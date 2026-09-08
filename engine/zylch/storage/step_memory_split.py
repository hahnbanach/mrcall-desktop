"""Migration step ``0002_memory_split`` — memory tables leave ``zylch.db``.

The six memory tables move out of the per-profile database (which also
holds mail, tasks, tokens and sync cursors — never shareable) into one
store per company. SQLite cannot make a transaction spanning two files
atomic under WAL, so the step is shaped to be **crash-atomic and
idempotent by construction**:

1. take the company store (creating it only under a vouched provenance —
   this profile is pre-split, which ``schema_version`` proves, or its key
   was minted or provisioned);
2. **copy-if-absent by primary key** every row of the six tables into the
   store, committed on the store's own engine;
3. **drop** the six tables from ``zylch.db`` and **record the step** — in
   one ``zylch.db`` transaction, last.

A crash between 2 and 3 leaves the step unrecorded and the rows in both
places; the re-run copies nothing (already present by PK) and drops. The
tables are dropped, not left as frozen copies: the reverse copies them
back per profile from the store, filtered by ``owner_id`` (provenance).
"""

from __future__ import annotations

import logging
from typing import Dict

from sqlalchemy import Connection, Engine

from zylch.storage.migrations import MigrationStep

logger = logging.getLogger(__name__)

STEP_ID = "0002_memory_split"

# Copy order respects the FK to blobs inside the store.
MEMORY_TABLES = (
    "blobs",
    "blob_sentences",
    "email_blobs",
    "calendar_blobs",
    "whatsapp_blobs",
    "person_identifiers",
)


def _tables_present(conn: Connection) -> set:
    rows = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def _columns(conn: Connection, table: str) -> list:
    return [r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()]


def copy_if_absent(src: Connection, dst_engine: Engine, tables=MEMORY_TABLES) -> Dict[str, int]:
    """Copy every row of ``tables`` from ``src`` into ``dst_engine`` by PK. Idempotent."""
    counts: Dict[str, int] = {}
    present = _tables_present(src)
    with dst_engine.begin() as dst:
        dst_present = _tables_present(dst)
        for table in tables:
            if table not in present or table not in dst_present:
                counts[table] = 0
                continue
            src_cols = _columns(src, table)
            dst_cols = set(_columns(dst, table))
            cols = [c for c in src_cols if c in dst_cols]
            col_list = ", ".join(cols)
            placeholders = ", ".join("?" for _ in cols)
            rows = src.exec_driver_sql(f"SELECT {col_list} FROM {table}").fetchall()
            n = 0
            for row in rows:
                res = dst.exec_driver_sql(
                    f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})",
                    tuple(row),
                )
                n += res.rowcount or 0
            counts[table] = n
    return counts


def apply(conn: Connection) -> None:
    from zylch.storage.database import attach_memory_store

    present = _tables_present(conn)
    has_rows = False
    if "blobs" in present:
        has_rows = conn.exec_driver_sql("SELECT 1 FROM blobs LIMIT 1").first() is not None

    # The profile is pre-split (it still holds the tables): that is the
    # migration provenance, and the store may be created for it.
    memory_engine = attach_memory_store(migrating=("blobs" in present))
    if memory_engine is None:
        # Memory unavailable (typed key with no store). Nothing can move;
        # if the profile held rows we must not drop them — leave the
        # tables and let the step re-run on a later boot once a store
        # exists. Recording without moving would strand the rows.
        if has_rows:
            raise RuntimeError(
                "memory store unavailable while the profile still holds memory rows; "
                "the split will retry on the next boot"
            )
        logger.info(f"[migrate] {STEP_ID}: no store and no rows to move — recorded")
        return

    counts = copy_if_absent(conn, memory_engine)
    for table in MEMORY_TABLES:
        if table in present:
            conn.exec_driver_sql(f"DROP TABLE {table}")
    logger.info(f"[migrate] {STEP_ID}: moved {counts} into the company store; tables dropped")


def reverse_into_profile(
    profile_engine: Engine, memory_engine: Engine, owner_id: str
) -> Dict[str, int]:
    """Rollback: this profile's rows (by provenance) back into ``zylch.db``.

    Exact only until the first shared tick: after a merge a survivor
    carries one ``owner_id``, and rows this profile contributed to another
    account's blob come back through ``fact_history`` (facts) or not at
    all (entities) — the pre-split backup is the exact restore then.
    """
    from zylch.storage.database import profile_tables, memory_tables
    from zylch.storage.migrations import unrecord_step
    from zylch.storage.models import Base

    _ = profile_tables  # kept for symmetry with the forward step's imports
    Base.metadata.create_all(profile_engine, tables=memory_tables())
    counts: Dict[str, int] = {}
    with memory_engine.begin() as src:
        with profile_engine.begin() as dst:
            for table in MEMORY_TABLES:
                cols = _columns(src, table)
                col_list = ", ".join(cols)
                placeholders = ", ".join("?" for _ in cols)
                where = "WHERE owner_id = ?" if "owner_id" in cols else ""
                params = (owner_id,) if where else ()
                rows = src.exec_driver_sql(
                    f"SELECT {col_list} FROM {table} {where}", params
                ).fetchall()
                n = 0
                for row in rows:
                    res = dst.exec_driver_sql(
                        f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})",
                        tuple(row),
                    )
                    n += res.rowcount or 0
                counts[table] = n
    unrecord_step(profile_engine, STEP_ID)
    logger.info(f"[migrate] {STEP_ID}: reversed for owner={owner_id}: {counts}")
    return counts


STEP = MigrationStep(
    id=STEP_ID,
    apply=apply,
    destructive=True,
    description="memory tables move to the company store; dropped from zylch.db",
)
