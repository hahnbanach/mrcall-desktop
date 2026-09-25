"""Removing ``memory_operations.approval`` from a company store that already has a journal.

The step rebuilds the one table every semantic write records into, on a file
several engines boot against. So it has to leave every other byte of every row
where it was, give the rebuilt table the same indexes a fresh store gets, do
nothing on a store already in shape (a second boot, a partially reverted one),
back the file up first, and leave a backup that restores into the same company
path, migrates again and still replays what the journal recorded.

The old shape is written as literal DDL — the model's columns with ``approval``
between ``payload`` and ``departure``, where a store created before the removal
carries it — so the starting point does not depend on the code under test.
"""

from __future__ import annotations

import json
import os
import sqlite3

import pytest
from sqlalchemy import create_engine

from zylch.memory.mnemonic import journal
from zylch.memory.mnemonic.contracts import INTERACTIVE, OPERATOR_DELEGATED, MemoryEvent
from zylch.memory.store import memory_db_path, open_memory_engine, prepare_store
from zylch.storage import database as dbm
from zylch.storage.database import MEMORY_TABLE_NAMES
from zylch.storage.migrations import (
    BACKUPS_DIRNAME,
    applied_step_ids,
    ensure_schema_version_table,
    record_step,
    restore_sqlite,
    unrecord_step,
)
from zylch.storage.models import Base, MemoryOperation
from zylch.storage.step_memory_operations_drop_approval import STEP_ID, apply

from tests.memory.mnemonic_env import COMPANY_A, OWNER_A, boot, clear_process_state, reboot

JOURNAL = "memory_operations"
FRESH = "FFFFFFFFFFFFFFFFFFFFFF"
IDENTIFIERS_STEP = "0001_identifiers_company_unique"

OLD_DDL = """CREATE TABLE memory_operations (
    event_id VARCHAR(64) NOT NULL,
    company_key TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    parent_event_id VARCHAR(64),
    protocol_version INTEGER NOT NULL,
    input_digest TEXT NOT NULL,
    proposal_digest TEXT,
    source_ref TEXT NOT NULL,
    origin TEXT NOT NULL,
    caller_class TEXT NOT NULL,
    target_family TEXT,
    state TEXT NOT NULL,
    allowance INTEGER NOT NULL,
    attempts INTEGER NOT NULL,
    lease TEXT,
    payload JSON,
    approval JSON,
    departure JSON,
    result JSON,
    pending_effects JSON,
    restrictions JSON,
    created_at DATETIME,
    updated_at DATETIME,
    PRIMARY KEY (event_id)
)"""

KEPT = [c.name for c in MemoryOperation.__table__.columns]


