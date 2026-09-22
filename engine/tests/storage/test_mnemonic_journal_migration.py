"""Installing the operation journal on a company store that already has memory.

The journal is an additive table in a file that holds a company's whole
memory, and several engines boot against that file. So the migration has to be
three things at once: idempotent (every engine runs it on every boot),
interruptible (a killed engine must leave a store the next one converges), and
provably inert towards the rows that were already there.

The last one is what the blob-table digest is for. "We only added a table" is
easy to say and easy to get wrong — a `create_all` over the wrong table list,
a column ensure pass that touches `blobs`, a step that rebuilds a table to add
an index. The digest covers every durable column of every blob row, so a
changed byte fails the test rather than quietly rewriting a company's memory.
"""

from __future__ import annotations

import sqlite3
import uuid

import pytest
from sqlalchemy import inspect, text

from zylch.memory.store import memory_db_path, open_memory_engine, prepare_store
from zylch.storage import database as dbm
from zylch.storage.database import MEMORY_TABLE_NAMES
from zylch.storage.migrations import applied_step_ids

from tests.memory.mnemonic_env import blob_table_digest

JOURNAL = "memory_operations"
COMPANY = "CCCCCCCCCCCCCCCCCCCCCC"

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


def _pre_journal_store(path, *, blobs: int = 2) -> None:
    """A company store exactly as it looked before this milestone.

    Built with `create_all` over the memory tables minus the journal, so the
    starting shape is the real previous schema rather than a hand-written
    approximation that could quietly differ.
    """
    from sqlalchemy import create_engine

    from zylch.storage.models import Base

    engine = create_engine(f"sqlite:///{path}")
    tables = [t for t in Base.metadata.sorted_tables if t.name in set(MEMORY_TABLE_NAMES)]
    Base.metadata.create_all(engine, tables=[t for t in tables if t.name != JOURNAL])
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


def _migrate(path):
    engine = open_memory_engine(COMPANY, create=True)
    try:
        prepare_store(engine, COMPANY, created_by="mint")
    finally:
        engine.dispose()


# ─── Old, empty and current stores ────────────────────────────────────


def test_an_existing_store_gains_the_journal_and_keeps_its_blobs_byte_for_byte(store_dir):
    path = memory_db_path(COMPANY)
    _pre_journal_store(path)
    before = blob_table_digest(path)
    assert JOURNAL not in _tables(path)

    _migrate(path)

    assert JOURNAL in _tables(path)
    assert blob_table_digest(path) == before


def test_an_empty_store_is_created_with_the_journal_already_in_it(store_dir):
    _migrate(memory_db_path(COMPANY))
    assert JOURNAL in _tables(memory_db_path(COMPANY))


def test_running_the_migration_twice_changes_nothing(store_dir):
    path = memory_db_path(COMPANY)
    _pre_journal_store(path)
    _migrate(path)
    digest, tables, indexes = (
        blob_table_digest(path),
        _tables(path),
        _indexes(path, JOURNAL),
    )

    _migrate(path)

    assert blob_table_digest(path) == digest
    assert _tables(path) == tables
    assert _indexes(path, JOURNAL) == indexes


def test_a_current_store_is_left_alone_including_its_recorded_steps(store_dir):
    path = memory_db_path(COMPANY)
    _pre_journal_store(path)
    _migrate(path)

    engine = open_memory_engine(COMPANY, create=False)
    try:
        steps = applied_step_ids(engine)
    finally:
        engine.dispose()

    _migrate(path)

    engine = open_memory_engine(COMPANY, create=False)
    try:
        assert applied_step_ids(engine) == steps
    finally:
        engine.dispose()


# ─── Interruption ─────────────────────────────────────────────────────


def test_an_interrupted_migration_converges_on_the_next_boot(store_dir, monkeypatch):
    """A killed engine must not leave a store the next one cannot finish."""
    path = memory_db_path(COMPANY)
    _pre_journal_store(path)
    before = blob_table_digest(path)

    import zylch.memory.store as store_mod

    real_columns = store_mod._ensure_memory_columns

    def die(engine):
        real_columns(engine)
        raise KeyboardInterrupt("engine killed mid-migration")

    monkeypatch.setattr(store_mod, "_ensure_memory_columns", die)
    with pytest.raises(KeyboardInterrupt):
        _migrate(path)

    monkeypatch.setattr(store_mod, "_ensure_memory_columns", real_columns)
    _migrate(path)

    assert JOURNAL in _tables(path)
    assert blob_table_digest(path) == before


def test_an_interruption_before_the_table_exists_still_converges(store_dir, monkeypatch):
    path = memory_db_path(COMPANY)
    _pre_journal_store(path)
    before = blob_table_digest(path)

    import zylch.memory.store as store_mod

    real_tables = store_mod._ensure_memory_tables
    monkeypatch.setattr(
        store_mod,
        "_ensure_memory_tables",
        lambda engine: (_ for _ in ()).throw(KeyboardInterrupt("killed before create_all")),
    )
    with pytest.raises(KeyboardInterrupt):
        _migrate(path)
    assert JOURNAL not in _tables(path)

    monkeypatch.setattr(store_mod, "_ensure_memory_tables", real_tables)
    _migrate(path)

    assert JOURNAL in _tables(path)
    assert blob_table_digest(path) == before


# ─── Shape ────────────────────────────────────────────────────────────


def test_the_journal_lands_in_the_company_store_and_not_the_profile(tmp_path, monkeypatch):
    """A profile-bound journal could not coordinate two profiles on one company.

    Which file a table lives in is decided by ``MEMORY_TABLE_NAMES``; getting
    it wrong is silent, so it is asserted from both sides.
    """
    assert JOURNAL in MEMORY_TABLE_NAMES
    monkeypatch.setenv("MEMORY_DB_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("MEMORY_KEY", COMPANY)
    monkeypatch.setenv("MEMORY_KEY_SOURCE", "mint")
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "zylch.db"))
    (tmp_path / ".env").write_text(f"MEMORY_KEY={COMPANY}\nMEMORY_KEY_SOURCE=mint\n")
    dbm.dispose_engine()
    try:
        dbm.init_db()
        assert JOURNAL not in _tables(tmp_path / "zylch.db")
        assert JOURNAL in _tables(memory_db_path(COMPANY))
    finally:
        dbm.dispose_engine()


def test_the_journal_carries_the_indexes_its_lookups_need(store_dir):
    _migrate(memory_db_path(COMPANY))
    engine = open_memory_engine(COMPANY, create=False)
    try:
        indexes = {index["name"] for index in inspect(engine).get_indexes(JOURNAL)}
    finally:
        engine.dispose()
    assert "ix_memory_operations_company_state" in indexes
    assert "ix_memory_operations_company_source" in indexes
