"""Memory-store step ``0001_identifiers_company_unique``.

``person_identifiers`` was unique per (owner, kind, value, blob): every
account indexing the same identifier on the same blob wrote its own row.
The index belongs to the company, so the constraint becomes
(company_key, kind, value, blob) and the duplicates collapse to one row.

SQLite cannot alter a constraint in place: rebuild the table (create the
new shape, copy with INSERT OR IGNORE so duplicates fold, drop, rename,
recreate the indexes), all inside the step's transaction on the store.
Idempotent: a store already in the new shape is left alone.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

from zylch.storage.migrations import MigrationStep

logger = logging.getLogger(__name__)

STEP_ID = "0001_identifiers_company_unique"
NEW_CONSTRAINT = "person_identifiers_company_kind_value_blob_unique"


def _has_new_constraint(conn: Connection) -> bool:
    rows = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='person_identifiers'"
    ).fetchall()
    return bool(rows) and NEW_CONSTRAINT in (rows[0][0] or "")


def apply(conn: Connection) -> None:
    present = {
        r[0]
        for r in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "person_identifiers" not in present or _has_new_constraint(conn):
        logger.info(f"[migrate] {STEP_ID}: nothing to rebuild")
        return
    conn.exec_driver_sql("DROP TABLE IF EXISTS person_identifiers_new")
    conn.exec_driver_sql(
        "CREATE TABLE person_identifiers_new ("
        " id VARCHAR(36) NOT NULL PRIMARY KEY,"
        " owner_id TEXT NOT NULL,"
        " company_key TEXT,"
        " blob_id VARCHAR(36) NOT NULL REFERENCES blobs(id) ON DELETE CASCADE,"
        " kind TEXT NOT NULL,"
        " value TEXT NOT NULL,"
        " created_at DATETIME,"
        f" CONSTRAINT {NEW_CONSTRAINT} UNIQUE (company_key, kind, value, blob_id))"
    )
    res = conn.exec_driver_sql(
        "INSERT OR IGNORE INTO person_identifiers_new "
        "(id, owner_id, company_key, blob_id, kind, value, created_at) "
        "SELECT id, owner_id, company_key, blob_id, kind, value, created_at "
        "FROM person_identifiers ORDER BY created_at, id"
    )
    before = conn.exec_driver_sql("SELECT COUNT(*) FROM person_identifiers").scalar_one()
    conn.exec_driver_sql("DROP TABLE person_identifiers")
    conn.exec_driver_sql("ALTER TABLE person_identifiers_new RENAME TO person_identifiers")
    for col in ("owner_id", "company_key", "blob_id"):
        conn.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS ix_person_identifiers_{col} ON person_identifiers({col})"
        )
    logger.info(
        f"[migrate] {STEP_ID}: rebuilt person_identifiers unique per company "
        f"({before} rows -> {res.rowcount})"
    )


STEP = MigrationStep(
    id=STEP_ID,
    apply=apply,
    destructive=True,
    description="person_identifiers unique per company; duplicate owner rows folded",
)
