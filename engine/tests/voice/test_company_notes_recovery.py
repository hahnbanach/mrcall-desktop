"""Source grouping, phrase routing and exact-key billing recovery checks."""

import asyncio
import os
import time
from datetime import datetime

import pytest
from sqlalchemy import create_engine, select

from .test_company_notes import SOURCE, output, provider, save, setup
from zylch.llm.usage import current_call_site
from zylch.services.voice import company_notes as notes
from zylch.services.voice.company_query import CompanyQuery
from zylch.storage.models import LlmReservation

BILLING_CLEAR = notes._billing_clear


def ledger(tmp_path, monkeypatch, sites):
    engine = create_engine(f"sqlite:///{tmp_path / 'reservations.db'}")
    LlmReservation.__table__.create(engine)
    with engine.begin() as conn:
        for index, site in enumerate(sites):
            conn.execute(
                LlmReservation.__table__.insert().values(
                    id=str(index),
                    owner_id="uid-test",
                    created_at=datetime(2026, 9, 28),
                    model="model-one",
                    transport="openrouter",
                    call_site=site,
                    reserved_micro_usd=100,
                    settled_at=None,
                )
            )
    monkeypatch.setattr(notes.database, "get_engine", lambda: engine)
    monkeypatch.setattr(notes, "_billing_clear", BILLING_CLEAR)
    return engine


def test_italian_phrases_and_exact_followup_preserve_category(tmp_path, monkeypatch):
    profile, snapshot = setup(tmp_path, monkeypatch)
    provider(monkeypatch, output())
    view = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    query = CompanyQuery(profile, snapshot, view)
    for phrase in ("Quando consegnate?", "Come funziona la consegna?"):
        result = notes.company_note_detail(profile, snapshot, phrase)
        assert result.status == "supported"
        assert (result.category, result.key) == ("process", "delivery_schedule")
        assert result.text == "We deliver weekly."
        answer, evidence, _ = query(phrase)
        assert "We deliver weekly." in answer
        assert (evidence["category"], evidence["key"]) == ("process", "delivery_schedule")
        query.commit(evidence)
        followup, repeated, _ = query("E quello?")
        assert "We deliver weekly." in followup
        assert repeated == evidence
    assert notes.company_note_detail(profile, snapshot, "Che servizi offrite?").status == "missing"


def test_single_word_key_only_used_by_exact_followup(tmp_path, monkeypatch):
    profile, snapshot = setup(tmp_path, monkeypatch)
    payload = output()
    payload["details"][0]["key"] = "services"
    provider(monkeypatch, payload)
    view = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    assert view.status == "supported"
    assert (
        notes.company_note_detail(profile, snapshot, "What services do you offer?").status
        == "missing"
    )
    assert notes.company_note_detail(profile, snapshot, "Weekly delivery?").status == "supported"
    assert (
        notes.company_note_detail_exact(
            profile, snapshot, "process", "services", view.source_hash
        ).status
        == "supported"
    )


def test_exact_followup_keeps_category_when_keys_collide(tmp_path, monkeypatch):
    source = SOURCE + " Express delivery is unavailable."
    profile, snapshot = setup(tmp_path, monkeypatch, source)
    payload = output(source)
    payload["details"].append(
        {
            "ids": [3],
            "category": "exclusion",
            "key": "delivery_schedule",
            "aliases": ["express delivery"],
        }
    )
    provider(monkeypatch, payload)
    view = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    assert view.status == "supported"
    query = CompanyQuery(profile, snapshot, view)
    _, evidence, _ = query("Weekly delivery?")
    query.commit(evidence)
    reply, repeated, _ = query("E quello?")
    assert "We deliver weekly." in reply
    assert "Express delivery" not in reply
    assert repeated["category"] == "process"
    exclusion = notes.company_note_detail_exact(
        profile, snapshot, "exclusion", "delivery_schedule", view.source_hash
    )
    assert exclusion.text == "Express delivery is unavailable."


@pytest.mark.parametrize(
    "aliases",
    [
        ["deliver"],
        ["delivery", "weekly delivery"],
        ["price offer"],
        ["quali servizi"],
        ["che servizi offrite"],
        ["cosa fate"],
        ["what services"],
    ],
)
def test_rejects_single_word_or_restricted_aliases(tmp_path, monkeypatch, aliases):
    profile, snapshot = setup(tmp_path, monkeypatch)
    payload = output()
    payload["details"][0]["aliases"] = aliases
    provider(monkeypatch, payload)
    assert asyncio.run(notes.prepare_company_notes(profile, snapshot)).status == "unavailable"


def grouped(source, *, services, details=None):
    return notes.Selection.model_validate(
        {
            "identity": None,
            "services": services,
            "qualifications": [],
            "exclusions": [],
            "actions": [],
            "details": details or [],
            "missing": [],
        }
    )


def test_bullet_and_dependent_sentence_materialize_exact_source():
    source = "Services:\n- We repair widgets.\n  Only blue widgets are accepted.\n\nCollection is available."
    units = notes._units(source)
    selection = grouped(source, services=[[0, 1]])
    result = notes._materialize(selection, units, source)
    notes._validate(result, source)
    claim = result.services[0]
    assert claim.text == "Services:\n- We repair widgets.\n  Only blue widgets are accepted."
    assert claim.text == source[claim.start : claim.end]
    assert "Only blue widgets are accepted." in notes._context(result)


