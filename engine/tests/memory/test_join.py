"""M2 — joining a company memory (brief C5, C12, C13 engine half).

Two profiles, each with a memory of its own; B joins A's key.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from zylch.memory.blob_storage import BlobStorage
from zylch.memory.company_key import current_company_key, entity_namespace, mint_key
from zylch.memory.join import join, preview
from zylch.memory.store import memory_db_path, set_self_notion
from zylch.storage import database as dbm
from zylch.storage.database import get_session

from tests.memory.test_split_store import _boot  # noqa: E402  (shared boot helper)


@pytest.fixture
def stub_embedder(monkeypatch, embedder):
    import zylch.memory as memory_pkg
    import zylch.memory.embeddings as emb_mod

    monkeypatch.setattr(memory_pkg, "EmbeddingEngine", lambda *a, **k: embedder)
    monkeypatch.setattr(emb_mod, "EmbeddingEngine", lambda *a, **k: embedder)
    return embedder


def _rows(key, sql):
    c = sqlite3.connect(memory_db_path(key))
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


def test_join_converges_facts_keeps_history_and_unites_the_rest(
    monkeypatch, tmp_path, stub_embedder
):
    from zylch.services import facts_store

    a = _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    key_a = current_company_key()
    facts_store.upsert_fact(a, "pricing", "MOQ", "500 units")
    BlobStorage(get_session, stub_embedder).store_blob(
        a, entity_namespace(key_a), "#IDENTIFIERS\nName: A-only\n#ABOUT\nx", "x"
    )

    b = _boot(monkeypatch, tmp_path, "b", key=None, source=None)  # its own memory
    key_b = current_company_key()
    assert key_b != key_a
    facts_store.upsert_fact(b, "pricing", "MOQ", "300 units")  # same (category, key), other value
    facts_store.upsert_fact(b, "pricing", "Lead time", "6 weeks")
    store_b = BlobStorage(get_session, stub_embedder)
    store_b.store_blob(b, entity_namespace(key_b), "#IDENTIFIERS\nName: B-only\n#ABOUT\ny", "x")
    store_b.store_blob(b, f"template:{b}", "B signs with the warehouse number", "x")

    out = join(key_a)
    assert out["ok"] and not out.get("already"), out
    assert current_company_key() == key_a
    assert os.environ["MEMORY_KEY_SOURCE"] == "join"
    assert "MEMORY_KEY=" + key_a in (tmp_path / "b" / ".env").read_text()
    assert dbm.memory_unavailable_reason() is None

    # one row per fact key; the joined store's value won; the loser is history with B's provenance
    facts = facts_store.get_facts_by_category(b, "pricing")
    assert sorted(f["key"] for f in facts) == ["Lead time", "MOQ"]
    assert [f["content"] for f in facts if f["key"] == "MOQ"] == [
        "Category: pricing\nKey: MOQ\n500 units"
    ]
    hist = _rows(
        key_a, "SELECT category, fact_key, losing_value, losing_owner_id, reason FROM fact_history"
    )
    assert hist == [("pricing", "moq", "300 units", b, "join")]
    # entities from both memories, rules with their owner, everything under key A
    names = {
        r[0].split("\n")[1]
        for r in _rows(key_a, "SELECT content FROM blobs WHERE namespace LIKE 'user:%'")
    }
    assert names == {"Name: A-only", "Name: B-only"}
    assert _rows(key_a, f"SELECT owner_id FROM blobs WHERE namespace = 'template:{b}'") == [(b,)]
    assert _rows(key_a, "SELECT DISTINCT company_key FROM blobs") == [(key_a,)]
    # the old store is left on disk, untouched
    assert os.path.isfile(memory_db_path(key_b))
    assert _rows(key_b, "SELECT COUNT(*) FROM blobs")[0][0] == 4
    # the running engine is on the joined store: B now reads A's entity
    assert BlobStorage(get_session, stub_embedder).list_blobs(b, limit=50)


def test_join_unknown_key_is_refused_and_creates_nothing(monkeypatch, tmp_path, stub_embedder):
    _boot(monkeypatch, tmp_path, "b", key=None, source=None)
    mine = current_company_key()
    ghost = mint_key()
    out = join(ghost)
    assert out == {"ok": False, "reason": "no company memory exists for this key on this host"}
    assert not os.path.exists(memory_db_path(ghost))
    assert current_company_key() == mine
    assert join("not a key")["ok"] is False


def test_preview_echoes_self_notion_and_size_without_creating(monkeypatch, tmp_path, stub_embedder):
    a = _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    key_a = current_company_key()
    set_self_notion(dbm.current_memory_engine(), "Café 124")
    for i in range(3):
        BlobStorage(get_session, stub_embedder).store_blob(
            a, entity_namespace(key_a), f"#IDENTIFIERS\nName: N{i}\n#ABOUT\nz", "x"
        )

    _boot(monkeypatch, tmp_path, "b", key=None, source=None)
    echo = preview(key_a)
    assert echo["exists"] and echo["self_notion"] == "Café 124" and echo["blob_count"] == 3
    assert echo["contributors"] == [a]
    ghost = mint_key()
    assert preview(ghost)["exists"] is False and not os.path.exists(memory_db_path(ghost))


def test_join_same_key_is_a_noop(monkeypatch, tmp_path):
    _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    assert join(current_company_key()) == {"ok": True, "already": True, "merged": {}}


@pytest.mark.asyncio
async def test_settings_update_refuses_the_memory_key(monkeypatch, tmp_path):
    _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    from zylch.rpc.methods import settings_update

    with pytest.raises(ValueError) as e:
        await settings_update({"updates": {"MEMORY_KEY": mint_key()}}, lambda *a: None)
    assert getattr(e.value, "code", None) == -32602 and "memory.join" in str(e.value)
