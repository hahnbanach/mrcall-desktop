"""Ingestion through the harness: what one source commits, links and indexes.

Against real split databases with the real worker, the real ``LLMClient`` and
the real reservation ledger — only the provider transport is scripted: the
extraction answers with entity blocks, the mnemonic role with decisions. What
these hold is the shape of a committed source: one blob per extracted entity,
the source link and the identity rows for each, the sender in none of them,
the candidates the role is shown, a FACT pinned to its exact row, an empty
extraction as a recorded skip, a long source shown bounded. The crashes,
resumes and refusals are ``test_mnemonic_replay.py``; the bench is
``tests/workers/ingestion_env.py``.
"""

from __future__ import annotations

import json

import pytest

from zylch.memory.blob_storage import BlobStorage
from zylch.memory.mnemonic import ingestion
from zylch.storage.database import get_session
from zylch.storage.models import EmailBlob
from zylch.storage.storage import Storage

from tests.memory.mnemonic_env import COMPANY_A, OWNER_A, BagOfWordsEmbedder
from tests.workers.ingestion_env import (
    ACME,
    FACT_ENTITY,
    LUCA,
    NAME_ONLY,
    blobs,
    booted,
    children_of,
    create_decision,
    email_processed,
    extraction,
    identifiers,
    links,
    make_worker,
    parent_of,
    role_messages,
    run,
    seed_email,
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


def test_a_blob_the_identity_index_finds_by_lid_is_shown_as_an_identifier_match(profile):
    """A ``LID:`` header line is read on the candidate side, so a blob the index
    found by lid is shown as what it is — an identifier match — rather than
    dropped or passed off as a cosine neighbour."""
    lid = "185800503328844@lid"
    nina = (
        "#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Nina Rossi\n"
        f"LID: {lid}\n#ABOUT\nWrites on WhatsApp about the order.\n#HISTORY\n- asked for the invoice"
    )
    storage = BlobStorage(get_session, profile.embedder)
    known = storage.store_blob(
        OWNER_A,
        f"user:{COMPANY_A}",
        f"#IDENTIFIERS\nEntity type: PERSON\nName: N. Rossi\nLID: {lid}\n#ABOUT\nOld note.",
        "seed",
    )
    Storage().add_person_identifiers(OWNER_A, known["id"], [("lid", lid)])
    worker = make_worker([extraction(nina)], [create_decision(nina, "PERSON")])

    assert run(worker, "process_whatsapp_message", seed_whatsapp()) is True

    shown = role_messages(worker)[0]["candidates"]
    assert shown[0]["blob_id"] == known["id"]
    assert shown[0]["retrieved_by"].startswith("identifier")
    assert shown[0]["shared_identifiers"] >= 1


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
