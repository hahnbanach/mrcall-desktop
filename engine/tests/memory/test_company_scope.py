"""M1 — company families are the key's, rule families are key AND owner.

Two accounts, A and B, share one store (one key). Criteria proven here:

- C3   an entity written by A and updated by B is actually updated
- C7   every row carries the contributing account as provenance
- C11  A's rules are neither readable, listable, editable nor deletable
       from B — on every family-blind path, not only the namespaced stores
- C11b ``/memory reset`` from B destroys nothing of A's and nothing of the
       company's, proven by running it
- C15  a model-supplied namespace cannot write outside the company
- C19  B retrieves A's entity through ``search()``'s VECTOR half — a query
       sharing no token with the entity's identifiers, which FTS cannot serve
- one engine instance serving two scopes returns each scope's own rows
"""

from __future__ import annotations

import pytest

from zylch.memory.blob_storage import BlobStorage
from zylch.memory.company_key import (
    current_company_key,
    entity_namespace,
    rule_namespaces,
    well_formed,
)
from zylch.memory.hybrid_search import HybridSearchEngine
from zylch.storage.database import get_session
from zylch.storage.models import Blob

A = "alice@company.test"
B = "bob@company.test"

PERSON = (
    "#IDENTIFIERS\nName: Giulia Verdi\nEmail: giulia@cliente.test\n"
    "#ABOUT\nRuns procurement for the Milan warehouse and negotiates pallet pricing.\n"
    "#HISTORY\n- agreed a payment plan in March"
)


@pytest.fixture
def store(company_db, embedder):
    return BlobStorage(get_session, embedder)


@pytest.fixture
def search(company_db, embedder):
    return HybridSearchEngine(get_session, embedder)


def _rule(store, owner, text):
    return store.store_blob(owner, rule_namespaces(owner)[0], text, "taught")["id"]


def _entity(store, owner, text=PERSON):
    return store.store_blob(owner, entity_namespace(current_company_key()), text, "extracted")["id"]


# ─── the key itself ───────────────────────────────────────────


def test_boot_minted_a_well_formed_key_and_persisted_it(company_db):
    key = current_company_key()
    assert key and well_formed(key) == (True, "")
    import os

    assert os.environ["MEMORY_KEY"] == key
    assert "MEMORY_KEY=" in open(os.path.join(os.environ["ZYLCH_PROFILE_DIR"], ".env")).read()


# ─── C7 provenance, C3 cross-owner write ──────────────────────


def test_rows_carry_provenance_and_the_company_key(store):
    bid = _entity(store, A)
    with get_session() as s:
        row = s.query(Blob).filter(Blob.id == bid).one()
        assert row.owner_id == A
        assert row.company_key == current_company_key()
        assert row.namespace == entity_namespace(current_company_key())


def test_entity_written_by_a_is_actually_updated_by_b(store):
    bid = _entity(store, A)
    out = store.update_blob(bid, B, PERSON + "\n- moved to net-60 terms in June", "merged")
    assert out, "cross-owner update returned an empty dict: the lost-update bug"
    assert "net-60" in store.get_blob(bid, A)["content"]
    # provenance stays with the account that CREATED the row
    with get_session() as s:
        assert s.query(Blob).filter(Blob.id == bid).one().owner_id == A


# ─── C11 on every family-blind path ──────────────────────────


def test_rules_are_invisible_to_the_other_account_on_every_path(store, search):
    a_rule = _rule(store, A, "Never promise a callback time; offer a written follow-up.")
    b_rule = _rule(store, B, "Sign every mail with the warehouse phone number.")
    shared = _entity(store, A)

    # read
    assert store.get_blob(a_rule, B) is None
    assert store.get_blob(a_rule, A) is not None
    # list
    assert {b["id"] for b in store.list_blobs(B, limit=50)} == {b_rule, shared}
    # stats / namespaces
    assert set(store.get_stats(B)["namespaces"]) == {
        rule_namespaces(B)[0],
        entity_namespace(current_company_key()),
    }
    # edit
    assert store.update_blob(a_rule, B, "poisoned", "x") == {}
    assert "Never promise" in store.get_blob(a_rule, A)["content"]
    # delete
    assert store.delete_blob(a_rule, B) is False
    assert store.get_blob(a_rule, A) is not None
    # search with NO namespace — the contact-tool / solve-tool shape
    hits = {
        r.blob_id for r in search.search(owner_id=B, query="callback follow-up written", limit=20)
    }
    assert a_rule not in hits
    hits_a = {
        r.blob_id for r in search.search(owner_id=A, query="callback follow-up written", limit=20)
    }
    assert a_rule in hits_a


