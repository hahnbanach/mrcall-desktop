"""Single-owner, idempotent schema migration runner for the SQLite stores.

One process migrates a given database file at a time; every other process
that reaches the same file **blocks** until the owner is done, then finds the
work recorded and continues. Nobody skips: a process that skipped would keep
booting and serve new code against a file the owner is still rewriting, and
``PRAGMA busy_timeout`` waits on a blocked statement, not on a column nobody
has added yet.

The lock is keyed by the database file — ``<db>.migrate.lock`` beside it —
and is deliberately NOT the per-profile lock in ``zylch.cli.profiles``: the
serving process already holds that one for its lifetime, and a second
``flock`` on the same path from a fresh descriptor conflicts with the
process's own lock. Where two files are migrated in one boot (profile DB and
company memory store) the order is always profile first, then company.

Three kinds of work run under the lock, in this order:

1. **Ensure passes** — ``create_all`` with an explicit table list, the column
   ensure list, index ensure. Idempotent, cheap, run on every boot.
2. **Versioned steps** — run once, recorded in ``schema_version``. A step
   receives a ``Connection`` already inside a transaction; the record of the
   step lands in that same transaction, so a crash mid-step leaves the step
   unrecorded and it re-runs, never half-recorded. Steps that rewrite or drop
   existing rows are ``destructive`` and trigger a backup of the file first.
3. **Data backfills** — idempotent row-level fixes, run on every boot.

Backups use ``sqlite3.Connection.backup`` — never a raw file copy, because
under WAL the ``-wal`` pages are not in the main file and a copy is not a
backup. ``restore_sqlite`` is the tested reverse.

POSIX only (``fcntl``), like the profile lock it sits beside.
"""

from __future__ import annotations

import fcntl
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Generator, Iterable, Sequence

from sqlalchemy import Connection, Engine, text

logger = logging.getLogger(__name__)

LOCK_SUFFIX = ".migrate.lock"
SCHEMA_VERSION_TABLE = "schema_version"
BACKUPS_DIRNAME = "backups"
# A hung owner must not hang every other process forever: past this bound
# the waiter raises, exits non-zero, and systemd's Restart=on-failure fires.
DEFAULT_LOCK_TIMEOUT_S = 300.0
_POLL_S = 0.05


class MigrationLockTimeout(RuntimeError):
    """Raised when the migration lock could not be taken within the bound."""


@dataclass(frozen=True)
class MigrationStep:
    """One versioned schema/data change, applied at most once per file.

    ``id`` orders steps lexically (``0001_…``, ``0002_…``) and is the key in
    ``schema_version``. ``apply`` runs inside a transaction on the file being
    migrated and must be idempotent over a partially-reverted database — the
    reverse path un-records the step and the forward path re-runs it.
    ``destructive`` marks a step that rewrites rows in place or drops them;
    the file is backed up before any pending destructive step runs.
    """

    id: str
    apply: Callable[[Connection], None]
    destructive: bool = False
    description: str = ""


@contextmanager
def db_file_lock(
    db_path: str,
    timeout_s: float = DEFAULT_LOCK_TIMEOUT_S,
) -> Generator[None, None, None]:
    """Hold the migration lock for ``db_path``: bounded blocking wait.

    ``flock`` has no timeout of its own, so this is ``LOCK_NB`` in a poll
    loop against a deadline. The kernel releases the lock when the holder
    dies, so a crashed owner never wedges the file.
    """
    lock_path = db_path + LOCK_SUFFIX
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    fd = open(lock_path, "w")
    deadline = time.monotonic() + timeout_s
    try:
        waited = False
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, IOError):
                if time.monotonic() >= deadline:
                    raise MigrationLockTimeout(
                        f"migration lock on {db_path} not acquired within {timeout_s:.0f}s"
                    )
                if not waited:
                    logger.info(f"[migrate] waiting for migration lock on {db_path}")
                    waited = True
                time.sleep(_POLL_S)
        fd.write(str(os.getpid()))
        fd.flush()
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            fd.close()


