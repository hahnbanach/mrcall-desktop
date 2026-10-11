"""Durable company provenance excludes bank-derived rows from real joins."""

import shutil

import pytest

from zylch.memory.blob_storage import BlobStorage
from zylch.memory.company_key import current_company_key
from zylch.memory.mnemonic import journal
from zylch.qonto.provenance import excluded_blob_ids
from zylch.services import facts_store, solve_tools
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import BlobAlias, BlobVersion, FactHistory

from tests.memory import seeding
from tests.memory.join_env import destination, blob_ids, rows, isolate
from tests.memory.mnemonic_env import BagOfWordsEmbedder, COMPANY_B, boot
from .conftest import UID, signin
from .test_publication import publishing as publishing_fixture, issue, confirm, records, decision

from .test_reads import bank as bank_fixture

bank = bank_fixture
publishing = publishing_fixture


def publish_fact(env, wire):
    preview = issue(env)
    wire.answer(decision(preview["fact_text"]))
    assert confirm(env, preview)["result"]["status"] == "committed"
    return records()[0][0]


def storage():
    return BlobStorage(get_session, BagOfWordsEmbedder())


def colleague(env, monkeypatch, key):
    from zylch.cli import profiles

    original = env.directory
    dbm.dispose_engine()
    boot(monkeypatch, env.home, "colleagueUid", key, profile="profiles/colleagueUid")
    monkeypatch.setattr(profiles, "_active_profile", "colleagueUid")
    monkeypatch.setattr(
        profiles, "_active_profile_dir", str(env.home / "profiles" / "colleagueUid")
    )
    signin("colleagueUid")
    shutil.rmtree(original)


@pytest.mark.parametrize("who", ["publisher", "colleague_original_profile_gone"])
def test_actual_join_excludes_published_fact_and_dependents(publishing, monkeypatch, who):
    env, api, wire = publishing
    isolate(monkeypatch)
    key = current_company_key()
    fact = publish_fact(env, wire)
    ordinary = seeding.store_blob(storage(), UID, "user:" + key, "Name: Ordinary company knowledge")
    if who == "colleague_original_profile_gone":
        colleague(env, monkeypatch, key)
    destination()
    from zylch.memory.join import join

    result = join(COMPANY_B)
    assert result["ok"] and result["merged"]["qonto_excluded"] == 1, result
    assert blob_ids(COMPANY_B) == {ordinary["id"]}
    for table in (
        "blob_sentences",
        "blob_versions",
        "email_blobs",
        "calendar_blobs",
        "whatsapp_blobs",
        "person_identifiers",
    ):
        assert not rows(COMPANY_B, "SELECT 1 FROM " + table + " WHERE blob_id=?", (fact["id"],))
    assert not rows(
        COMPANY_B,
        "SELECT 1 FROM blob_aliases WHERE keeper_id=? OR merged_id=?",
        (fact["id"], fact["id"]),
    )
    assert not rows(COMPANY_B, "SELECT 1 FROM memory_operations WHERE source_ref LIKE 'qonto:%'")


