"""Tests for the whatsapp_blobs join table (whatsapp-pipeline-parity Phase 2a).

Phase 2a is additive: a new join table mirroring email_blobs / calendar_blobs
between WhatsAppMessage and Blob, plus the matching Storage helpers
(`add_whatsapp_blob_link`, `get_blobs_for_whatsapp_message`). A merge
keeps these rows: the consolidation MERGE commit re-creates a donor's links
on its keeper before CASCADE drops the donor's own
(`tests/memory/test_mnemonic_merge.py`).

Nothing reads or writes whatsapp_blobs yet — Phase 2c will. These tests
lock the contract.
"""

import uuid
from datetime import datetime, timezone

import pytest


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Per-test SQLite DB. Disposes the engine on teardown."""
    db_path = tmp_path / "wa_blobs_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))

    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield db_path
    db_mod.dispose_engine()


def _make_blob(owner_id: str, content: str = "dummy") -> str:
    from zylch.memory.company_key import current_company_key, entity_namespace
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob

    blob_id = str(uuid.uuid4())
    with get_session() as s:
        s.add(
            Blob(
                id=blob_id,
                owner_id=owner_id,
                namespace=entity_namespace(current_company_key()),
                content=content,
            )
        )
    return blob_id


def _make_wa_message(owner_id: str, message_id: str | None = None) -> str:
    """Insert a real WhatsAppMessage row so whatsapp_blobs FK is satisfied.
    Returns the row id (PK, distinct from message_id)."""
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage

    row_id = str(uuid.uuid4())
    with get_session() as s:
        s.add(
            WhatsAppMessage(
                id=row_id,
                owner_id=owner_id,
                message_id=message_id or row_id,
                chat_jid="393331234567@s.whatsapp.net",
                sender_jid="393331234567@s.whatsapp.net",
                sender_name="John",
                text="ciao",
                timestamp=datetime.now(timezone.utc),
            )
        )
    return row_id


# ---------------------------------------------------------------------
# add_whatsapp_blob_link — idempotency, owner isolation
# ---------------------------------------------------------------------


def test_add_whatsapp_blob_link_inserts_new_row(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    blob_id = _make_blob(owner)
    msg_id = _make_wa_message(owner)

    inserted = storage.add_whatsapp_blob_link(owner, msg_id, blob_id)
    assert inserted is True

    blobs = storage.get_blobs_for_whatsapp_message(owner, msg_id)
    assert blobs == [blob_id]


def test_add_whatsapp_blob_link_is_idempotent(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    blob_id = _make_blob(owner)
    msg_id = _make_wa_message(owner)

    assert storage.add_whatsapp_blob_link(owner, msg_id, blob_id) is True
    assert storage.add_whatsapp_blob_link(owner, msg_id, blob_id) is False

    blobs = storage.get_blobs_for_whatsapp_message(owner, msg_id)
    assert blobs == [blob_id]


def test_add_whatsapp_blob_link_skips_empty_inputs(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    blob_id = _make_blob(owner)
    msg_id = _make_wa_message(owner)

    assert storage.add_whatsapp_blob_link("", msg_id, blob_id) is False
    assert storage.add_whatsapp_blob_link(owner, "", blob_id) is False
    assert storage.add_whatsapp_blob_link(owner, msg_id, "") is False


def test_get_blobs_for_whatsapp_message_returns_multiple_blobs(fresh_db):
    """One WA message can extract multiple entities (PERSON + COMPANY)."""
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    blob_a = _make_blob(owner, content="PERSON")
    blob_b = _make_blob(owner, content="COMPANY")
    msg_id = _make_wa_message(owner)

    storage.add_whatsapp_blob_link(owner, msg_id, blob_a)
    storage.add_whatsapp_blob_link(owner, msg_id, blob_b)

    blobs = storage.get_blobs_for_whatsapp_message(owner, msg_id)
    assert set(blobs) == {blob_a, blob_b}


def test_get_blobs_for_whatsapp_message_is_company_scoped(fresh_db):
    """Link rows belong to the company (2026-09, shared memory): two
    accounts under one key see each other's links. A message id is a
    per-profile UUID, so in production an account only ever asks about
    its own messages; the wall that matters is the company key."""
    from zylch.storage.storage import Storage

    storage = Storage()
    blob_alice = _make_blob("alice@example.com")
    blob_bob = _make_blob("bob@example.com")
    msg_alice = _make_wa_message("alice@example.com")
    msg_bob = _make_wa_message("bob@example.com")

    storage.add_whatsapp_blob_link("alice@example.com", msg_alice, blob_alice)
    storage.add_whatsapp_blob_link("bob@example.com", msg_bob, blob_bob)

    assert storage.get_blobs_for_whatsapp_message("alice@example.com", msg_alice) == [blob_alice]
    assert storage.get_blobs_for_whatsapp_message("bob@example.com", msg_bob) == [blob_bob]
    assert storage.get_blobs_for_whatsapp_message("alice@example.com", msg_bob) == [blob_bob]


# ---------------------------------------------------------------------
# CASCADE behaviour — both sides
# ---------------------------------------------------------------------


def test_deleting_a_whatsapp_message_through_storage_removes_its_link(fresh_db):
    """The message side of the link has no ON DELETE CASCADE any more: since
    2026-09 `whatsapp_blobs` lives in the company memory store and
    `whatsapp_messages` in the profile file, and SQLite cannot enforce a
    foreign key across two files. The production delete path drops the
    link rows itself, and that is what this asserts (the blob side keeps
    its real, same-file cascade — see the next test)."""
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppBlob, WhatsAppMessage
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    blob_id = _make_blob(owner)
    msg_id = _make_wa_message(owner)
    storage.add_whatsapp_blob_link(owner, msg_id, blob_id)
    with get_session() as s:
        wa_message_id = (
            s.query(WhatsAppMessage.message_id).filter(WhatsAppMessage.id == msg_id).scalar()
        )

    assert storage.delete_whatsapp_message_by_message_id(owner, wa_message_id) == 1

    with get_session() as s:
        rows = s.query(WhatsAppBlob).filter(WhatsAppBlob.whatsapp_message_id == msg_id).all()
    assert rows == []


def test_cascade_delete_blob_removes_link(fresh_db):
    """ON DELETE CASCADE on blob_id — same guarantee email_blobs gives."""
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob, WhatsAppBlob
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    blob_id = _make_blob(owner)
    msg_id = _make_wa_message(owner)
    storage.add_whatsapp_blob_link(owner, msg_id, blob_id)

    with get_session() as s:
        s.query(Blob).filter(Blob.id == blob_id).delete()

    with get_session() as s:
        rows = s.query(WhatsAppBlob).filter(WhatsAppBlob.blob_id == blob_id).all()
    assert rows == []