def ensure_schema_version_table(conn: Connection) -> None:
    conn.exec_driver_sql(
        f"CREATE TABLE IF NOT EXISTS {SCHEMA_VERSION_TABLE} "
        "(id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )


def applied_step_ids(engine: Engine) -> set[str]:
    with engine.begin() as conn:
        ensure_schema_version_table(conn)
        rows = conn.execute(text(f"SELECT id FROM {SCHEMA_VERSION_TABLE}")).fetchall()
    return {r[0] for r in rows}


def record_step(conn: Connection, step_id: str) -> None:
    """Mark ``step_id`` applied — call inside the step's own transaction."""
    conn.execute(
        text(f"INSERT OR REPLACE INTO {SCHEMA_VERSION_TABLE} (id, applied_at) VALUES (:id, :at)"),
        {"id": step_id, "at": datetime.now(timezone.utc).isoformat()},
    )


def unrecord_step(engine: Engine, step_id: str) -> None:
    """Forget ``step_id`` so the next boot re-applies it.

    This is half of a rollback: the other half is the step's own reverse.
    Un-recording without reversing re-runs the forward step over already
    migrated data, which every step must tolerate (idempotence).
    """
    with engine.begin() as conn:
        ensure_schema_version_table(conn)
        conn.execute(text(f"DELETE FROM {SCHEMA_VERSION_TABLE} WHERE id = :id"), {"id": step_id})


def backup_sqlite(db_path: str, label: str) -> str:
    """Snapshot ``db_path`` through the SQLite backup API; returns the path."""
    backups_dir = os.path.join(os.path.dirname(db_path), BACKUPS_DIRNAME)
    os.makedirs(backups_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dst_path = os.path.join(backups_dir, f"{os.path.basename(db_path)}.{label}.{stamp}.bak")
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dst_path)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    logger.info(f"[migrate] backup written: {dst_path}")
    return dst_path


def restore_sqlite(backup_path: str, db_path: str) -> None:
    """Overwrite ``db_path`` with ``backup_path``'s content.

    The caller must have disposed every engine on ``db_path`` first; this
    writes through a fresh connection's pager so an existing ``-wal`` is
    honoured rather than orphaned.
    """
    src = sqlite3.connect(backup_path)
    dst = sqlite3.connect(db_path)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    logger.info(f"[migrate] restored {db_path} from {backup_path}")


def run_migrations(
    engine: Engine,
    db_path: str,
    *,
    ensure: Sequence[Callable[[Engine], None]] = (),
    steps: Sequence[MigrationStep] = (),
    backfills: Sequence[Callable[[], None]] = (),
    lock_timeout_s: float = DEFAULT_LOCK_TIMEOUT_S,
) -> list[str]:
    """Migrate one database file as its single owner. Returns applied step ids.

    ``ensure`` passes run every time (``create_all`` and friends), ``steps``
    run once each and are recorded, ``backfills`` run every time after the
    schema is settled. Everything happens under the file's migration lock,
    so a process that returns from here is guaranteed to see a file no
    other process is still rewriting.
    """
    with db_file_lock(db_path, timeout_s=lock_timeout_s):
        with engine.begin() as conn:
            ensure_schema_version_table(conn)
        for fn in ensure:
            fn(engine)

        already = applied_step_ids(engine)
        pending = [s for s in steps if s.id not in already]
        if any(s.destructive for s in pending):
            labels = "+".join(s.id for s in pending if s.destructive)
            backup_sqlite(db_path, label=labels)

        applied: list[str] = []
        for step in pending:
            logger.info(f"[migrate] applying {step.id}: {step.description or ''}".rstrip())
            with engine.begin() as conn:
                step.apply(conn)
                record_step(conn, step.id)
            applied.append(step.id)

        for fn in backfills:
            fn()
    return applied


def pending_step_ids(engine: Engine, steps: Iterable[MigrationStep]) -> list[str]:
    """Which of ``steps`` would run on the next boot — for tests and doctors."""
    already = applied_step_ids(engine)
    return [s.id for s in steps if s.id not in already]