@pytest.mark.parametrize("ids", [[0, 2], [1, 0], [0, 0]])
def test_noncontiguous_reordered_or_duplicate_source_groups_refused(ids):
    with pytest.raises(ValueError):
        notes._materialize(grouped(SOURCE, services=[ids]), notes._units(SOURCE), SOURCE)


def test_source_ids_cannot_repeat_between_sections():
    selection = grouped(SOURCE, services=[[0]])
    selection.qualifications = [[0]]
    with pytest.raises(ValueError):
        notes._materialize(selection, notes._units(SOURCE), SOURCE)


def test_restricted_required_qualifier_never_yields_partial_service():
    source = "We repair widgets. Minimum 100 pcs. We paint blue widgets."
    result = notes._materialize(grouped(source, services=[[0, 1]]), notes._units(source), source)
    assert result.services == []
    assert "ambiguous" in result.missing
    with pytest.raises(ValueError, match="No supported service"):
        notes._validate(result, source)
    result = notes._materialize(
        grouped(source, services=[[0, 1], [2]]), notes._units(source), source
    )
    notes._validate(result, source)
    assert [item.text for item in result.services] == ["We paint blue widgets."]
    assert "ambiguous" in result.missing


def test_merged_group_exceeding_claim_budget_refused():
    source = "A" * 350 + ". " + "B" * 350 + "."
    with pytest.raises(ValueError):
        notes._materialize(grouped(source, services=[[0, 1]]), notes._units(source), source)


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("marker_type", ["malformed", "directory", "broken_link"])
def test_uncertain_marker_denies_cached_and_paid_reads(tmp_path, monkeypatch, cached, marker_type):
    profile, snapshot = setup(tmp_path, monkeypatch)
    calls, _ = provider(monkeypatch, output())
    if cached:
        assert asyncio.run(notes.prepare_company_notes(profile, snapshot)).status == "supported"
    calls.clear()
    key = notes._source(profile, snapshot).cache_key
    marker = profile / f".voice-company-notes-uncertain-{key}"
    if marker_type == "directory":
        marker.mkdir()
    elif marker_type == "broken_link":
        marker.symlink_to(profile / "absent")
    else:
        marker.write_text("malformed")
    assert asyncio.run(notes.prepare_company_notes(profile, snapshot)).status == "unavailable"
    assert notes.current_company_notes(profile, snapshot).status == "unavailable"
    assert notes.company_note_detail(profile, snapshot, "Weekly delivery?").status == "unavailable"
    assert (
        notes.company_note_detail_exact(
            profile,
            snapshot,
            "process",
            "delivery_schedule",
            notes._source(profile, snapshot).digest,
        ).status
        == "unavailable"
    )
    assert calls == []


def test_same_key_pending_refuses_replay_after_cooldown_without_row_edits(tmp_path, monkeypatch):
    profile, snapshot = setup(tmp_path, monkeypatch)
    source = notes._source(profile, snapshot)
    assert notes._claim_attempt(profile, source)
    marker = profile / f".voice-company-notes-attempt-{source.cache_key}"
    old = time.time() - notes.RETRY_COOLDOWN_SECONDS - 1
    os.utime(marker, (old, old))
    engine = ledger(tmp_path, monkeypatch, [notes._preparation_site(source.cache_key)])
    calls, _ = provider(monkeypatch, output())
    assert asyncio.run(notes.prepare_company_notes(profile, snapshot)).status == "unavailable"
    assert calls == []
    with engine.connect() as conn:
        row = conn.execute(select(LlmReservation.__table__)).one()
    assert row.settled_at is None
    assert row.reserved_micro_usd == 100


def test_distinct_key_and_legacy_trial_allow_new_tagged_work_without_row_edits(
    tmp_path, monkeypatch
):
    profile, snapshot = setup(tmp_path, monkeypatch)
    sites = [notes._preparation_site("a" * 64), "voice.company_notes.v4_trial"]
    engine = ledger(tmp_path, monkeypatch, sites)
    key = notes._source(profile, snapshot).cache_key
    (profile / f".voice-company-notes-uncertain-{'a' * 64}").write_text("malformed")
    seen = []
    provider(monkeypatch, output())
    factory = notes.make_llm_client

    def recording(model):
        client = factory(model)
        original = client.create_message

        async def create_message(**kwargs):
            seen.append(current_call_site())
            return await original(**kwargs)

        client.create_message = create_message
        return client

    monkeypatch.setattr(notes, "make_llm_client", recording)
    assert asyncio.run(notes.prepare_company_notes(profile, snapshot)).status == "supported"
    assert seen == [notes._preparation_site(key)]
    with engine.connect() as conn:
        rows = conn.execute(select(LlmReservation.__table__)).all()
    assert [row.call_site for row in rows] == sites
    assert all(row.settled_at is None and row.reserved_micro_usd == 100 for row in rows)


def test_same_source_new_model_changes_pinned_cache_key(tmp_path, monkeypatch):
    profile, snapshot = setup(tmp_path, monkeypatch)
    provider(monkeypatch, output())
    before = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    save(profile, SOURCE, model="model-two")
    after = asyncio.run(notes.prepare_company_notes(profile, snapshot))
    assert before.status == after.status == "supported"
    assert before.source_hash == after.source_hash
    assert before.cache_key and before.cache_key != after.cache_key
