"""Ingestion through the harness: one replay contract for every channel.

Against real split databases with the real worker, the real ``LLMClient`` and
the real reservation ledger — only the provider transport is scripted: the
extraction answers with entity blocks, the mnemonic role with decisions. The
crashes are real ``BaseException``s raised from injected faults, and a resume
is a new preparation run after the backoff, on the same files. The bench is
``tests/workers/ingestion_env.py``.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from zylch.llm.budget import BudgetError
from zylch.memory.blob_storage import BlobStorage
from zylch.memory.mnemonic import ingestion, journal, manifest
from zylch.memory.mnemonic.turn import revocable_turn
from zylch.services import preparation
from zylch.services.preparation import PreparationStopped, preparation_run
from zylch.storage.database import get_session
from zylch.storage.models import CalendarBlob, CalendarEvent, EmailBlob, MrcallConversation, WhatsAppBlob, WhatsAppMessage
from zylch.storage.storage import Storage

from tests.memory.mnemonic_env import COMPANY_A, OWNER_A, BagOfWordsEmbedder, client
from tests.workers.ingestion_env import (
    ACME,
    FACT_ENTITY,
    LUCA,
    NAME_ONLY,
    Crash,
    attempt_rows,
    blobs,
    booted,
    children_of,
    create_decision,
    email_processed,
    extraction,
    identifiers,
    links,
    make_worker,
    operations,
    parent_of,
    resume,
    role_messages,
    run,
    seed_calendar,
    seed_email,
    seed_mrcall,
    seed_whatsapp,
    update_decision,
)


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def profile(tmp_path, monkeypatch, embedder):
    yield from booted(tmp_path, monkeypatch, embedder)


# ─── The commit, the links, the identifiers, the sender ───────────────


def test_one_mail_with_two_entities_commits_two_blobs_and_the_sender_is_in_neither(profile):
    mail = seed_email()
    worker = make_worker(
        [extraction(LUCA, ACME)],
        [create_decision(LUCA, "PERSON"), create_decision(ACME, "COMPANY")],
    )

    assert run(worker, "process_email", mail) is True

    stored = blobs()
    assert len(stored) == 2
    assert links(EmailBlob, "email_id", "mail-1") == set(stored)
    rows = identifiers()
    assert {(k, v) for _, k, v in rows} == {("email", "luca@alpha.example"), ("email", "info@acme.test")}
    assert not any(v == "mario@acme.test" for _, _, v in rows)
    shown = role_messages(worker)
    assert shown[0]["subject_hint"] == {
        "entity_type": "PERSON",
        "name": "Luca Bianchi",
        "identifiers": [["email", "luca@alpha.example"]],
    }
    assert "mario@acme.test" not in json.dumps(shown[0]["subject_hint"])
    assert shown[0]["caller_class"] == "automatic_observation"
    parent = parent_of("mail-1")
    assert parent["state"] == "committed"
    assert len(parent["result"]["committed_ids"]) == 2
    kids = children_of(parent["event_id"])
    assert sorted(kids) == [f"{parent['event_id']}:0", f"{parent['event_id']}:1"]
    assert {k["state"] for k in kids.values()} == {"committed"}
    assert email_processed("mail-1")


def test_a_name_only_entity_gets_a_blob_and_no_identifier(profile):
    mail = seed_email()
    worker = make_worker([extraction(NAME_ONLY)], [create_decision(NAME_ONLY, "COMPANY")])
    assert run(worker, "process_email", mail) is True
    assert len(blobs()) == 1
    assert identifiers() == set()
    assert role_messages(worker)[0]["subject_hint"] == {"entity_type": "COMPANY", "name": "Example Ltd"}


NAME_ONLY_PERSON = (
    "#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Luca Bianchi\nCompany: Acme\n"
    "#ABOUT\nColleague of the sender; will call about the order."
)


def test_a_name_only_person_never_inherits_the_senders_identity(profile):
    """The sender has a blob whose address is in the identity index. A person
    the mail merely mentions, with a name and no address of their own, must not
    be judged by that address: the index is not asked with it, the sender's
    blob is not evidence, and the person is created."""
    storage = BlobStorage(get_session, profile.embedder)
    sender = storage.store_blob(
        OWNER_A,
        f"user:{COMPANY_A}",
        "#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Mario Verdi\nEmail: mario@acme.test\n#ABOUT\nBuyer.",
        "seed",
    )
    Storage().add_person_identifiers(OWNER_A, sender["id"], [("email", "mario@acme.test")])
    mail = seed_email(body="Luca Bianchi, my colleague at Acme, will call you about the order.")
    worker = make_worker([extraction(NAME_ONLY_PERSON)], [create_decision(NAME_ONLY_PERSON, "PERSON")])
    asked = []
    real = worker.storage.find_blobs_by_identifiers

    def spying(owner_id, identifiers):
        asked.append(list(identifiers))
        return real(owner_id, identifiers)

    worker.storage.find_blobs_by_identifiers = spying

    assert run(worker, "process_email", mail) is True

    assert asked == []  # a name states no identity, so the index is never asked
    shown = role_messages(worker)[0]
    assert shown["subject_hint"] == {"entity_type": "PERSON", "name": "Luca Bianchi", "company": "Acme"}
    assert all(c["shared_identifiers"] == 0 for c in shown["candidates"])
    assert len(blobs()) == 2
    assert {v for _, _, v in identifiers()} == {"mario@acme.test"}


def test_the_candidates_the_role_is_shown_are_identifier_first_then_cosine(profile):
    """The ``test_person_identifiers`` incident, on the harness: blob A is in
    the identity index, blob B is only a cosine match, and A is shown first."""
    storage = BlobStorage(get_session, profile.embedder)
    a = storage.store_blob(OWNER_A, f"user:{COMPANY_A}", LUCA.replace("Purchasing at Alpha.", "Old note."), "seed")
    Storage().add_person_identifiers(OWNER_A, a["id"], [("email", "luca@alpha.example")])
    b = storage.store_blob(
        OWNER_A,
        f"user:{COMPANY_A}",
        "#IDENTIFIERS\nEntity type: PERSON\nName: Luca Bianchi\n#ABOUT\nPurchasing at Alpha, maybe.",
        "seed",
    )
    version = storage.get_blob(a["id"], OWNER_A)["updated_at"]
    mail = seed_email()
    worker = make_worker([extraction(LUCA)], [update_decision(a["id"], version, LUCA, "PERSON")])

    assert run(worker, "process_email", mail) is True

    shown = role_messages(worker)[0]["candidates"]
    assert [c["blob_id"] for c in shown][:2] == [a["id"], b["id"]]
    assert shown[0]["shared_identifiers"] >= 1
    assert blobs()[a["id"]] == LUCA
    assert len(blobs()) == 2


def test_a_fact_entity_pins_its_exact_row(profile):
    storage = BlobStorage(get_session, profile.embedder)
    fact = storage.store_blob(OWNER_A, f"facts:{COMPANY_A}", "Category: pricing\nKey: list\nValue: EUR 100 per unit", "seed")
    version = storage.get_blob(fact["id"], OWNER_A)["updated_at"]
    mail = seed_email(body="Our list price is now EUR 120 per unit.")
    worker = make_worker([extraction(FACT_ENTITY)], [update_decision(fact["id"], version, FACT_ENTITY, "FACT")])

    assert run(worker, "process_email", mail) is True

    shown = role_messages(worker)[0]
    assert shown["subject_hint"] == {"entity_type": "FACT", "target_blob_id": fact["id"]}
    assert shown["candidates"][0]["blob_id"] == fact["id"]
    assert blobs()[fact["id"]] == FACT_ENTITY
    assert len(blobs()) == 1


def test_an_empty_extraction_is_a_recorded_skip_that_marks_the_source(profile):
    mail = seed_email()
    worker = make_worker(["SKIP"], [])
    assert run(worker, "process_email", mail) is True
    parent = parent_of("mail-1")
    assert parent["state"] == "skipped"
    assert children_of(parent["event_id"]) == {}
    assert blobs() == {}
    assert email_processed("mail-1")


def test_a_long_source_is_extracted_in_full_and_shown_bounded(profile):
    body = ("Acme confirms the order. " * 1200).strip()  # > 20,000 characters
    mail = seed_email(body=body)
    worker = make_worker([extraction(ACME)], [create_decision(ACME, "COMPANY")])

    assert run(worker, "process_email", mail) is True

    sent_to_extraction = worker.client._client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert body in sent_to_extraction
    shown = role_messages(worker)[0]
    assert len(shown["observation"]) <= ingestion.MAX_OBSERVATION_CHARS
    assert "[observation truncated:" in shown["observation"]
    full = worker._format_email_data(mail, "mario@acme.test")
    assert shown["source"]["revision"] == ingestion.Source("email", "mail-1", full, "memory:email").revision


# ─── Crashes and resumes ──────────────────────────────────────────────


def test_a_crash_before_the_manifest_save_re_extracts_on_resume(profile, monkeypatch):
    mail = seed_email()
    worker = make_worker([extraction(LUCA), extraction(LUCA)], [create_decision(LUCA, "PERSON")])
    real = manifest.record_manifest
    crashes = {"left": 1}

    def crashing(*args, **kwargs):
        if crashes["left"]:
            crashes["left"] -= 1
            raise Crash()
        return real(*args, **kwargs)

    monkeypatch.setattr(ingestion.manifest, "record_manifest", crashing)
    with pytest.raises(Crash):
        run(worker, "process_email", mail)
    parent = parent_of("mail-1")
    assert parent["state"] == "pending" and children_of(parent["event_id"]) == {}
    assert worker.client._client.messages.create.call_count == 1
    assert not email_processed("mail-1")

    resume(profile)
    assert run(worker, "process_email", mail) is True
    assert worker.client._client.messages.create.call_count == 2
    assert len(blobs()) == 1 and email_processed("mail-1")


def test_a_crash_between_children_resumes_only_the_unfinished_child(profile):
    mail = seed_email()
    worker = make_worker([extraction(LUCA, ACME)], [create_decision(LUCA, "PERSON"), Crash()])

    with pytest.raises(Crash):
        run(worker, "process_email", mail)
    parent = parent_of("mail-1")
    kids = children_of(parent["event_id"])
    assert kids[f"{parent['event_id']}:0"]["state"] == "committed"
    assert kids[f"{parent['event_id']}:1"]["state"] == "pending"
    assert len(blobs()) == 1 and not email_processed("mail-1")

    resume(profile)
    worker.decision_client = client(create_decision(ACME, "COMPANY"))
    assert run(worker, "process_email", mail) is True
    assert worker.client._client.messages.create.call_count == 1  # no second extraction
    assert worker.decision_client._client.messages.create.call_count == 1  # only the unfinished child
    assert len(blobs()) == 2 and email_processed("mail-1")
    assert parent_of("mail-1")["state"] == "committed"


def test_a_crash_after_the_commit_and_before_the_checkpoint_marks_on_resume_without_paying(profile, monkeypatch):
    mail = seed_email()
    worker = make_worker([extraction(LUCA)], [create_decision(LUCA, "PERSON")])
    real = Storage.mark_email_processed
    crashes = {"left": 1}

    def crashing(self, owner_id, email_id):
        if crashes["left"]:
            crashes["left"] -= 1
            raise Crash()
        return real(self, owner_id, email_id)

    monkeypatch.setattr(Storage, "mark_email_processed", crashing)
    with pytest.raises(Crash):
        run(worker, "process_email", mail)
    assert parent_of("mail-1")["state"] == "committed"
    assert len(blobs()) == 1 and not email_processed("mail-1")

    resume(profile)
    assert run(worker, "process_email", mail) is True
    assert worker.client._client.messages.create.call_count == 1
    assert worker.decision_client._client.messages.create.call_count == 1
    assert len(blobs()) == 1 and email_processed("mail-1")


def test_a_pause_between_children_arrives_as_preparation_stopped_and_keeps_the_attempt_row(profile, monkeypatch):
    mail = seed_email()
    worker = make_worker(
        [extraction(LUCA, ACME)],
        [create_decision(LUCA, "PERSON"), create_decision(ACME, "COMPANY")],
    )
    real = ingestion.submit

    def pausing(child, **kwargs):
        result = real(child, **kwargs)
        preparation.pause(OWNER_A)  # the user presses pause after the first child
        return result

    monkeypatch.setattr(ingestion, "submit", pausing)
    with pytest.raises(PreparationStopped):
        run(worker, "process_email", mail)

    assert worker.decision_client._client.messages.create.call_count == 1
    parent = parent_of("mail-1")
    kids = children_of(parent["event_id"])
    assert kids[f"{parent['event_id']}:0"]["state"] == "committed"
    assert kids[f"{parent['event_id']}:1"]["state"] == "failed"
    assert parent["state"] == "pending"
    assert not email_processed("mail-1")
    rows = attempt_rows()
    assert rows == [{"stage": "memory:email", "source": "mail-1", "inflight": 0, "dispatched": 1, "failures": 1}]


def test_a_budget_refusal_in_a_child_costs_no_allowance_and_stops_the_batch(profile, monkeypatch):
    first, second = seed_email("mail-1"), seed_email("mail-2", body="Second mail about Acme.")
    worker = make_worker([extraction(LUCA), extraction(ACME)], [create_decision(LUCA, "PERSON")])
    from zylch.llm import budget

    real_reserve = budget.reserve

    def refusing(request_kwargs, transport, **kwargs):
        from zylch.llm.usage import current_call_site

        if current_call_site() == "memory.mnemonic":
            raise BudgetError("Daily AI budget unavailable")
        return real_reserve(request_kwargs, transport, **kwargs)

    monkeypatch.setattr(budget, "reserve", refusing)

    with pytest.raises(BudgetError), preparation_run(OWNER_A):
        asyncio.run(worker.process_batch([first, second], concurrency=1))

    parent = parent_of("mail-1")
    child = children_of(parent["event_id"])[f"{parent['event_id']}:0"]
    assert child["state"] == "failed"
    assert child["allowance"] == journal.EVENT_DISPATCH_ALLOWANCE  # refused before dispatch
    assert worker.decision_client._client.messages.create.call_count == 0
    assert worker.client._client.messages.create.call_count == 1  # the batch stopped before mail-2
    assert blobs() == {} and not email_processed("mail-1") and not email_processed("mail-2")


def test_an_extraction_refused_by_the_budget_leaves_the_parent_pending_and_resumes(profile, monkeypatch):
    """The refusal happens before the parent's dispatch: the exception reaches
    the batch untouched, the parent keeps its row and its lease with no manifest,
    and the next run re-extracts under a fresh claim."""
    mail = seed_email()
    worker = make_worker([extraction(LUCA)], [create_decision(LUCA, "PERSON")])
    from zylch.llm import budget

    real_reserve = budget.reserve
    refusing = {"on": True}

    def maybe_refuse(request_kwargs, transport, **kwargs):
        from zylch.llm.usage import current_call_site

        if refusing["on"] and current_call_site() == "memory.extract":
            raise BudgetError("Daily AI budget unavailable")
        return real_reserve(request_kwargs, transport, **kwargs)

    monkeypatch.setattr(budget, "reserve", maybe_refuse)
    with pytest.raises(BudgetError):
        run(worker, "process_email", mail)
    parent = parent_of("mail-1")
    assert parent["state"] == "pending" and parent["lease"]
    assert manifest.read_manifest(parent["event_id"]) is None
    assert worker.client._client.messages.create.call_count == 0
    assert parent["allowance"] == journal.EVENT_DISPATCH_ALLOWANCE

    refusing["on"] = False
    resume(profile)
    assert run(worker, "process_email", mail) is True
    assert worker.client._client.messages.create.call_count == 1
    assert len(blobs()) == 1 and email_processed("mail-1")


def test_a_source_edit_is_a_new_parent_and_never_an_old_digest_reused(profile):
    mail = seed_email(body="First version.")
    worker = make_worker([extraction(LUCA), extraction(LUCA)], [create_decision(LUCA, "PERSON")])
    assert run(worker, "process_email", mail) is True
    edited = {**mail, "body_plain": "Second version, the voice note transcribed."}
    profile.clock[0] += 1000
    # The second pass sees the blob the first one created, so a second CREATE
    # would be refused as a duplicate: the role updates it.
    (luca_id, _content), = blobs().items()
    version = BlobStorage(get_session, profile.embedder).get_blob(luca_id, OWNER_A)["updated_at"]
    worker.decision_client = client(update_decision(luca_id, version, LUCA.replace("Purchasing", "Now sales"), "PERSON"))

    assert run(worker, "process_email", edited) is True

    parents = [r for r in operations().values() if r["parent_event_id"] is None]
    assert len(parents) == 2 and len({p["source_ref"] for p in parents}) == 2
    assert worker.client._client.messages.create.call_count == 2


def test_an_oversized_extraction_is_a_review_and_nothing_is_written(profile):
    mail = seed_email()
    many = [LUCA.replace("Luca Bianchi", f"Person {i}") for i in range(ingestion.MAX_EXTRACTED_ENTITIES + 1)]
    worker = make_worker([extraction(*many)], [])
    assert run(worker, "process_email", mail) is False
    parent = parent_of("mail-1")
    assert parent["state"] == "review" and "bound" in parent["result"]["reason"]
    assert children_of(parent["event_id"]) == {}
    assert blobs() == {} and not email_processed("mail-1")


def test_an_unhealthy_merge_gate_shows_the_role_no_candidate_and_keeps_the_fact_pin(profile):
    storage = BlobStorage(get_session, profile.embedder)
    luca = storage.store_blob(OWNER_A, f"user:{COMPANY_A}", LUCA, "seed")
    Storage().add_person_identifiers(OWNER_A, luca["id"], [("email", "luca@alpha.example")])
    fact = storage.store_blob(OWNER_A, f"facts:{COMPANY_A}", "Category: pricing\nKey: list\nValue: EUR 100", "seed")
    version = storage.get_blob(fact["id"], OWNER_A)["updated_at"]
    mail = seed_email()
    worker = make_worker(
        [extraction(LUCA, FACT_ENTITY)],
        [create_decision(LUCA, "PERSON"), update_decision(fact["id"], version, FACT_ENTITY, "FACT")],
    )
    worker.merge_enabled = False

    assert run(worker, "process_email", mail) is True

    shown = role_messages(worker)
    assert shown[0]["candidates"] == []
    assert [c["blob_id"] for c in shown[1]["candidates"]] == [fact["id"]]
    assert len(blobs()) == 3  # Luca twice: the brake makes a fresh blob, recoverable by the sweep


@pytest.mark.parametrize(
    "kind, seeder, method, model, column, marker",
    [
        ("whatsapp", seed_whatsapp, "process_whatsapp_message", WhatsAppBlob, "whatsapp_message_id", WhatsAppMessage),
        ("calendar", seed_calendar, "process_calendar_event", CalendarBlob, "event_id", CalendarEvent),
        ("mrcall", seed_mrcall, "process_mrcall_conversation", None, None, MrcallConversation),
    ],
)
def test_whatsapp_calendar_and_mrcall_run_the_same_path(profile, kind, seeder, method, model, column, marker):
    item = seeder()
    extracted = "Marta Riva of Acme attended as finance lead." if kind == "calendar" else extraction(LUCA)
    decided = create_decision(
        "#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Marta Riva\nCompany: Acme\n#ABOUT\nFinance lead." if kind == "calendar" else LUCA,
        "PERSON",
    )
    worker = make_worker([extracted], [decided])

    assert run(worker, method, item) is True

    assert len(blobs()) == 1
    parent = next(r for r in operations().values() if r["parent_event_id"] is None)
    assert parent["source_ref"].startswith(f"{kind}:{item['id']}@")
    assert parent["state"] == "committed"
    if model is not None:
        assert links(model, column, item["id"]) == set(blobs())
    with get_session() as session:
        assert session.get(marker, item["id"]).memory_processed_at is not None


# ─── A refusal a later run can satisfy is not a review ────────────────


def test_extraction_outside_an_admitted_item_keeps_the_source_retryable(profile):
    """Reached with no preparation run behind it, the worker gets no grant:
    nothing is asked of a provider, the parent stays pending, and the same
    source commits on the next admitted run with the extraction still to spend."""
    mail = seed_email()
    worker = make_worker([extraction(LUCA)], [create_decision(LUCA, "PERSON")])

    asyncio.run(worker.process_email(mail))

    parent = parent_of("mail-1")
    assert parent["state"] == "pending" and children_of(parent["event_id"]) == {}
    assert blobs() == {} and not email_processed("mail-1")

    run(worker, "process_email", mail)

    assert parent_of("mail-1")["state"] == "committed" and email_processed("mail-1")
    assert len(blobs()) == 1


def test_a_turn_cancelled_before_extraction_keeps_the_source_retryable(profile):
    mail = seed_email()
    worker = make_worker([extraction(LUCA)], [create_decision(LUCA, "PERSON")])

    with revocable_turn() as handle:
        handle.cancel("stopped before extraction")
        run(worker, "process_email", mail)

    parent = parent_of("mail-1")
    assert parent["state"] == "pending" and blobs() == {} and not email_processed("mail-1")
    resume(profile)  # the scheduler's own backoff, elapsed

    run(worker, "process_email", mail)

    assert parent_of("mail-1")["state"] == "committed" and email_processed("mail-1")
