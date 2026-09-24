"""End-to-end tests for `MemoryWorker.process_whatsapp_message` (Phase 2c).

Lock the cross-channel happy path: a WhatsApp message extracted into a
person blob produces:

1. a `blobs` row,
2. a `whatsapp_blobs(message_id, blob_id)` link row,
3. `person_identifiers` rows for the structured Phone / LID,
4. a `whatsapp_messages.memory_processed_at` watermark.

And — most importantly — a WA message from a contact whose phone is
ALREADY in `person_identifiers` (from a previous email) merges into the
existing blob instead of creating a duplicate. That's the load-bearing
contract Phase 1+2 buys for cross-channel identity.

The worker-path cases run on the ingestion bench (``tests/workers/ingestion_env.py``):
the real worker on real split databases, the extraction stubbed, the mnemonic
role's decisions scripted at the transport, inside an admitted preparation
run. The storage-helper and envelope cases keep the plain ``fresh_db`` store.
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from tests.memory.mnemonic_env import COMPANY_A, OWNER_A, BagOfWordsEmbedder
from tests.workers.ingestion_env import booted, make_worker, run


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "wa_memory_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))
    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield db_path
    db_mod.dispose_engine()


def _make_wa_message(
    *,
    owner: str,
    text: str,
    sender_jid: str = "393331234567@s.whatsapp.net",
    sender_name: str = "John",
    is_from_me: bool = False,
    is_group: bool = False,
) -> str:
    """Insert a WhatsAppMessage row, return the row PK."""
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage

    row_id = str(uuid.uuid4())
    with get_session() as s:
        s.add(
            WhatsAppMessage(
                id=row_id,
                owner_id=owner,
                message_id=row_id,
                chat_jid=sender_jid,
                sender_jid=sender_jid,
                sender_name=sender_name,
                text=text,
                timestamp=datetime.now(timezone.utc),
                is_from_me=is_from_me,
                is_group=is_group,
            )
        )
    return row_id


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def profile(tmp_path, monkeypatch, embedder):
    yield from booted(tmp_path, monkeypatch, embedder)


def _make_worker(decisions: list):
    """The real worker with the extraction stubbed and the role's answers scripted.

    ``_extract_entities_for_message`` is stubbed because the extraction is
    well-tested elsewhere — what matters here is the pipeline AROUND it (the
    whatsapp_blobs link, person_identifiers, the watermark), now the harness's.
    """
    worker = make_worker([], decisions)
    worker._extract_entities_for_message = MagicMock()
    return worker


def _create(content: str) -> str:
    return json.dumps(
        {
            "action": "CREATE",
            "entity_type": "PERSON",
            "scope": "entity",
            "content": content,
            "reason": "no visible candidate describes this person",
        }
    )


def _update(blob_id: str, version: str, content: str) -> str:
    return json.dumps(
        {
            "action": "UPDATE",
            "entity_type": "PERSON",
            "scope": "entity",
            "content": content,
            "write_set": [{"blob_id": blob_id, "expected_version": version, "role": "target"}],
            "reason": "the same person, reachable on WhatsApp too",
        }
    )


# ---------------------------------------------------------------------
# Happy path — single message creates a blob + WA link + identifier rows
# ---------------------------------------------------------------------


def test_process_whatsapp_message_creates_blob_and_writes_links(profile):
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob, PersonIdentifier, WhatsAppBlob, WhatsAppMessage
    from zylch.storage.storage import Storage

    owner = OWNER_A
    wa_id = _make_wa_message(owner=owner, text="Ciao Alex, sono John. Ti scrivo per organizzare il corso sicurezza.")

    # Stub the entity extractor to return one synthetic entity with structured #IDENTIFIERS.
    extracted = (
        "#IDENTIFIERS\n"
        "Entity type: PERSON\n"
        "Scope: entity\n"
        "Name: John Smith\n"
        "Phone: +393331234567\n"
        "\n"
        "#ABOUT\n"
        "John reached out about the safety course.\n"
        "\n"
        "#HISTORY\n"
        "First message via WhatsApp."
    )
    worker = _make_worker([_create(extracted)])
    worker._extract_entities_for_message.return_value = [extracted]

    ok = run(
        worker,
        "process_whatsapp_message",
        {
            "id": wa_id,
            "text": "Ciao Alex, sono John. Ti scrivo per organizzare il corso sicurezza.",
            "sender_jid": "393331234567@s.whatsapp.net",
            "sender_name": "John",
            "timestamp": "2026-05-08T10:11:12+00:00",
            "is_from_me": False,
            "is_group": False,
        },
    )
    assert ok is True

    # 1 blob created
    with get_session() as s:
        blobs = s.query(Blob).filter(Blob.owner_id == owner).all()
    assert len(blobs) == 1
    blob_id = str(blobs[0].id)

    # whatsapp_blobs link row written
    with get_session() as s:
        link_rows = (
            s.query(WhatsAppBlob)
            .filter(WhatsAppBlob.owner_id == owner, WhatsAppBlob.blob_id == blob_id)
            .all()
        )
    assert len(link_rows) == 1
    assert link_rows[0].whatsapp_message_id == wa_id

    # person_identifiers row(s) written for the Phone identifier
    with get_session() as s:
        id_rows = (
            s.query(PersonIdentifier)
            .filter(
                PersonIdentifier.owner_id == owner,
                PersonIdentifier.blob_id == blob_id,
            )
            .all()
        )
    kinds_values = {(r.kind, r.value) for r in id_rows}
    assert ("phone", "+393331234567") in kinds_values

    # memory_processed_at watermark advanced
    with get_session() as s:
        row = s.query(WhatsAppMessage).filter(WhatsAppMessage.id == wa_id).one()
    assert row.memory_processed_at is not None

    # Storage helper now reports zero unprocessed for this owner
    storage = Storage()
    assert storage.get_unprocessed_whatsapp_messages(owner) == []


# ---------------------------------------------------------------------
# Cross-channel — WA message merges into existing email-derived blob
# ---------------------------------------------------------------------


def test_process_whatsapp_message_merges_into_existing_email_blob(profile):
    """Phase 1b + Phase 2c happy path: an existing PERSON blob with
    `Phone: +393331234567` in person_identifiers (created during email
    extraction) is the candidate the role is shown first when a WA
    message from the same phone arrives — it updates that row, NO duplicate."""
    from zylch.memory.blob_storage import BlobStorage
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob, WhatsAppBlob
    from zylch.storage.storage import Storage

    owner = OWNER_A
    storage = Storage()

    # Pre-seed an "email-derived" blob with a Phone identifier already
    # indexed into person_identifiers. Mirrors what process_email would
    # leave behind after the user received an email signed by John.
    seeded = BlobStorage(get_session, profile.embedder).store_blob(
        owner,
        f"user:{COMPANY_A}",
        "#IDENTIFIERS\n"
        "Entity type: PERSON\n"
        "Name: John Smith\n"
        "Email: contact@example.com\n"
        "Phone: +393331234567\n"
        "\n"
        "#ABOUT\nFrom email signature.\n",
        "seed",
    )
    pre_blob_id = seeded["id"]
    version = BlobStorage(get_session, profile.embedder).get_blob(pre_blob_id, owner)["updated_at"]
    storage.add_person_identifiers(
        owner,
        pre_blob_id,
        [("email", "contact@example.com"), ("phone", "+393331234567")],
    )

    # Now arrive a WhatsApp message from the same phone.
    wa_id = _make_wa_message(owner=owner, text="Alex, ricordi del corso? Aspetto risposta.")

    # The role is asked to decide the WA-derived entity against the existing
    # blob; it answers with the merged text as an UPDATE of that row.
    merged_content = (
        "#IDENTIFIERS\n"
        "Entity type: PERSON\n"
        "Scope: entity\n"
        "Name: John Smith\n"
        "Email: contact@example.com\n"
        "Phone: +393331234567\n"
        "\n"
        "#ABOUT\nFrom email signature.\n"
        "\n"
        "#HISTORY\nNow also reachable via WhatsApp."
    )
    worker = _make_worker([_update(pre_blob_id, version, merged_content)])

    extracted = (
        "#IDENTIFIERS\n"
        "Entity type: PERSON\n"
        "Name: John Smith\n"
        "Phone: +393331234567\n"
        "\n"
        "#ABOUT\nWhatsApp follow-up about the course.\n"
        "\n"
        "#HISTORY\nMessage on 2026-05-08."
    )
    worker._extract_entities_for_message.return_value = [extracted]

    ok = run(
        worker,
        "process_whatsapp_message",
        {
            "id": wa_id,
            "text": "Alex, ricordi del corso? Aspetto risposta.",
            "sender_jid": "393331234567@s.whatsapp.net",
            "sender_name": "John",
            "timestamp": "2026-05-08T11:00:00+00:00",
            "is_from_me": False,
            "is_group": False,
        },
    )
    assert ok is True
    shown = json.loads(worker.decision_client._client.messages.create.call_args.kwargs["messages"][0]["content"])
    assert shown["candidates"][0]["blob_id"] == pre_blob_id

    # Still exactly ONE blob — merged into the pre-existing email-derived blob.
    with get_session() as s:
        blobs = s.query(Blob).filter(Blob.owner_id == owner).all()
    assert len(blobs) == 1, "expected merge into existing blob, not a duplicate"
    assert str(blobs[0].id) == pre_blob_id

    # whatsapp_blobs row points to the SAME blob_id, not a new one.
    with get_session() as s:
        wa_links = (
            s.query(WhatsAppBlob)
            .filter(WhatsAppBlob.owner_id == owner, WhatsAppBlob.whatsapp_message_id == wa_id)
            .all()
        )
    assert len(wa_links) == 1
    assert wa_links[0].blob_id == pre_blob_id


# ---------------------------------------------------------------------
# Skip / mark-as-processed paths
# ---------------------------------------------------------------------


def test_process_whatsapp_skips_short_text_but_marks_processed(profile):
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob, WhatsAppBlob, WhatsAppMessage

    owner = OWNER_A
    wa_id = _make_wa_message(owner=owner, text="ok")

    worker = _make_worker([])
    worker._extract_entities_for_message.return_value = []  # would never be called

    ok = run(
        worker,
        "process_whatsapp_message",
        {
            "id": wa_id,
            "text": "ok",
            "sender_jid": "393331234567@s.whatsapp.net",
            "sender_name": "John",
            "timestamp": "2026-05-08T10:11:12+00:00",
            "is_from_me": False,
            "is_group": False,
        },
    )
    assert ok is True

    # No blob, no whatsapp_blobs link, but watermark advanced.
    with get_session() as s:
        assert s.query(Blob).filter(Blob.owner_id == owner).count() == 0
        assert s.query(WhatsAppBlob).filter(WhatsAppBlob.owner_id == owner).count() == 0
        row = s.query(WhatsAppMessage).filter(WhatsAppMessage.id == wa_id).one()
    assert row.memory_processed_at is not None
    # Extraction must NOT have been called for short text
    worker._extract_entities_for_message.assert_not_called()


def test_process_whatsapp_marks_processed_when_extractor_returns_empty(profile):
    """An empty valid extraction is a recorded SKIP that marks the source."""
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob, MemoryOperation, WhatsAppMessage

    owner = OWNER_A
    wa_id = _make_wa_message(
        owner=owner, text="Some long enough message that the worker will try to extract from."
    )

    worker = _make_worker([])
    worker._extract_entities_for_message.return_value = []  # LLM said SKIP

    ok = run(
        worker,
        "process_whatsapp_message",
        {
            "id": wa_id,
            "text": "Some long enough message that the worker will try to extract from.",
            "sender_jid": "393331234567@s.whatsapp.net",
            "sender_name": "John",
            "timestamp": "2026-05-08T10:11:12+00:00",
            "is_from_me": False,
            "is_group": False,
        },
    )
    assert ok is True
    with get_session() as s:
        assert [r.state for r in s.query(MemoryOperation).all()] == ["skipped"]

    with get_session() as s:
        assert s.query(Blob).filter(Blob.owner_id == owner).count() == 0
        row = s.query(WhatsAppMessage).filter(WhatsAppMessage.id == wa_id).one()
    assert row.memory_processed_at is not None


# ---------------------------------------------------------------------
# Storage helpers — group filter + watermark roundtrip
# ---------------------------------------------------------------------


def test_get_unprocessed_whatsapp_messages_excludes_groups(fresh_db):
    from zylch.storage.storage import Storage

    owner = "alice@example.com"
    direct_id = _make_wa_message(owner=owner, text="hello world from a person")
    _ = _make_wa_message(
        owner=owner,
        text="group chatter",
        sender_jid="123456-1234567@g.us",
        is_group=True,
    )

    storage = Storage()
    unprocessed = storage.get_unprocessed_whatsapp_messages(owner)
    ids = {row["id"] for row in unprocessed}
    assert direct_id in ids
    assert len(ids) == 1, "group message should be filtered out"


def test_mark_whatsapp_memory_processed_advances_watermark(fresh_db):
    from zylch.storage.storage import Storage

    owner = "alice@example.com"
    wa_id = _make_wa_message(owner=owner, text="some message that crosses the min length")

    storage = Storage()
    assert any(r["id"] == wa_id for r in storage.get_unprocessed_whatsapp_messages(owner))
    storage.mark_whatsapp_memory_processed(owner, wa_id)
    assert storage.get_unprocessed_whatsapp_messages(owner) == []


# ---------------------------------------------------------------------
# Envelope formatter — channel hints visible in user message
# ---------------------------------------------------------------------


def _make_envelope_worker(owner: str = "alice@example.com"):
    """Bare worker with just enough state for `_format_whatsapp_data`.

    `_format_whatsapp_data` calls ``self.storage.get_whatsapp_contact_by_jid``,
    so we hand it a real Storage bound to the active fresh_db.
    """
    from zylch.workers.memory import MemoryWorker
    from zylch.storage.storage import Storage

    worker = MemoryWorker.__new__(MemoryWorker)
    worker.storage = Storage()
    worker.owner_id = owner
    return worker


def _add_wa_contact(owner: str, jid: str, phone: str | None, name: str | None) -> None:
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppContact

    with get_session() as s:
        s.add(
            WhatsAppContact(
                owner_id=owner,
                jid=jid,
                phone_number=phone,
                name=name,
            )
        )


def test_format_whatsapp_data_emits_channel_phone_and_text(fresh_db):
    worker = _make_envelope_worker()
    out = worker._format_whatsapp_data(
        {
            "sender_jid": "393331234567@s.whatsapp.net",
            "sender_name": "John",
            "timestamp": "2026-05-08T10:11:12+00:00",
            "text": "Ciao Alex, ricordi del corso?",
        }
    )
    assert "Channel: WhatsApp" in out
    assert "John" in out
    assert "+393331234567" in out
    assert "Group: (1-on-1)" in out
    assert "Phone: +393331234567" in out
    assert "Ciao Alex, ricordi del corso?" in out
    # No bogus +<lid> string
    assert "@lid" not in out


def test_format_whatsapp_data_lid_unresolved_does_not_render_as_plus_phone(fresh_db):
    """LIDs are NOT phone numbers. With NO whatsapp_contacts row to
    resolve from, the LID line stays but the envelope never invents a
    Phone: out of LID digits."""
    worker = _make_envelope_worker()
    out = worker._format_whatsapp_data(
        {
            "sender_jid": "19095575629933@lid",
            "sender_name": "",
            "timestamp": "2026-05-08T10:11:12+00:00",
            "text": "Some message about a topic",
        }
    )
    assert "Channel: WhatsApp" in out
    assert "LID: 19095575629933@lid" in out
    assert "+19095575629933" not in out
    assert "Phone:" not in out


def test_format_whatsapp_data_resolves_lid_to_phone_via_contacts(fresh_db):
    """When ``whatsapp_contacts`` carries a LID→phone mapping, the
    envelope MUST surface BOTH the resolved Phone (so cross-channel
    identity matches the email-derived blob) AND the LID (so future
    LID-only matches still work)."""
    owner = "alice@example.com"
    _add_wa_contact(
        owner,
        jid="185800503328844@lid",
        phone="+393331234567",
        name="John Smith",
    )

    worker = _make_envelope_worker(owner)
    out = worker._format_whatsapp_data(
        {
            "sender_jid": "185800503328844@lid",
            "sender_name": "",  # the contact lookup fills this in
            "timestamp": "2026-05-08T10:11:12+00:00",
            "text": "Ciao Alex, sentiamoci per il corso.",
        }
    )
    assert "Channel: WhatsApp" in out
    # Resolved name appears in the From line, not the bare jid
    assert "John Smith" in out
    assert "+393331234567" in out
    # Both Phone: AND LID: lines emitted — Phase 1 indexes both
    assert "Phone: +393331234567" in out
    assert "LID: 185800503328844@lid" in out


def test_normalise_phone_rejects_lid_shaped_input():
    """Hardening: if the LLM ever writes ``Phone: <digits>@lid``, the
    parser must NOT strip the @suffix and index the leading digits as
    a phone — that would pollute the cross-channel index with bogus
    matches against unrelated phone numbers."""
    from zylch.workers.memory import _normalise_phone

    assert _normalise_phone("185800503328844@lid") is None
    assert _normalise_phone("user@example.com") is None
    # Real phones still parse
    assert _normalise_phone("+393331234567") == "+393331234567"
    assert _normalise_phone("00393331234567") == "+393331234567"


def test_parse_identifiers_reroutes_lid_in_phone_field_to_lid_kind():
    """If the LLM mislabels a LID as a Phone:, the parser routes it to
    the LID kind anyway so Phase 1's identifier-first match still has
    a signal."""
    from zylch.workers.memory import _parse_identifiers_block

    block = (
        "#IDENTIFIERS\n"
        "Entity type: PERSON\n"
        "Name: Nina\n"
        "Phone: 185800503328844@lid\n"
        "\n"
        "#ABOUT\n"
        "irrelevant\n"
    )
    out = _parse_identifiers_block(block)
    # The LID survives — not as a phone — so cross-LID matching still works
    assert ("lid", "185800503328844@lid") in out
    # And there is NO bogus phone row from the digit-strip
    assert not any(k == "phone" for k, _ in out)
