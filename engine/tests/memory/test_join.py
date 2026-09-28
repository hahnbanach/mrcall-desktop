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

from tests.memory import seeding
from tests.memory.test_split_store import _boot, _fact  # noqa: E402  (shared helpers)


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
    _fact(a, stub_embedder, "pricing", "MOQ", "500 units")
    seeding.store_blob(BlobStorage(get_session, stub_embedder),
        a, entity_namespace(key_a), "#IDENTIFIERS\nName: A-only\n#ABOUT\nx", "x"
    )

    b = _boot(monkeypatch, tmp_path, "b", key=None, source=None)  # its own memory
    key_b = current_company_key()
    assert key_b != key_a
    _fact(b, stub_embedder, "pricing", "MOQ", "300 units")  # same (category, key), other value
    _fact(b, stub_embedder, "pricing", "Lead time", "6 weeks")
    store_b = BlobStorage(get_session, stub_embedder)
    seeding.store_blob(store_b, b, entity_namespace(key_b), "#IDENTIFIERS\nName: B-only\n#ABOUT\ny", "x")
    seeding.store_blob(store_b, b, f"template:{b}", "B signs with the warehouse number", "x")

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
        seeding.store_blob(BlobStorage(get_session, stub_embedder),
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


# ─── AC4: what a join carries, and what it keeps out ──────────────────

HOURS = "Category: hours\nKey: opening\nValue: 9-18 on weekdays"
TERMS = "Category: pricing\nKey: acme-term\nValue: 60 days, the terms Acme negotiated"
MOQ_A = "Category: pricing\nKey: MOQ\nValue: 300 units"
MOQ_B = "Category: pricing\nKey: MOQ\nValue: 500 units"
LUCA = "#IDENTIFIERS\nEntity type: PERSON\nName: Luca Bianchi\n#ABOUT\nPurchasing at Alpha."


def test_a_join_carries_what_the_joiner_sees_its_rules_its_versions_and_every_restriction(
    monkeypatch, tmp_path, embedder
):
    from tests.memory.join_env import isolate, store_digest
    from tests.memory.mnemonic_env import COMPANY_A, COMPANY_B, OWNER_A, OWNER_B, boot, stub_embedder
    from zylch.memory.eligibility import ineligible_fact_ids
    from zylch.memory.hybrid_search import HybridSearchEngine
    from zylch.memory.mnemonic import journal
    from zylch.memory.mnemonic.contracts import INTERACTIVE, OPERATOR_DELEGATED, MemoryEvent
    from zylch.memory.mnemonic.proposals import MnemonicResult
    from zylch.services import facts_store

    colleague = "uid-owner-c"
    isolate(monkeypatch)
    stub_embedder(monkeypatch, embedder)
    boot(monkeypatch, tmp_path, OWNER_B, COMPANY_B)
    seeding.store_blob(BlobStorage(get_session, embedder), OWNER_B, f"facts:{COMPANY_B}", MOQ_B, "seed")
    boot(monkeypatch, tmp_path, colleague, COMPANY_A)
    theirs = seeding.store_blob(
        BlobStorage(get_session, embedder), colleague, f"template:{colleague}", "Colleague rule", "x"
    )
    boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    store = BlobStorage(get_session, embedder)
    luca = seeding.store_blob(store, OWNER_A, f"user:{COMPANY_A}", LUCA, "seed")
    seeding.update_blob(store, luca["id"], OWNER_A, LUCA + "\n#HISTORY\n- quote", "seed",
                        expected_updated_at=luca["updated_at"])
    mine = seeding.store_blob(store, OWNER_A, f"template:{OWNER_A}", "Joiner rule", "x")
    loser = seeding.store_blob(store, OWNER_A, f"facts:{COMPANY_A}", MOQ_A, "seed")
    hours = seeding.store_blob(store, OWNER_A, f"facts:{COMPANY_A}", HOURS, "seed")
    terms = seeding.store_blob(store, OWNER_A, f"facts:{COMPANY_A}", TERMS, "seed")
    review = MemoryEvent(
        event_id="evt-colleague-review", owner_id=colleague, company_key=COMPANY_A,
        caller_class=OPERATOR_DELEGATED, origin=INTERACTIVE, source_kind="chat",
        source_id="turn:1", source_revision="rev-1", observation="Those are Acme's terms only.",
    )
    journal.open_operation(review)
    journal.record_result(
        review.event_id, MnemonicResult.review_needed(review.event_id, "customer-specific"),
        state=journal.REVIEW, restrictions=[{"blob_id": terms["id"], "version": terms["updated_at"]}],
    )
    source = store_digest(COMPANY_A)

    assert join(COMPANY_B)["ok"] is True

    assert _rows(COMPANY_B, f"SELECT id FROM blobs WHERE namespace = 'template:{OWNER_A}'") == [(mine["id"],)]
    assert _rows(COMPANY_B, f"SELECT COUNT(*) FROM blobs WHERE id = '{theirs['id']}'") == [(0,)]
    assert _rows(COMPANY_B, f"SELECT namespace FROM blobs WHERE id = '{luca['id']}'") == [(f"user:{COMPANY_B}",)]
    assert _rows(COMPANY_B, f"SELECT namespace FROM blob_versions WHERE blob_id = '{luca['id']}'") == [
        (f"user:{COMPANY_B}",)
    ]
    assert _rows(COMPANY_B, "SELECT losing_blob_id, losing_owner_id FROM fact_history") == [(loser["id"], OWNER_A)]
    assert _rows(COMPANY_B, f"SELECT COUNT(*) FROM blobs WHERE id = '{terms['id']}'") == [(1,)]
    assert store_digest(COMPANY_A) == source
    assert _rows(COMPANY_A, "SELECT state, restrictions FROM memory_operations WHERE event_id = 'evt-colleague-review'") == [
        ("review", f'[{{"blob_id": "{terms["id"]}", "version": "{terms["updated_at"]}"}}]')
    ]

    boot(monkeypatch, tmp_path, OWNER_B, COMPANY_B)
    assert BlobStorage(get_session, embedder).get_blob(luca["id"], OWNER_B)["content"].startswith(LUCA)
    fact_ids = {row["blob_id"] for row in facts_store._all_fact_blobs(OWNER_B)}
    assert hours["id"] in fact_ids and terms["id"] not in fact_ids
    assert facts_store.exact_fact(OWNER_B, "pricing", "acme-term") is None
    with get_session() as session:
        assert terms["id"] in ineligible_fact_ids(session, COMPANY_B)
    found = [r.blob_id for r in HybridSearchEngine(get_session, embedder).search(OWNER_B, "Acme negotiated terms 60 days")]
    assert terms["id"] not in found
