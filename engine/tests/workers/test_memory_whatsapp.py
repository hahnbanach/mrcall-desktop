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

The LLM client is mocked via `make_llm_client`; the merge service is
mocked at the worker level. Storage is real (in-memory SQLite via the
`fresh_db` fixture).
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


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
    sender_jid: str = "393395040816@s.whatsapp.net",
    sender_name: str = "Carmine",
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


def _make_worker(owner: str, *, llm_merge_returns: list):
    """Build a MemoryWorker with the LLM client + merge service mocked.

    Storage / hybrid_search / blob_storage / person_identifiers are all
    real against the active fresh_db.
    """
    from zylch.workers import memory as mem_mod

    fake_client = MagicMock()
    with patch.object(mem_mod, "make_llm_client", return_value=fake_client):
        worker = mem_mod.MemoryWorker(
            storage=__import__("zylch.storage", fromlist=["Storage"]).Storage(),
            owner_id=owner,
        )

    fake_merge = MagicMock()
    fake_merge.merge.side_effect = list(llm_merge_returns)
    worker.llm_merge = fake_merge

    # ``has_custom_prompt`` is checked by the pipeline — we don't go via
    # the pipeline here, but ``_extract_entities_for_message`` does call
    # ``_get_extraction_prompt``. Stub a non-empty value so we don't take
    # the "no prompt → return []" branch.
    worker._custom_prompt = "FAKE PROMPT"
    worker._custom_prompt_loaded = True

    # Stub _extract_entities_for_message to avoid the real LLM call. The
    # extraction is well-tested elsewhere — what we care about here is
    # the pipeline AROUND it (whatsapp_blobs link, person_identifiers,
    # watermark).
    worker._extract_entities_for_message = MagicMock()

    return worker