@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_DB_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("MEMORY_KEY", COMPANY_A)
    (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
    yield tmp_path / "memory"
    dbm.dispose_engine()


def replayed_event() -> MemoryEvent:
    return MemoryEvent(
        event_id="evt-settled",
        owner_id=OWNER_A,
        company_key=COMPANY_A,
        caller_class=OPERATOR_DELEGATED,
        origin=INTERACTIVE,
        source_kind="chat",
        source_id="turn:1",
        source_revision="rev-1",
        observation="Acme pays in 60 days.",
    )


def _rows() -> list[dict]:
    """Every column populated, in more than one storage shape, plus a terminal row."""
    full = {
        "event_id": "evt-review",
        "company_key": COMPANY_A,
        "owner_id": OWNER_A,
        "parent_event_id": "src-parent",
        "protocol_version": 1,
        "input_digest": "in-review",
        "proposal_digest": "prop-review",
        "source_ref": "email:mail-1@rev-1",
        "origin": "automatic",
        "caller_class": "automatic_observation",
        "target_family": "user",
        "state": "review",
        "allowance": 2,
        "attempts": 1,
        "lease": "123:abcd:ef01",
        "payload": json.dumps(
            {"manifest": [{"event_id": "src:0", "index": 0, "content": "Acme — Milano"}]}
        ),
        "approval": json.dumps({"granted": False, "by": "nobody"}),
        "departure": json.dumps({"flags": ["narrowed"]}),
        "result": json.dumps(
            {"outcome": "review_needed", "reason": "ambiguous", "committed_ids": []}
        ),
        "pending_effects": json.dumps([{"kind": "reindex", "detail": "blob-1"}]),
        "restrictions": json.dumps([{"blob_id": "fact-1", "version": "2026-09-01T10:00:00"}]),
        "created_at": "2026-09-01 10:00:00.123456",
        "updated_at": "2026-09-02 11:00:00.654321",
    }
    sparse = {
        **{name: None for name in full},
        "event_id": "evt-pending",
        "company_key": COMPANY_A,
        "owner_id": "uid-other",
        "protocol_version": 1,
        "input_digest": "in-pending",
        "source_ref": "chat:turn:9@r",
        "origin": "interactive",
        "caller_class": "operator_delegated",
        "state": "pending",
        "allowance": 3,
        "attempts": 0,
    }
    event = replayed_event()
    settled = {
        **full,
        "event_id": event.event_id,
        "parent_event_id": None,
        "input_digest": journal.input_digest(event),
        "source_ref": event.source_ref,
        "origin": event.origin,
        "caller_class": event.caller_class,
        "state": "committed",
        "payload": None,
        "lease": None,
        "result": json.dumps(
            {"outcome": "committed", "reason": None, "committed_ids": [["blob-1", "v1"]]}
        ),
        "pending_effects": json.dumps([]),
    }
    return [full, sparse, settled]


def _old_store(path) -> None:
    """A store as a build with the approval column left it, its first step recorded."""
    engine = create_engine(f"sqlite:///{path}")
    skip = {JOURNAL, "memory_join_fences"}
    tables = [t for t in Base.metadata.sorted_tables if t.name in set(MEMORY_TABLE_NAMES) - skip]
    Base.metadata.create_all(engine, tables=tables)
    with engine.begin() as conn:
        conn.exec_driver_sql(OLD_DDL)
        for index in MemoryOperation.__table__.indexes:
            index.create(conn)
        conn.exec_driver_sql(
            "INSERT INTO memory_meta (id, company_key, self_notion, mutation_seq, "
            "last_sweep_seq, created_by_source) VALUES (1, ?, NULL, 0, 0, 'mint')",
            (COMPANY_A,),
        )
        ensure_schema_version_table(conn)
        record_step(conn, IDENTIFIERS_STEP)
        for row in _rows():
            names = ", ".join(row)
            marks = ", ".join(f":{name}" for name in row)
            conn.exec_driver_sql(f"INSERT INTO memory_operations ({names}) VALUES ({marks})", row)
    engine.dispose()


def _migrate(key=COMPANY_A) -> None:
    engine = open_memory_engine(key, create=True)
    try:
        prepare_store(engine, key, created_by="mint")
    finally:
        engine.dispose()


def _read(path, sql, params=()):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _columns(path) -> list:
    return [row[1] for row in _read(path, f"PRAGMA table_info({JOURNAL})")]


def _table_info(path) -> list:
    return [row[1:] for row in _read(path, f"PRAGMA table_info({JOURNAL})")]


def _indexes(path) -> dict:
    sql = "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=?"
    return dict(_read(path, sql, (JOURNAL,)))


def _kept_bytes(path) -> list:
    """Every kept column of every row, quoted: storage class and bytes both compared."""
    quoted = ", ".join(f"quote({name})" for name in KEPT)
    return _read(path, f"SELECT {quoted} FROM {JOURNAL} ORDER BY event_id")


def _schema(path) -> tuple:
    master = _read(path, "SELECT type, name, rootpage, sql FROM sqlite_master ORDER BY type, name")
    return _read(path, "PRAGMA schema_version")[0][0], master


def _fresh_store(store_dir):
    _migrate(FRESH)
    return memory_db_path(FRESH)


def _step_recorded(key=COMPANY_A) -> bool:
    engine = open_memory_engine(key, create=False)
    try:
        return STEP_ID in applied_step_ids(engine)
    finally:
        engine.dispose()


# ─── The rebuild ──────────────────────────────────────────────────────


def test_an_old_store_loses_approval_and_keeps_every_other_byte(store_dir):
    path = memory_db_path(COMPANY_A)
    _old_store(path)
    before = _kept_bytes(path)
    assert "approval" in _columns(path)
    assert len(before) == 3

    _migrate()

    assert "approval" not in _columns(path)
    assert _kept_bytes(path) == before
    assert _step_recorded()


def test_the_rebuilt_table_has_a_fresh_stores_columns_and_indexes(store_dir):
    path = memory_db_path(COMPANY_A)
    _old_store(path)
    _migrate()
    fresh = _fresh_store(store_dir)

    assert _table_info(path) == _table_info(fresh)
    assert _indexes(path) == _indexes(fresh)
    assert set(_indexes(fresh)) == {
        "sqlite_autoindex_memory_operations_1",
        "ix_memory_operations_company_key",
        "ix_memory_operations_owner_id",
        "ix_memory_operations_parent_event_id",
        "ix_memory_operations_state",
        "ix_memory_operations_company_state",
        "ix_memory_operations_company_source",
    }


def test_a_new_store_never_has_approval(store_dir):
    path = _fresh_store(store_dir)
    assert KEPT == [name for name in _columns(path)]
    assert "approval" not in _columns(path)
    assert _step_recorded(FRESH)


def test_a_store_without_the_journal_is_left_alone(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'bare.db'}")
    try:
        with engine.begin() as conn:
            apply(conn)
        with engine.begin() as conn:
            assert conn.exec_driver_sql("SELECT name FROM sqlite_master").fetchall() == []
    finally:
        engine.dispose()


# ─── Idempotence ──────────────────────────────────────────────────────


def test_a_second_run_changes_nothing(store_dir):
    path = memory_db_path(COMPANY_A)
    _old_store(path)
    _migrate()
    schema, rows = _schema(path), _kept_bytes(path)

    _migrate()

    assert _schema(path) == schema
    assert _kept_bytes(path) == rows


def test_a_partially_reverted_store_is_left_alone(store_dir):
    """The reverse path un-records the step; the forward path re-runs it over a
    table already in shape, and must not rebuild it again."""
    path = memory_db_path(COMPANY_A)
    _old_store(path)
    _migrate()
    schema, rows = _schema(path), _kept_bytes(path)
    engine = open_memory_engine(COMPANY_A, create=False)
    try:
        unrecord_step(engine, STEP_ID)
    finally:
        engine.dispose()
    assert not _step_recorded()

    _migrate()

    assert _schema(path) == schema
    assert _kept_bytes(path) == rows
    assert _step_recorded()


# ─── Backup and restore ───────────────────────────────────────────────


def _backups(store_dir) -> list:
    folder = store_dir / BACKUPS_DIRNAME
    return sorted(folder.iterdir()) if folder.is_dir() else []


def test_the_runner_backs_the_store_up_before_the_rebuild(store_dir):
    path = memory_db_path(COMPANY_A)
    _old_store(path)

    _migrate()

    taken = [p for p in _backups(store_dir) if STEP_ID in p.name]
    assert len(taken) == 1
    assert "approval" in _columns(taken[0])
    assert _kept_bytes(taken[0]) == _kept_bytes(path)


def test_a_restored_backup_opens_migrates_and_replays_a_terminal_row(tmp_path, monkeypatch):
    path = tmp_path / "memory" / f"{COMPANY_A}.db"
    os.makedirs(path.parent, exist_ok=True)
    _old_store(path)
    event = replayed_event()
    try:
        boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
        assert "approval" not in _columns(path)
        assert journal.open_operation(event).replay.committed_ids == (("blob-1", "v1"),)
        migrated = _kept_bytes(path)

        dbm.dispose_engine()
        [backup] = [p for p in _backups(path.parent) if STEP_ID in p.name]
        restore_sqlite(str(backup), str(path))
        assert "approval" in _columns(path)

        reboot()

        assert "approval" not in _columns(path)
        assert _kept_bytes(path) == migrated
        replay = journal.open_operation(event).replay
        assert replay is not None and replay.outcome == "committed"
        assert replay.committed_ids == (("blob-1", "v1"),)
    finally:
        dbm.dispose_engine()
        clear_process_state()