def test_alias_version_and_merged_keeper_closure_survives_ordinary_edit_and_profile_removal(
    publishing, monkeypatch
):
    env, api, wire = publishing
    isolate(monkeypatch)
    key = current_company_key()
    fact = publish_fact(env, wire)
    seeding.update_blob(
        storage(), fact["id"], UID, "Category: finance\nKey: qonto\nValue: Later ordinary edit."
    )
    keeper = seeding.store_blob(
        storage(),
        UID,
        "facts:" + key,
        "Category: other\nKey: keeper\nValue: Merged keeper with bank donor.",
    )
    final = seeding.store_blob(
        storage(), UID, "facts:" + key, "Category: other\nKey: final\nValue: Second merged keeper."
    )
    source_alias = seeding.store_blob(storage(), UID, "user:" + key, "Name: Source alias")
    with journal.company_transaction(write=True) as session:
        session.add_all(
            [
                BlobAlias(merged_id=fact["id"], keeper_id=keeper["id"], company_key=key),
                BlobAlias(merged_id=keeper["id"], keeper_id=final["id"], company_key=key),
                BlobAlias(merged_id=source_alias["id"], keeper_id=final["id"], company_key=key),
                BlobVersion(
                    blob_id=keeper["id"],
                    company_key=key,
                    owner_id=UID,
                    namespace="facts:" + key,
                    content="Retained merged bank donor.",
                    reason="consolidate",
                ),
            ]
        )
    with journal.company_transaction(write=True) as session:
        assert storage().delete_blob(fact["id"], UID, retain=True, session=session)
    colleague(env, monkeypatch, key)
    with journal.company_transaction() as session:
        assert {fact["id"], keeper["id"], final["id"], source_alias["id"]} <= excluded_blob_ids(
            session, key
        )
    destination()
    from zylch.memory.join import join

    result = join(COMPANY_B)
    assert result["ok"] and result["merged"]["qonto_excluded"] == 3, result
    assert blob_ids(COMPANY_B) == set()
    assert rows(COMPANY_B, "SELECT count(*) FROM blob_versions") == [(0,)]
    assert rows(COMPANY_B, "SELECT count(*) FROM blob_aliases") == [(0,)]


@pytest.mark.parametrize("removed", ["disconnect_delete", "original_profile_gone"])
def test_historical_source_unavailable_annotation_is_company_only(publishing, monkeypatch, removed):
    env, api, wire = publishing
    key = current_company_key()
    fact = publish_fact(env, wire)
    ordinary = seeding.store_blob(
        storage(), UID, "facts:" + key, "Category: hours\nKey: opening\nValue: Nine."
    )
    if removed == "disconnect_delete":
        assert "result" in env.rpc("qonto.disconnect")
        assert "result" in env.rpc("qonto.delete_imported_data", confirmed=True)
        owner = UID
    else:
        colleague(env, monkeypatch, key)
        owner = "colleagueUid"
    import zylch.qonto.repository as repository

    monkeypatch.setattr(
        repository,
        "profile_transaction",
        lambda: (_ for _ in ()).throw(
            AssertionError("Shared provenance must never open another profile.")
        ),
    )
    bank = storage().get_blob(fact["id"], owner)
    assert bank["historical_finance_snapshot"] is True and bank["source_available"] is False
    assert "/memory delete " + fact["id"] in bank["source_guidance"]
    assert "source_available" not in storage().get_blob(ordinary["id"], owner)
    assert any(r.get("historical_finance_snapshot") for r in storage().list_blobs(owner))
    category = facts_store.get_facts_by_category(owner, "finance")
    assert category[0]["source_available"] is False
    result = solve_tools.execute_tool("get_facts_by_category", {"category": "finance"}, None, owner)
    assert "Historical published finance snapshot" in result
    assert "unavailable" in result and "/memory delete " + fact["id"] in result
    assert "source_available" not in facts_store.get_facts_by_category(owner, "hours")[0]


def test_fact_history_convergence_cannot_copy_bank_donor_to_another_company(
    publishing, monkeypatch
):
    env, api, wire = publishing
    isolate(monkeypatch)
    key = current_company_key()
    fact = publish_fact(env, wire)
    keeper = seeding.store_blob(
        storage(),
        UID,
        "facts:" + key,
        "Category: finance\nKey: keeper\nValue: Converged bank fact.",
    )
    with journal.company_transaction(write=True) as session:
        session.add(
            FactHistory(
                company_key=key,
                category="finance",
                fact_key="qonto",
                losing_value=fact["content"],
                losing_owner_id=UID,
                losing_blob_id=fact["id"],
                winning_blob_id=keeper["id"],
                reason="sweep",
            )
        )
    destination()
    from zylch.memory.join import join

    result = join(COMPANY_B)
    assert result["ok"] and result["merged"]["qonto_excluded"] == 2
    assert blob_ids(COMPANY_B) == set()
    assert not rows(COMPANY_B, "SELECT 1 FROM fact_history")