# ---------------------------------------------------------------------
# Happy path — single message creates a blob + WA link + identifier rows
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_whatsapp_message_creates_blob_and_writes_links(fresh_db):
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob, PersonIdentifier, WhatsAppBlob, WhatsAppMessage
    from zylch.storage.storage import Storage

    owner = "alice@example.com"
    wa_id = _make_wa_message(owner=owner, text="Ciao Mario, sono Carmine. Ti scrivo per organizzare il corso sicurezza.")

    worker = _make_worker(owner, llm_merge_returns=[])

    # Mock the entity extractor to return one synthetic entity with structured #IDENTIFIERS.
    extracted = (
        "#IDENTIFIERS\n"
        "Entity type: PERSON\n"
        "Name: Carmine Salamone\n"
        "Phone: +393395040816\n"
        "\n"
        "#ABOUT\n"
        "Carmine reached out about the safety course.\n"
        "\n"
        "#HISTORY\n"
        "First message via WhatsApp."
    )
    worker._extract_entities_for_message.return_value = [extracted]

    ok = await worker.process_whatsapp_message(
        {
            "id": wa_id,
            "text": "Ciao Mario, sono Carmine. Ti scrivo per organizzare il corso sicurezza.",
            "sender_jid": "393395040816@s.whatsapp.net",
            "sender_name": "Carmine",
            "timestamp": "2026-05-08T10:11:12+00:00",
            "is_from_me": False,
            "is_group": False,
        }
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
    assert ("phone", "+393395040816") in kinds_values

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


@pytest.mark.asyncio
async def test_process_whatsapp_message_merges_into_existing_email_blob(fresh_db):
    """Phase 1b + Phase 2c happy path: an existing PERSON blob with
    `Phone: +393395040816` in person_identifiers (created during email
    extraction) should be picked up as the merge target when a WA
    message from the same phone arrives — NO duplicate blob."""
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob, WhatsAppBlob
    from zylch.storage.storage import Storage

    owner = "alice@example.com"
    storage = Storage()

    # Pre-seed an "email-derived" blob with a Phone identifier already
    # indexed into person_identifiers. Mirrors what process_email would
    # leave behind after the user received an email signed by Carmine.
    pre_blob_id = str(uuid.uuid4())
    with get_session() as s:
        s.add(
            Blob(
                id=pre_blob_id,
                owner_id=owner,
                namespace=f"user:{owner}",
                content=(
                    "#IDENTIFIERS\n"
                    "Entity type: PERSON\n"
                    "Name: Carmine Salamone\n"
                    "Email: carmine@cnit.it\n"
                    "Phone: +393395040816\n"
                    "\n"
                    "#ABOUT\nFrom email signature.\n"
                ),
            )
        )
    storage.add_person_identifiers(
        owner,
        pre_blob_id,
        [("email", "carmine@cnit.it"), ("phone", "+393395040816")],
    )

    # Now arrive a WhatsApp message from the same phone.
    wa_id = _make_wa_message(owner=owner, text="Mario, ricordi del corso? Aspetto risposta.")

    # The LLM merge will be asked to merge the new WA-derived entity
    # with the existing blob's content. Return a "merged" string so the
    # worker takes the merge branch rather than insert.
    merged_content = (
        "#IDENTIFIERS\n"
        "Entity type: PERSON\n"
        "Name: Carmine Salamone\n"
        "Email: carmine@cnit.it\n"
        "Phone: +393395040816\n"
        "\n"
        "#ABOUT\nFrom email signature.\n"
        "\n"
        "#HISTORY\nNow also reachable via WhatsApp."
    )
    worker = _make_worker(owner, llm_merge_returns=[merged_content])

    extracted = (
        "#IDENTIFIERS\n"
        "Entity type: PERSON\n"
        "Name: Carmine Salamone\n"
        "Phone: +393395040816\n"
        "\n"
        "#ABOUT\nWhatsApp follow-up about the course.\n"
        "\n"
        "#HISTORY\nMessage on 2026-05-08."
    )
    worker._extract_entities_for_message.return_value = [extracted]

    ok = await worker.process_whatsapp_message(
        {
            "id": wa_id,
            "text": "Mario, ricordi del corso? Aspetto risposta.",
            "sender_jid": "393395040816@s.whatsapp.net",
            "sender_name": "Carmine",
            "timestamp": "2026-05-08T11:00:00+00:00",
            "is_from_me": False,
            "is_group": False,
        }
    )
    assert ok is True

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


@pytest.mark.asyncio
async def test_process_whatsapp_skips_short_text_but_marks_processed(fresh_db):
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob, WhatsAppBlob, WhatsAppMessage

    owner = "alice@example.com"
    wa_id = _make_wa_message(owner=owner, text="ok")

    worker = _make_worker(owner, llm_merge_returns=[])
    worker._extract_entities_for_message.return_value = []  # would never be called

    ok = await worker.process_whatsapp_message(
        {
            "id": wa_id,
            "text": "ok",
            "sender_jid": "393395040816@s.whatsapp.net",
            "sender_name": "Carmine",
            "timestamp": "2026-05-08T10:11:12+00:00",
            "is_from_me": False,
            "is_group": False,
        }
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


@pytest.mark.asyncio
async def test_process_whatsapp_marks_processed_when_extractor_returns_empty(fresh_db):
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob, WhatsAppMessage

    owner = "alice@example.com"
    wa_id = _make_wa_message(
        owner=owner, text="Some long enough message that the worker will try to extract from."
    )

    worker = _make_worker(owner, llm_merge_returns=[])
    worker._extract_entities_for_message.return_value = []  # LLM said SKIP

    ok = await worker.process_whatsapp_message(
        {
            "id": wa_id,
            "text": "Some long enough message that the worker will try to extract from.",
            "sender_jid": "393395040816@s.whatsapp.net",
            "sender_name": "Carmine",
            "timestamp": "2026-05-08T10:11:12+00:00",
            "is_from_me": False,
            "is_group": False,
        }
    )
    assert ok is True

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
            "sender_jid": "393395040816@s.whatsapp.net",
            "sender_name": "Carmine",
            "timestamp": "2026-05-08T10:11:12+00:00",
            "text": "Ciao Mario, ricordi del corso?",
        }
    )
    assert "Channel: WhatsApp" in out
    assert "Carmine" in out
    assert "+393395040816" in out
    assert "Group: (1-on-1)" in out
    assert "Phone: +393395040816" in out
    assert "Ciao Mario, ricordi del corso?" in out
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
        phone="+393395040816",
        name="Carmine Salamone",
    )

    worker = _make_envelope_worker(owner)
    out = worker._format_whatsapp_data(
        {
            "sender_jid": "185800503328844@lid",
            "sender_name": "",  # the contact lookup fills this in
            "timestamp": "2026-05-08T10:11:12+00:00",
            "text": "Ciao Mario, sentiamoci per il corso.",
        }
    )
    assert "Channel: WhatsApp" in out
    # Resolved name appears in the From line, not the bare jid
    assert "Carmine Salamone" in out
    assert "+393395040816" in out
    # Both Phone: AND LID: lines emitted — Phase 1 indexes both
    assert "Phone: +393395040816" in out
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
    assert _normalise_phone("+393395040816") == "+393395040816"
    assert _normalise_phone("00393395040816") == "+393395040816"


def test_parse_identifiers_reroutes_lid_in_phone_field_to_lid_kind():
    """If the LLM mislabels a LID as a Phone:, the parser routes it to
    the LID kind anyway so Phase 1's identifier-first match still has
    a signal."""
    from zylch.workers.memory import _parse_identifiers_block

    block = (
        "#IDENTIFIERS\n"
        "Entity type: PERSON\n"
        "Name: Tania\n"
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
