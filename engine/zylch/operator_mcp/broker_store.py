"""Private durable authorization records with atomic secret consumption."""

import hashlib
import json
import os
import sqlite3
import stat
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class StorageError(Exception):
    """A content-free storage refusal."""


class BrokerStore:
    NAMESPACES = frozenset({"clients", "pending", "grants", "codes", "access", "refresh"})
    MAX_PAYLOAD_BYTES = 65536

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path).absolute()
        self._transactions: set[sqlite3.Connection] = set()
        self._lock = threading.Lock()
        with self.transaction() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS records ("
                "namespace TEXT NOT NULL, keyhash TEXT NOT NULL, payload TEXT NOT NULL, "
                "consumed INTEGER NOT NULL DEFAULT 0 CHECK(consumed IN (0, 1)), "
                "PRIMARY KEY(namespace, keyhash))"
            )

    @staticmethod
    def _check_file(metadata: os.stat_result) -> None:
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
        ):
            raise StorageError("unsafe store file")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        directory_fd = None
        file_fd = None
        connection = None
        try:
            if self.path.parent.resolve() != self.path.parent:
                raise StorageError("unsafe store directory")
            directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            directory = os.fstat(directory_fd)
            if directory.st_uid != os.getuid() or stat.S_IMODE(directory.st_mode) != 0o700:
                raise StorageError("unsafe store directory")
            try:
                file_fd = os.open(
                    self.path.name,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory_fd,
                )
            except FileExistsError:
                file_fd = os.open(self.path.name, os.O_RDWR | os.O_NOFOLLOW, dir_fd=directory_fd)
            metadata = os.fstat(file_fd)
            self._check_file(metadata)
            anchored_path = f"/proc/self/fd/{directory_fd}/{self.path.name}"
            connection = sqlite3.connect(anchored_path, timeout=10, isolation_level=None)
            current = os.stat(self.path.name, dir_fd=directory_fd, follow_symlinks=False)
            self._check_file(current)
            if (metadata.st_dev, metadata.st_ino) != (current.st_dev, current.st_ino):
                raise StorageError("store file changed")
            connection.execute("PRAGMA trusted_schema=OFF")
            yield connection
        except (OSError, sqlite3.Error):
            raise StorageError("store unavailable") from None
        finally:
            if connection is not None:
                connection.close()
            if file_fd is not None:
                os.close(file_fd)
            if directory_fd is not None:
                os.close(directory_fd)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            with self._lock:
                self._transactions.add(connection)
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                with self._lock:
                    self._transactions.discard(connection)

    @contextmanager
    def _use(self, connection: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
        if connection is None:
            with self.transaction() as active:
                yield active
        else:
            with self._lock:
                admitted = connection in self._transactions
            if not admitted or not connection.in_transaction:
                raise StorageError("invalid store transaction")
            try:
                yield connection
            except sqlite3.Error:
                raise StorageError("store unavailable") from None

    @classmethod
    def _namespace(cls, namespace: str) -> None:
        if not isinstance(namespace, str) or namespace not in cls.NAMESPACES:
            raise StorageError("invalid record namespace")

    @classmethod
    def _keyhash(cls, namespace: str, key: str) -> str:
        cls._namespace(namespace)
        if not isinstance(key, str) or not key or len(key) > 4096:
            raise StorageError("invalid record key")
        try:
            return hashlib.sha256((namespace + "\x00" + key).encode("utf-8")).hexdigest()
        except UnicodeError:
            raise StorageError("invalid record key") from None

    @classmethod
    def _encode(cls, payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            raise StorageError("invalid record payload")

        def validate(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if (
                        not isinstance(key, str)
                        or key in {"token", "code", "access_token", "refresh_token", "_consumed"}
                        or (key == "client_secret" and item is not None)
                    ):
                        raise StorageError("invalid record payload")
                    validate(item)
            elif isinstance(value, list):
                for item in value:
                    validate(item)
            elif value is not None and not isinstance(value, (str, int, float, bool)):
                raise StorageError("invalid record payload")

        try:
            validate(payload)
            encoded = json.dumps(payload, allow_nan=False, ensure_ascii=True, separators=(",", ":"))
            if len(encoded.encode("utf-8")) > cls.MAX_PAYLOAD_BYTES:
                raise StorageError("record payload too large")
            return encoded
        except (TypeError, ValueError, RecursionError, UnicodeError):
            raise StorageError("invalid record payload") from None

    @classmethod
    def _decode(cls, encoded: str) -> dict[str, Any]:
        try:
            if not isinstance(encoded, str) or len(encoded.encode("utf-8")) > cls.MAX_PAYLOAD_BYTES:
                raise StorageError("invalid stored record")
            decoded = json.loads(encoded)
            cls._encode(decoded)
            return decoded
        except (TypeError, ValueError, RecursionError):
            raise StorageError("invalid stored record") from None

    def get(
        self,
        namespace: str,
        key: str,
        include_consumed: bool = False,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        keyhash = self._keyhash(namespace, key)
        with self._use(connection) as active:
            row = active.execute(
                "SELECT payload, consumed FROM records WHERE namespace=? AND keyhash=?",
                (namespace, keyhash),
            ).fetchone()
        if row is None or (row[1] and not include_consumed):
            return None
        result = self._decode(row[0])
        if include_consumed:
            result["_consumed"] = bool(row[1])
        return result

    def put(
        self,
        namespace: str,
        key: str,
        payload: dict[str, Any],
        connection: sqlite3.Connection | None = None,
        overwrite: bool = False,
    ) -> None:
        keyhash, encoded = self._keyhash(namespace, key), self._encode(payload)
        with self._use(connection) as active:
            if overwrite:
                active.execute(
                    "INSERT INTO records(namespace,keyhash,payload) VALUES(?,?,?) "
                    "ON CONFLICT(namespace,keyhash) DO UPDATE SET payload=excluded.payload",
                    (namespace, keyhash, encoded),
                )
            else:
                try:
                    active.execute(
                        "INSERT INTO records(namespace,keyhash,payload) VALUES(?,?,?)",
                        (namespace, keyhash, encoded),
                    )
                except sqlite3.IntegrityError:
                    raise StorageError("record already exists") from None

    def update(
        self,
        namespace: str,
        key: str,
        payload: dict[str, Any],
        connection: sqlite3.Connection | None = None,
    ) -> None:
        keyhash, encoded = self._keyhash(namespace, key), self._encode(payload)
        with self._use(connection) as active:
            result = active.execute(
                "UPDATE records SET payload=? WHERE namespace=? AND keyhash=?",
                (encoded, namespace, keyhash),
            )
            if result.rowcount != 1:
                raise StorageError("record not found")

    def consume(
        self, namespace: str, key: str, connection: sqlite3.Connection | None = None
    ) -> dict[str, Any] | None:
        keyhash = self._keyhash(namespace, key)
        with self._use(connection) as active:
            row = active.execute(
                "SELECT payload FROM records WHERE namespace=? AND keyhash=? AND consumed=0",
                (namespace, keyhash),
            ).fetchone()
            if row is None:
                return None
            payload = self._decode(row[0])
            result = active.execute(
                "UPDATE records SET consumed=1 WHERE namespace=? AND keyhash=? AND consumed=0",
                (namespace, keyhash),
            )
            return payload if result.rowcount == 1 else None

    def list(
        self, namespace: str, connection: sqlite3.Connection | None = None
    ) -> list[dict[str, Any]]:
        self._namespace(namespace)
        with self._use(connection) as active:
            rows = active.execute(
                "SELECT payload FROM records WHERE namespace=? AND consumed=0 ORDER BY keyhash",
                (namespace,),
            ).fetchall()
        return [self._decode(row[0]) for row in rows]

    def count(self, namespace: str, connection: sqlite3.Connection | None = None) -> int:
        self._namespace(namespace)
        with self._use(connection) as active:
            return active.execute(
                "SELECT COUNT(*) FROM records WHERE namespace=?", (namespace,)
            ).fetchone()[0]
