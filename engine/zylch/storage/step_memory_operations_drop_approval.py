"""Memory-store step ``0002_memory_operations_drop_approval``.

``memory_operations.approval`` is gone from the model; a store created before
that still carries the column. SQLite's ``ALTER TABLE … DROP COLUMN`` exists
only from 3.35 and is not idempotent, so the table is rebuilt instead: create
``memory_operations_new`` in the model's shape, copy every other column of
every row, drop the old table, rename, and recreate every index ``create_all``
gives the model — the two named ones and the four single-column ones.

The DDL is literal and equal to what ``create_all`` emits for the model, so a
rebuilt store and a fresh one carry the same columns and the same indexes.
Idempotent over a partially reverted store: a table without ``approval``, or no
table at all, is left alone. Destructive, so the runner backs the file up
before it runs.
"""

from __future__ import annotations

import logging

from sqlalchemy import Connection

from zylch.storage.migrations import MigrationStep

logger = logging.getLogger(__name__)

STEP_ID = "0002_memory_operations_drop_approval"
DROPPED = "approval"

COLUMNS = (
    "event_id",
    "company_key",
    "owner_id",
    "parent_event_id",
    "protocol_version",
    "input_digest",
    "proposal_digest",
    "source_ref",
    "origin",
    "caller_class",
    "target_family",
    "state",
    "allowance",
    "attempts",
    "lease",
    "payload",
    "departure",
    "result",
    "pending_effects",
    "restrictions",
    "created_at",
    "updated_at",
)

CREATE_NEW = (
    "CREATE TABLE memory_operations_new (\n"
    "\tevent_id VARCHAR(64) NOT NULL, \n"
    "\tcompany_key TEXT NOT NULL, \n"
    "\towner_id TEXT NOT NULL, \n"
    "\tparent_event_id VARCHAR(64), \n"
    "\tprotocol_version INTEGER NOT NULL, \n"
    "\tinput_digest TEXT NOT NULL, \n"
    "\tproposal_digest TEXT, \n"
    "\tsource_ref TEXT NOT NULL, \n"
    "\torigin TEXT NOT NULL, \n"
    "\tcaller_class TEXT NOT NULL, \n"
    "\ttarget_family TEXT, \n"
    "\tstate TEXT NOT NULL, \n"
    "\tallowance INTEGER NOT NULL, \n"
    "\tattempts INTEGER NOT NULL, \n"
    "\tlease TEXT, \n"
    "\tpayload JSON, \n"
    "\tdeparture JSON, \n"
    "\tresult JSON, \n"
    "\tpending_effects JSON, \n"
    "\trestrictions JSON, \n"
    "\tcreated_at DATETIME, \n"
    "\tupdated_at DATETIME, \n"
    "\tPRIMARY KEY (event_id)\n"
    ")"
)

INDEXES = (
    "CREATE INDEX ix_memory_operations_company_key ON memory_operations (company_key)",
    "CREATE INDEX ix_memory_operations_owner_id ON memory_operations (owner_id)",
    "CREATE INDEX ix_memory_operations_parent_event_id ON memory_operations (parent_event_id)",
    "CREATE INDEX ix_memory_operations_state ON memory_operations (state)",
    "CREATE INDEX ix_memory_operations_company_state ON memory_operations (company_key, state)",
    "CREATE INDEX ix_memory_operations_company_source "
    "ON memory_operations (company_key, source_ref)",
)


def _columns(conn: Connection) -> set:
    rows = conn.exec_driver_sql("PRAGMA table_info(memory_operations)").fetchall()
    return {row[1] for row in rows}


def apply(conn: Connection) -> None:
    present = _columns(conn)
    if DROPPED not in present:
        logger.info(f"[migrate] {STEP_ID}: no {DROPPED} column; nothing to rebuild")
        return
    cols = ", ".join(COLUMNS)
    conn.exec_driver_sql("DROP TABLE IF EXISTS memory_operations_new")
    conn.exec_driver_sql(CREATE_NEW)
    conn.exec_driver_sql(
        f"INSERT INTO memory_operations_new ({cols}) SELECT {cols} FROM memory_operations"
    )
    rows = conn.exec_driver_sql("SELECT COUNT(*) FROM memory_operations_new").scalar_one()
    conn.exec_driver_sql("DROP TABLE memory_operations")
    conn.exec_driver_sql("ALTER TABLE memory_operations_new RENAME TO memory_operations")
    for ddl in INDEXES:
        conn.exec_driver_sql(ddl)
    logger.info(f"[migrate] {STEP_ID}: rebuilt memory_operations without {DROPPED} ({rows} rows)")


STEP = MigrationStep(
    id=STEP_ID,
    apply=apply,
    destructive=True,
    description="memory_operations rebuilt without the approval column",
)
