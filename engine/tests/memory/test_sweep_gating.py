"""The reconsolidation sweep runs after an update only when the store changed."""

from __future__ import annotations

import asyncio

import pytest

from zylch.memory.company_key import current_company_key, entity_namespace
from zylch.memory.store import get_meta
from zylch.storage import database as dbm
from zylch.storage.database import get_session

from tests.memory.test_split_store import _boot  # noqa: E402


@pytest.fixture
def stub_embedder(monkeypatch, embedder):
    import zylch.memory as memory_pkg
    import zylch.memory.embeddings as emb_mod

    monkeypatch.setattr(memory_pkg, "EmbeddingEngine", lambda *a, **k: embedder)
    monkeypatch.setattr(emb_mod, "EmbeddingEngine", lambda *a, **k: embedder)
    return embedder


def test_sweep_runs_once_per_change_and_rests_otherwise(monkeypatch, tmp_path, stub_embedder):
    import zylch.memory.llm_merge as lm
    from zylch.memory.blob_storage import BlobStorage

    monkeypatch.setattr(
        lm, "try_make_llm_client", lambda *a, **k: None
    )  # no LLM: the sweep body exits early
    a = _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    key = current_company_key()
    engine = dbm.current_memory_engine()

    # a fresh store: nothing changed since "the last sweep" (both 0)
    first = asyncio.run(lm.reconsolidate_now(a))
    assert first["skipped"] is True and "nothing changed" in first["reason"]

    BlobStorage(get_session, stub_embedder).store_blob(
        a, entity_namespace(key), "#IDENTIFIERS\nName: G\n#ABOUT\nx", "x"
    )
    meta = get_meta(engine)
    assert meta["mutation_seq"] > meta["last_sweep_seq"]

    second = asyncio.run(lm.reconsolidate_now(a))
    assert not second.get("skipped") and second["no_llm"] is True  # it ran (and found no LLM)
    meta = get_meta(engine)
    assert meta["last_sweep_seq"] == meta["mutation_seq"]

    third = asyncio.run(lm.reconsolidate_now(a))
    assert third["skipped"] is True  # nothing changed since

    forced = asyncio.run(lm.reconsolidate_now(a, force=True))
    assert not forced.get("skipped")  # the button and the CLI always sweep


def test_a_new_identifier_alone_makes_the_sweep_due(monkeypatch, tmp_path, stub_embedder):
    """Identifiers are the clustering signal: an entity that gains an email
    can now match another blob, so the sweep must run even if no blob
    content changed."""
    import zylch.memory.llm_merge as lm
    from zylch.memory.blob_storage import BlobStorage
    from zylch.storage.storage import Storage

    monkeypatch.setattr(lm, "try_make_llm_client", lambda *a, **k: None)
    a = _boot(monkeypatch, tmp_path, "a", key=None, source=None)
    key = current_company_key()
    engine = dbm.current_memory_engine()
    bid = BlobStorage(get_session, stub_embedder).store_blob(
        a, entity_namespace(key), "#IDENTIFIERS\nName: G\n#ABOUT\nx", "x"
    )["id"]
    assert not asyncio.run(lm.reconsolidate_now(a)).get("skipped")  # the new blob
    assert asyncio.run(lm.reconsolidate_now(a))["skipped"] is True  # rests

    Storage._instance = None
    assert Storage.get_instance().add_person_identifiers(a, bid, [("email", "g@c.test")]) == 1
    meta = get_meta(engine)
    assert meta["mutation_seq"] > meta["last_sweep_seq"]
    assert not asyncio.run(lm.reconsolidate_now(a)).get("skipped")  # due again
    # the same identifier again is a no-op: no bump, no sweep
    assert Storage.get_instance().add_person_identifiers(a, bid, [("email", "g@c.test")]) == 0
    assert asyncio.run(lm.reconsolidate_now(a))["skipped"] is True
