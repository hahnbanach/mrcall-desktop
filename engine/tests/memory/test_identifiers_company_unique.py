"""Memory-store step 0001_identifiers_company_unique: the identifier index is
unique per company, and an existing store's per-owner duplicates fold."""

from __future__ import annotations

import sqlite3

import pytest

from zylch.memory.company_key import current_company_key, entity_namespace
from zylch.memory.store import memory_db_path
from zylch.storage.database import get_session
from zylch.storage.migrations import applied_step_ids
from zylch.storage.step_identifiers_company_unique import STEP_ID

from tests.memory.test_split_store import _boot  # noqa: E402


@pytest.fixture
def stub_embedder(monkeypatch, embedder):
    import zylch.memory as memory_pkg
    import zylch.memory.embeddings as emb_mod

    monkeypatch.setattr(memory_pkg, "EmbeddingEngine", lambda *a, **k: embedder)
    monkeypatch.setattr(emb_mod, "EmbeddingEngine", lambda *a, **k: embedder)
    return embedder


def test_fresh_store_is_company_unique_and_two_owners_share_one_row(
    monkeypatch, tmp_path, stub_embedder
):
    from zylch.memory.blob_storage import BlobStorage
    from zylch.storage.storage import Storage

    a = _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    key = current_company_key()
    bid = BlobStorage(get_session, stub_embedder).store_blob(
        a, entity_namespace(key), "#IDENTIFIERS\nName: G\n#ABOUT\nx", "x"
    )["id"]
    st = Storage.get_instance()
    assert st.add_person_identifiers(a, bid, [("email", "g@c.test")]) == 1
    b = _boot(monkeypatch, tmp_path, "b", key=key, source="join")
    Storage._instance = None
    assert (
        Storage.get_instance().add_person_identifiers(b, bid, [("email", "g@c.test")]) == 0
    )  # already indexed by A
    c = sqlite3.connect(memory_db_path(key))
    try:
        assert c.execute("SELECT COUNT(*) FROM person_identifiers").fetchone()[0] == 1
        ddl = c.execute("SELECT sql FROM sqlite_master WHERE name='person_identifiers'").fetchone()[
            0
        ]
        assert "person_identifiers_company_kind_value_blob_unique" in ddl
    finally:
        c.close()


def test_legacy_store_is_rebuilt_and_duplicates_fold(monkeypatch, tmp_path, stub_embedder):
    """A store created before the step: per-owner constraint, two rows for one
    identifier on one blob. Booting rebuilds it to one row."""
    a = _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    key = current_company_key()
    from zylch.storage import database as dbm

    dbm.dispose_engine()
    c = sqlite3.connect(memory_db_path(key))
    c.executescript(f"""
        DELETE FROM schema_version WHERE id = '{STEP_ID}';
        DROP TABLE person_identifiers;
        CREATE TABLE person_identifiers (id VARCHAR(36) NOT NULL PRIMARY KEY, owner_id TEXT NOT NULL,
            company_key TEXT, blob_id VARCHAR(36) NOT NULL REFERENCES blobs(id) ON DELETE CASCADE,
            kind TEXT NOT NULL, value TEXT NOT NULL, created_at DATETIME,
            CONSTRAINT person_identifiers_owner_kind_value_blob_unique UNIQUE (owner_id, kind, value, blob_id));
        INSERT INTO blobs (id, owner_id, namespace, content, company_key) VALUES ('b1', '{a}', 'user:{key}', 'x', '{key}');
        INSERT INTO person_identifiers VALUES ('i1', '{a}', '{key}', 'b1', 'email', 'g@c.test', '2026-09-01 00:00:00');
        INSERT INTO person_identifiers VALUES ('i2', 'b@company.test', '{key}', 'b1', 'email', 'g@c.test', '2026-09-02 00:00:00');
        INSERT INTO person_identifiers VALUES ('i3', 'b@company.test', '{key}', 'b1', 'phone', '+39333', '2026-09-02 00:00:00');
        """)
    c.commit()
    c.close()

    dbm.init_db()  # the store's runner re-applies the pending step
    c = sqlite3.connect(memory_db_path(key))
    try:
        rows = c.execute("SELECT id, kind, value FROM person_identifiers ORDER BY id").fetchall()
        assert rows == [("i1", "email", "g@c.test"), ("i3", "phone", "+39333")]  # i2 folded into i1
        ddl = c.execute("SELECT sql FROM sqlite_master WHERE name='person_identifiers'").fetchone()[
            0
        ]
        assert "person_identifiers_company_kind_value_blob_unique" in ddl
    finally:
        c.close()
    assert STEP_ID in applied_step_ids(dbm.current_memory_engine())
