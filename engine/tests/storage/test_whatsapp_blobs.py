"""Tests for the whatsapp_blobs join table (whatsapp-pipeline-parity Phase 2a).

Phase 2a is additive: a new join table mirroring email_blobs / calendar_blobs
between WhatsAppMessage and Blob, plus the matching Storage helpers
(`add_whatsapp_blob_link`, `get_blobs_for_whatsapp_message`) and an
extension to `migrate_blob_references` so the Phase 1c reconsolidation
sweep doesn't drop these rows when CASCADE fires.

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
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob

    blob_id = str(uuid.uuid4())
    with get_session() as s:
        s.add(
            Blob(
                id=blob_id,
                owner_id=owner_id,
                namespace=f"user:{owner_id}",
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
                chat_jid="393395040816@s.whatsapp.net",
                sender_jid="393395040816@s.whatsapp.net",
                sender_name="Carmine",
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


def test_get_blobs_for_whatsapp_message_isolates_owners(fresh_db):
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
    assert storage.get_blobs_for_whatsapp_message("alice@example.com", msg_bob) == []


# ---------------------------------------------------------------------
# CASCADE behaviour — both sides
# ---------------------------------------------------------------------


def test_cascade_delete_whatsapp_message_removes_link(fresh_db):
    """ON DELETE CASCADE on whatsapp_message_id."""
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppBlob, WhatsAppMessage
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    blob_id = _make_blob(owner)
    msg_id = _make_wa_message(owner)
    storage.add_whatsapp_blob_link(owner, msg_id, blob_id)

    with get_session() as s:
        s.query(WhatsAppMessage).filter(WhatsAppMessage.id == msg_id).delete()

    with get_session() as s:
        rows = (
            s.query(WhatsAppBlob).filter(WhatsAppBlob.whatsapp_message_id == msg_id).all()
        )
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


# ---------------------------------------------------------------------
# migrate_blob_references — Phase 1c keeps WA links intact
# ---------------------------------------------------------------------


def test_migrate_whatsapp_blobs_to_keeper(fresh_db):
    """whatsapp_blobs(msg_id, dup) must become whatsapp_blobs(msg_id, keeper)."""
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppBlob
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    keeper = _make_blob(owner, content="KEEPER")
    dup = _make_blob(owner, content="DUP")

    msg_keeper = _make_wa_message(owner)
    msg_dup = _make_wa_message(owner)
    msg_shared = _make_wa_message(owner)

    storage.add_whatsapp_blob_link(owner, msg_keeper, keeper)
    storage.add_whatsapp_blob_link(owner, msg_shared, keeper)
    storage.add_whatsapp_blob_link(owner, msg_dup, dup)
    storage.add_whatsapp_blob_link(owner, msg_shared, dup)

    counts = storage.migrate_blob_references(owner_id=owner, dup_blob_id=dup, keeper_blob_id=keeper)
    # Only msg_dup is new on keeper; msg_shared already linked to keeper.
    assert counts["whatsapp_blobs_migrated"] == 1

    keeper_msgs = storage.get_blobs_for_whatsapp_message(owner, msg_dup)
    assert keeper in keeper_msgs

    # Sanity: dup's whatsapp_blobs rows still exist; CASCADE will drop
    # them when the blob is deleted.
    with get_session() as s:
        dup_links = (
            s.query(WhatsAppBlob.whatsapp_message_id)
            .filter(WhatsAppBlob.blob_id == dup, WhatsAppBlob.owner_id == owner)
            .all()
        )
    assert {str(r[0]) for r in dup_links} == {msg_dup, msg_shared}


def test_migrate_blob_references_reports_zero_when_no_wa_links(fresh_db):
    """Phase 2a is additive: existing migrate callers (no WA links) keep
    seeing 0 in the new key without breaking."""
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    keeper = _make_blob(owner)
    dup = _make_blob(owner)

    counts = storage.migrate_blob_references(owner_id=owner, dup_blob_id=dup, keeper_blob_id=keeper)
    assert counts["whatsapp_blobs_migrated"] == 0
    # Existing keys still present
    for key in (
        "person_identifiers_migrated",
        "email_blobs_migrated",
        "calendar_blobs_migrated",
        "task_items_updated",
    ):
        assert key in counts
