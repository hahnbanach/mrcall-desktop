"""Short read snapshots and serialized exact document commits."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from zylch.storage.database import get_engine
from zylch.workflows.errors import WorkflowError
from zylch.workflows.identity import Identity, check_same
from zylch.workflows.models import WorkflowDocument
from zylch.workflows.repository import ensure_tables

SOURCE_LIMIT = 16 * 1024 * 1024
RECEIPT_LIMIT = 20000
COLUMNS = "uid,digest,host_id,company_scope,generation,text_length,created_at"


@contextmanager
def zero_busy(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as connection:
        previous = connection.exec_driver_sql("PRAGMA busy_timeout").scalar()
        connection.exec_driver_sql("PRAGMA busy_timeout=0")
        try:
            yield connection
        finally:
            connection.rollback()
            connection.exec_driver_sql(f"PRAGMA busy_timeout={int(previous)}")


@dataclass(frozen=True)
class DatabaseIdentity:
    engine: object
    path: Path
    device: int
    inode: int


@dataclass(frozen=True)
class Capture:
    database: DatabaseIdentity
    document_id: str
    uid: str
    name: str
    size: int
    sha256: str
    state: str
    original: bytes
    metadata: dict[str, Any]
    receipts: tuple[tuple, ...]
    sources: tuple[bytes | str, ...]


def database_identity() -> DatabaseIdentity:
    engine = get_engine()
    path = Path(engine.url.database).resolve(strict=True)
    stat = path.stat()
    return DatabaseIdentity(engine, path, stat.st_dev, stat.st_ino)


def receipt_rows(session: Session) -> tuple[tuple, ...]:
    if not session.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='qonto_evidence_receipts'")
    ).first():
        return ()
    result = session.execute(text(f"SELECT {COLUMNS} FROM qonto_evidence_receipts"))
    rows = result.fetchmany(RECEIPT_LIMIT + 1)
    if len(rows) > RECEIPT_LIMIT:
        raise WorkflowError("operation_failed")
    return tuple(tuple(row) for row in rows)


def sources(session: Session, uid: str) -> tuple[bytes | str, ...]:
    found: list[bytes | str] = []
    remaining = SOURCE_LIMIT
    for table, columns in (
        ("qonto_conversations", ("canonical_history",)),
        ("workflow_runs", ("canonical_history", "output")),
        ("workflow_artifacts", ("original",)),
    ):
        for column in columns:
            try:
                result = session.execute(
                    text(
                        f"SELECT CASE WHEN length(CAST({column} AS BLOB)) <= :maximum THEN {column} ELSE NULL END FROM {table} WHERE uid=:uid"
                    ),
                    {"maximum": remaining, "uid": uid},
                )
                for (value,) in result:
                    if not isinstance(value, (str, bytes)):
                        continue
                    size = len(value.encode()) if isinstance(value, str) else len(value)
                    if size > remaining or len(found) >= 1000:
                        return tuple(found)
                    if size <= remaining:
                        found.append(value)
                        remaining -= size
                    if remaining == 0:
                        return tuple(found)
            except SQLAlchemyError:
                continue
    return tuple(found)


def capture(identity: Identity, document_id: str) -> Capture:
    from zylch.workflows.documents import _metadata, _owned

    check_same(identity)
    engine = get_engine()
    with zero_busy(engine) as connection:
        installed = inspect(connection).has_table(WorkflowDocument.__tablename__)
    if not installed:
        ensure_tables(identity)
    database = database_identity()
    with zero_busy(engine) as connection:
        connection.exec_driver_sql("BEGIN")
        with Session(bind=connection, expire_on_commit=False) as session:
            row = _owned(session, WorkflowDocument, document_id, identity, "document_unavailable")
            rows = receipt_rows(session)
            originals = sources(session, identity.uid) if any(r[5] for r in rows) else ()
            result = Capture(
                database,
                row.id,
                row.uid,
                row.name,
                row.size,
                row.sha256,
                row.state,
                bytes(row.original),
                _metadata(row),
                rows,
                originals,
            )
    check_same(identity)
    if database_identity() != database:
        raise WorkflowError("binding_changed")
    return result


def commit(
    identity: Identity, before: Capture, combined: bytes, result: dict[str, Any], finish: bool
) -> dict[str, Any] | None:
    from zylch.workflows.documents import _metadata, _owned

    check_same(identity)
    if database_identity() != before.database:
        raise WorkflowError("binding_changed")
    engine = get_engine()
    with engine.connect() as connection:
        previous_timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar()
        connection.exec_driver_sql("PRAGMA busy_timeout=0")
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            with Session(bind=connection, expire_on_commit=False) as session:
                check_same(identity)
                if database_identity() != before.database:
                    raise WorkflowError("binding_changed")
                if sorted(receipt_rows(session)) != sorted(before.receipts):
                    connection.rollback()
                    return None
                row = _owned(
                    session, WorkflowDocument, before.document_id, identity, "document_unavailable"
                )
                same = (row.uid, row.name, row.size, row.sha256, row.original) == (
                    before.uid,
                    before.name,
                    before.size,
                    before.sha256,
                    before.original,
                )
                if not same:
                    raise WorkflowError("upload_invalid")
                if finish and row.state == "ready":
                    if row.text != result["text"] or row.limitations != result["limitations"]:
                        raise WorkflowError("upload_invalid")
                    value = _metadata(row)
                else:
                    if row.state != before.state or row.state != "uploading":
                        raise WorkflowError("upload_invalid")
                    if finish:
                        duplicate = (
                            session.query(WorkflowDocument)
                            .filter_by(uid=identity.uid, sha256=row.sha256, state="ready")
                            .first()
                        )
                        row.duplicate_of = duplicate.id if duplicate else None
                        row.text, row.limitations, row.state = (
                            result["text"],
                            result["limitations"],
                            "ready",
                        )
                        value = _metadata(row)
                    else:
                        row.original = combined
                        value = {"document_id": row.id, "received": len(combined)}
                    session.flush()
                check_same(identity)
                connection.commit()
                return value
        finally:
            connection.rollback()
            connection.exec_driver_sql(f"PRAGMA busy_timeout={int(previous_timeout)}")


def busy(error: OperationalError) -> bool:
    return getattr(error.orig, "sqlite_errorcode", None) in {5, 6}