# ─── C11b: /memory reset, run for real ───────────────────────


def test_memory_reset_by_b_leaves_a_and_the_company_intact(store):
    a_rule = _rule(store, A, "A's rule")
    b_rule = _rule(store, B, "B's rule")
    a_entity = _entity(store, A)
    b_entity = _entity(store, B, PERSON.replace("Giulia Verdi", "Marco Neri"))

    removed = store.delete_all_blobs(B)

    assert removed == 1  # B's rule only
    assert store.get_blob(b_rule, B) is None
    assert store.get_blob(a_rule, A) is not None
    assert store.get_blob(a_entity, A) is not None
    # B's contribution to company knowledge survives, provenance included
    with get_session() as s:
        row = s.query(Blob).filter(Blob.id == b_entity).one()
        assert row.owner_id == B


def test_memory_reset_on_a_single_owner_store_still_wipes_everything(store):
    _rule(store, A, "only me")
    _entity(store, A)
    assert store.delete_all_blobs(A) == 2
    assert store.list_blobs(A) == []


# ─── C15: the model names a family, never a namespace ────────


@pytest.mark.asyncio
async def test_model_supplied_namespace_is_rescoped_never_stored(company_db, embedder, monkeypatch):
    from zylch.tools.create_memory_tool import CreateMemoryTool
    from zylch.tools.base import ToolStatus

    tool = CreateMemoryTool.__new__(CreateMemoryTool)
    tool._get_owner_id = lambda: A
    key = current_company_key()

    r = await tool.execute(
        content="#IDENTIFIERS\nName: X\n#ABOUT\ny", namespace="user:someone-else"
    )
    assert r.status == ToolStatus.SUCCESS and r.data["namespace"] == f"user:{key}"
    r = await tool.execute(content="be terse", namespace="template:someone-else")
    assert r.status == ToolStatus.SUCCESS and r.data["namespace"] == f"template:{A}"
    r = await tool.execute(content="x", namespace="attic:whatever")
    assert r.status == ToolStatus.ERROR and "unknown memory namespace family" in (r.error or "")


# ─── C19: the vector half, specifically ──────────────────────


def test_b_retrieves_a_entity_through_the_vector_half(store, search):
    bid = _entity(store, A)
    # No token of this query appears in the #IDENTIFIERS section
    # ("Giulia Verdi", "giulia@cliente.test"), so FTS scores nothing and
    # only cosine over #ABOUT can return the row.
    hits = search.search(owner_id=B, query="pallet pricing procurement warehouse", limit=5)
    assert [h.blob_id for h in hits] == [bid]
    assert hits[0].fts_score == 0.0 and hits[0].semantic_score > 0.0


def test_one_engine_instance_serves_two_scopes_correctly(store, search):
    a_rule = _rule(store, A, "alpha rule about pallets")
    b_rule = _rule(store, B, "bravo rule about pallets")
    ids_a = {r.blob_id for r in search.search(owner_id=A, query="rule about pallets", limit=10)}
    ids_b = {r.blob_id for r in search.search(owner_id=B, query="rule about pallets", limit=10)}
    assert a_rule in ids_a and b_rule not in ids_a
    assert b_rule in ids_b and a_rule not in ids_b


# ─── key shape ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad,why",
    [
        ("", "empty"),
        ("short", "22 characters"),
        ("x" * 21 + "!", "not URL-safe"),
        ("!" * 22, "not URL-safe"),
        ("x" * 21 + "+", "not URL-safe"),
        ("x" * 21 + "/", "not URL-safe"),
    ],
)
def test_well_formed_rejects(bad, why):
    ok, reason = well_formed(bad)
    assert not ok and why.split()[0] in reason
