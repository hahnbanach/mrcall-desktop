"""M1 migration step ``0001_company_key`` (brief C2, C20; plan M1.2/M1.6).

Starts from what the five live daemons actually look like: a profile with
``MEMORY_KEY`` unset and rows in the pre-M1 shape — ``user:<owner>`` /
``facts:<owner>`` namespaces, no ``company_key``. Then boots.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from zylch.memory.company_key import entity_namespace, facts_namespace, rule_namespaces
from zylch.memory.store import memory_db_path
from zylch.storage import database as dbm
from zylch.storage.migrations import pending_step_ids
from zylch.storage.step_company_key import STEP, STEP_ID, reverse
from zylch.storage.step_memory_split import STEP as SPLIT_STEP, reverse_into_profile

OWNER = "legacy@company.test"


def _legacy_db(path: str) -> None:
    """A pre-M1 zylch.db: the six memory tables WITHOUT company_key."""
    c = sqlite3.connect(path)
    c.executescript(f"""
        CREATE TABLE blobs (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, namespace TEXT NOT NULL,
            content TEXT NOT NULL, embedding BLOB, events JSON, created_at DATETIME, updated_at DATETIME);
        CREATE TABLE blob_sentences (id TEXT PRIMARY KEY, blob_id TEXT NOT NULL REFERENCES blobs(id) ON DELETE CASCADE,
            owner_id TEXT NOT NULL, sentence_text TEXT NOT NULL, embedding BLOB NOT NULL, created_at DATETIME);
        CREATE TABLE person_identifiers (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, blob_id TEXT NOT NULL REFERENCES blobs(id) ON DELETE CASCADE,
            kind TEXT NOT NULL, value TEXT NOT NULL, created_at DATETIME);
        INSERT INTO blobs VALUES ('e1','{OWNER}','user:{OWNER}','#IDENTIFIERS\nName: Giulia\n#ABOUT\npallets', X'00', '[]', NULL, NULL);
        INSERT INTO blobs VALUES ('f1','{OWNER}','facts:{OWNER}','Category: pricing\nKey: MOQ\n500 units', X'00', '[]', NULL, NULL);
        INSERT INTO blobs VALUES ('r1','{OWNER}','template:{OWNER}','Never promise a callback time', X'00', '[]', NULL, NULL);
        INSERT INTO blobs VALUES ('p1','{OWNER}','prefs:{OWNER}','Sign with the warehouse number', X'00', '[]', NULL, NULL);
        INSERT INTO blob_sentences VALUES ('s1','e1','{OWNER}','pallets', X'00', NULL);
        INSERT INTO person_identifiers VALUES ('i1','{OWNER}','e1','email','giulia@cliente.test', NULL);
        """)
    c.commit()
    c.close()


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    db_path = str(tmp_path / "zylch.db")
    _legacy_db(db_path)
    monkeypatch.setenv("ZYLCH_DB_PATH", db_path)
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    monkeypatch.delenv("MEMORY_KEY", raising=False)  # the live daemons' state
    dbm.dispose_engine()
    yield db_path
    dbm.dispose_engine()


def _rows(db_path, sql):
    c = sqlite3.connect(db_path)
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


def _store(_legacy_path):
    """After the split (M2) the memory rows live in the company store."""
    return memory_db_path(os.environ["MEMORY_KEY"])


def test_boot_mints_the_key_then_stamps_and_rewrites_every_row(legacy):
    dbm.init_db()
    key = os.environ.get("MEMORY_KEY")
    assert key, "the step must mint before it rewrites — nothing else runs first"

    store = _store(legacy)
    ns = dict(_rows(store, "SELECT id, namespace FROM blobs"))
    assert ns["e1"] == entity_namespace(key)  # C2: company family re-keyed
    assert ns["f1"] == facts_namespace(key)
    assert (ns["r1"], ns["p1"]) == rule_namespaces(OWNER)  # rules keep the owner
    keys = _rows(store, "SELECT DISTINCT company_key FROM blobs")
    assert keys == [(key,)]  # C20: rule rows stamped too, not only company rows
    assert _rows(store, "SELECT company_key FROM blob_sentences") == [(key,)]
    assert _rows(store, "SELECT company_key FROM person_identifiers") == [(key,)]
    assert _rows(store, "SELECT owner_id FROM blobs WHERE id='e1'") == [(OWNER,)]  # C7 provenance
    assert pending_step_ids(dbm.get_engine(), [STEP, SPLIT_STEP]) == []
    # both steps are destructive: one backup of the profile file covers both
    backups = os.listdir(os.path.join(os.path.dirname(legacy), "backups"))
    assert len(backups) == 1 and STEP_ID in backups[0] and SPLIT_STEP.id in backups[0]


def test_migrated_rows_are_retrievable_through_the_key(legacy, monkeypatch):
    dbm.init_db()
    from zylch.services import facts_store
    from zylch.services.prefs_store import load_rules

    assert [f["content"] for f in facts_store.get_facts_by_category(OWNER, "pricing")] == [
        "Category: pricing\nKey: MOQ\n500 units"
    ]
    # C20: existing rules survive and stay readable by their owner
    assert sorted(r["content"] for r in load_rules(OWNER)) == [
        "Never promise a callback time",
        "Sign with the warehouse number",
    ]


def test_forward_reverse_forward_converges(legacy):
    """Both steps forward, both reversed (split first, then the key), a row
    written in the old shape during the rollback window, both forward
    again: everything converges and nothing is lost."""
    dbm.init_db()
    key = os.environ["MEMORY_KEY"]
    engine = dbm.get_engine()

    reverse_into_profile(engine, dbm.current_memory_engine(), OWNER)  # 0002 back
    reverse(engine)  # 0001 back — the blobs are in the profile file again
    ns = dict(_rows(legacy, "SELECT id, namespace FROM blobs"))
    assert ns["e1"] == f"user:{OWNER}" and ns["f1"] == f"facts:{OWNER}"  # exact, via owner_id
    assert pending_step_ids(engine, [STEP, SPLIT_STEP]) == [STEP_ID, SPLIT_STEP.id]

    # a row written during the rollback window, in the old shape
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f"INSERT INTO blobs (id, owner_id, namespace, content) VALUES ('e2','{OWNER}','user:{OWNER}','x')"
        )

    dbm.dispose_engine()
    dbm.init_db()  # forward again: re-stamp, re-key, re-split
    engine = dbm.get_engine()
    store = _store(legacy)
    ns = dict(_rows(store, "SELECT id, namespace FROM blobs"))
    assert ns["e1"] == ns["e2"] == entity_namespace(key)
    assert _rows(store, "SELECT company_key FROM blobs WHERE id='e2'") == [(key,)]
    assert _rows(store, "SELECT COUNT(*) FROM blobs") == [(5,)]  # 4 + e2, no duplicates
    assert pending_step_ids(engine, [STEP, SPLIT_STEP]) == []


def test_second_boot_is_a_no_op(legacy):
    dbm.init_db()
    store = _store(legacy)
    before = _rows(store, "SELECT id, namespace, company_key FROM blobs ORDER BY id")
    dbm.dispose_engine()
    dbm.init_db()
    assert _rows(store, "SELECT id, namespace, company_key FROM blobs ORDER BY id") == before
    assert len(os.listdir(os.path.join(os.path.dirname(legacy), "backups"))) == 1
