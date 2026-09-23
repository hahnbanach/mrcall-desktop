"""Installing `blob_versions` on a company store that already has memory.

Same three guarantees the journal's migration test holds the journal to, for
the same reason: several engines boot against one company file, so the table
must arrive idempotently, survive an interruption, and — the one that matters
most — leave every blob row byte-for-byte as it was. A retention table that
rewrote a blob on install would be the very failure it exists to prevent.
"""

from __future__ import annotations

import sqlite3
import uuid

import pytest
from sqlalchemy import text

from tests.memory.mnemonic_env import blob_table_digest
from zylch.memory.store import memory_db_path, open_memory_engine, prepare_store
from zylch.storage import database as dbm
from zylch.storage.database import MEMORY_TABLE_NAMES

VERSIONS = "blob_versions"
COMPANY = "VVVVVVVVVVVVVVVVVVVVVV"
PERSON = (
    "#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Giulia Verdi\n"
    "Email: giulia@cliente.test\n#ABOUT\nRuns procurement for the Milan warehouse."
)


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Override the root conftest's Supabase-era autouse fixture."""
    yield


@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_DB_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("MEMORY_KEY", COMPANY)
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    yield tmp_path / "memory"
    dbm.dispose_engine()


def _pre_versions_store(path, *, blobs: int = 2) -> None:
    """A company store exactly as milestone 4 left it: every memory table but this one."""
    from sqlalchemy import create_engine

    from zylch.storage.models import Base

    engine = create_engine(f"sqlite:///{path}")
    tables = [t for t in Base.metadata.sorted_tables if t.name in set(MEMORY_TABLE_NAMES)]
    Base.metadata.create_all(engine, tables=[t for t in tables if t.name != VERSIONS])
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO memory_meta (id, company_key, self_notion, mutation_seq, "
                "last_sweep_seq, created_by_source) VALUES (1, :k, NULL, 3, 0, 'mint')"
            ),
            {"k": COMPANY},
        )
        for index in range(blobs):
            conn.execute(
                text(
                    "INSERT INTO blobs (id, owner_id, company_key, namespace, content, "
                    "embedding, events, created_at, updated_at) VALUES "
                    "(:id, 'uid-a', :k, :ns, :content, :emb, '[]', "
                    "'2026-09-01 10:00:00', '2026-09-01 10:00:00')"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "k": COMPANY,
                    "ns": f"user:{COMPANY}",
                    "content": f"{PERSON}\n#HISTORY\n- row {index}",
                    "emb": b"\x01\x02\x03\x04",
                },
            )
    engine.dispose()


def _tables(path) -> set:
    conn = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        conn.close()


def _indexes(path, table) -> set:
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA index_list('{table}')").fetchall()}
    finally:
        conn.close()


def _foreign_keys(path, table) -> list:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"PRAGMA foreign_key_list('{table}')").fetchall()
    finally:
        conn.close()


def _migrate(path):
    engine = open_memory_engine(COMPANY, create=True)
    try:
        prepare_store(engine, COMPANY, created_by="mint")
    finally:
        engine.dispose()


def test_an_existing_store_gains_the_table_and_keeps_its_blobs_byte_for_byte(store_dir):
    path = memory_db_path(COMPANY)
    _pre_versions_store(path)
    before = blob_table_digest(path)
    assert VERSIONS not in _tables(path)

    _migrate(path)

    assert VERSIONS in _tables(path)
    assert blob_table_digest(path) == before


def test_an_empty_store_is_created_with_the_table_already_in_it(store_dir):
    _migrate(memory_db_path(COMPANY))
    assert VERSIONS in _tables(memory_db_path(COMPANY))


def test_running_the_migration_twice_changes_nothing(store_dir):
    path = memory_db_path(COMPANY)
    _pre_versions_store(path)
    _migrate(path)
    digest, tables, indexes = (
        blob_table_digest(path),
        _tables(path),
        _indexes(path, VERSIONS),
    )
    _migrate(path)
    assert (blob_table_digest(path), _tables(path), _indexes(path, VERSIONS)) == (
        digest,
        tables,
        indexes,
    )


def test_blob_id_is_indexed_and_carries_no_cascading_foreign_key(store_dir):
    """The one schema decision that had to be made on purpose.

    Foreign keys are enforced on this store, so a cascade from `blobs.id` would
    delete a dropped donor's retained text in the transaction that retains it.
    The column is indexed for the reads and constrained by nothing.
    """
    path = memory_db_path(COMPANY)
    _migrate(path)
    assert _foreign_keys(path, VERSIONS) == []
    assert any("blob_id" in name for name in _indexes(path, VERSIONS))


def test_an_upgraded_store_gains_the_departure_column(store_dir):
    """`memory_operations.departure` is added by the column pass, not by `create_all`.

    A store that already holds the journal never goes through `create_all` for
    that table again, so the column can only arrive through
    `_apply_column_migrations` inside `prepare_store`'s ensure pass. Built by
    dropping the column from a current store, because every store this test
    can construct from the ORM already has it.
    """
    path = memory_db_path(COMPANY)
    _pre_versions_store(path)
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE memory_operations DROP COLUMN departure")
    conn.commit()
    conn.close()
    before = blob_table_digest(path)

    engine = open_memory_engine(COMPANY, create=False)
    try:
        prepare_store(engine, COMPANY, created_by="mint")
    finally:
        engine.dispose()

    conn = sqlite3.connect(path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_operations)")}
    conn.close()
    assert "departure" in columns
    assert blob_table_digest(path) == before
