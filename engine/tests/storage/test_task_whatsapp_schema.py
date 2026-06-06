"""Schema + storage-helper tests for WhatsApp task processing
(whatsapp-pipeline-parity Fase 3a).

Phase 3a is purely additive:
- ``TaskItem.contact_phone`` column (nullable, indexed) — populated by
  the new WA task worker (Fase 3b/3c).
- ``_infer_task_channel`` learns ``event_type == 'whatsapp'`` →
  ``channel='whatsapp'``.
- New storage helpers:
  ``get_tasks_by_contact_phone``,
  ``get_unprocessed_whatsapp_messages_for_task``,
  ``mark_whatsapp_task_processed`` + bulk variant,
  ``update_task_item(add_source_whatsapp_message=…)``.
- ``reset_task_processing_timestamps`` gains a ``whatsapp`` channel.

These tests lock the contract before the worker side lands so behavior
changes there are isolated.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest


# ---------------------------------------------------------------------
# Per-test fresh SQLite DB (mirrors test_whatsapp_blobs.py)
# ---------------------------------------------------------------------


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "task_wa_schema.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))

    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield db_path
    db_mod.dispose_engine()


def _make_wa_message(
    owner_id: str,
    *,
    text: str = "ciao come va",
    is_group: bool = False,
    task_processed: bool = False,
    timestamp: datetime | None = None,
    chat_jid: str | None = None,
) -> str:
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage

    row_id = str(uuid.uuid4())
    with get_session() as s:
        s.add(
            WhatsAppMessage(
                id=row_id,
                owner_id=owner_id,
                message_id=row_id,
                chat_jid=chat_jid or "393395040816@s.whatsapp.net",
                sender_jid="393395040816@s.whatsapp.net",
                sender_name="Alessandro",
                text=text,
                timestamp=timestamp or datetime.now(timezone.utc),
                is_group=is_group,
                task_processed_at=datetime.now(timezone.utc) if task_processed else None,
            )
        )
    return row_id


# ---------------------------------------------------------------------
# Schema: TaskItem.contact_phone column + index
# ---------------------------------------------------------------------


def test_task_items_has_contact_phone_column(fresh_db):
    """ORM-driven create_all on a fresh DB ships contact_phone."""
    from zylch.storage.database import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(task_items)").fetchall()
    cols = {r[1] for r in rows}
    assert "contact_phone" in cols, "contact_phone column missing on fresh DB"
    assert "channel" in cols  # pre-existing 3.2 column; sanity check


def test_task_items_has_contact_phone_index(fresh_db):
    """Index ix_task_items_contact_phone is created for fresh DBs by
    SQLAlchemy's create_all (via index=True on the column) AND is
    ensured by _apply_column_migrations for legacy DBs."""
    from zylch.storage.database import get_engine

    engine = get_engine()
    with engine.begin() as conn:
        rows = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='task_items'"
        ).fetchall()
    names = {r[0] for r in rows}
    assert "ix_task_items_contact_phone" in names


def test_legacy_db_gets_contact_phone_via_migration(tmp_path, monkeypatch):
    """If a DB was created BEFORE the Phase 3a model change (no
    contact_phone column), init_db must idempotently ALTER it in via
    _apply_column_migrations and CREATE INDEX IF NOT EXISTS the matching
    index. We simulate by dropping the column post-init and reinitialising.
    """
    db_path = tmp_path / "legacy.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))

    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()

    # Simulate the pre-3a state: drop contact_phone + its index.
    engine = db_mod.get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP INDEX IF EXISTS ix_task_items_contact_phone")
        # SQLite doesn't support DROP COLUMN on older versions but Python's
        # bundled SQLite 3.35+ does. ALTER TABLE … DROP COLUMN works since
        # 3.35 (Apr 2021) which all supported Python builds carry.
        conn.exec_driver_sql("ALTER TABLE task_items DROP COLUMN contact_phone")
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(task_items)").fetchall()}
        assert "contact_phone" not in cols  # confirm we successfully simulated legacy

    # Re-run init_db → migration should re-add the column + the index.
    db_mod.dispose_engine()
    db_mod.init_db()

    engine = db_mod.get_engine()
    with engine.begin() as conn:
        cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(task_items)").fetchall()}
        idx_names = {
            r[0]
            for r in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND tbl_name='task_items'"
            ).fetchall()
        }
    assert "contact_phone" in cols, "migration did not add contact_phone back"
    assert "ix_task_items_contact_phone" in idx_names

    db_mod.dispose_engine()


def test_migration_is_idempotent(fresh_db):
    """init_db twice in a row must not raise (the migration step has to
    no-op on already-migrated DBs)."""
    from zylch.storage import database as db_mod

    db_mod.init_db()
    db_mod.init_db()  # second run is the actual test


# ---------------------------------------------------------------------
# _infer_task_channel: whatsapp branch
# ---------------------------------------------------------------------


def test_infer_channel_whatsapp_event_type():
    from zylch.storage.storage import _infer_task_channel

    assert (
        _infer_task_channel(contact_email="", event_type="whatsapp") == "whatsapp"
    )


def test_infer_channel_whatsapp_overrides_notification_contact():
    """Even if a future code path passes a notification@*mrcall* contact
    with event_type='whatsapp' (it shouldn't, but defensively): channel
    must be 'whatsapp' because event_type wins over the contact heuristic."""
    from zylch.storage.storage import _infer_task_channel

    assert (
        _infer_task_channel(
            contact_email="notification@transactional.mrcall.ai",
            event_type="whatsapp",
        )
        == "whatsapp"
    )


def test_infer_channel_email_when_event_type_unspecified():
    from zylch.storage.storage import _infer_task_channel

    assert _infer_task_channel(contact_email="alice@example.com", event_type="email") == "email"
    assert _infer_task_channel(contact_email="alice@example.com", event_type=None) == "email"


def test_infer_channel_phone_for_mrcall_notification():
    from zylch.storage.storage import _infer_task_channel

    assert (
        _infer_task_channel(
            contact_email="notification@transactional.mrcall.ai", event_type="email"
        )
        == "phone"
    )


def test_infer_channel_calendar_wins():
    from zylch.storage.storage import _infer_task_channel

    assert _infer_task_channel(contact_email="", event_type="calendar") == "calendar"


# ---------------------------------------------------------------------
# store_task_item writes contact_phone + auto-infers channel for WA
# ---------------------------------------------------------------------


def test_store_task_item_persists_contact_phone(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    msg_id = _make_wa_message(owner)

    ok = storage.store_task_item(
        owner,
        {
            "event_type": "whatsapp",
            "event_id": msg_id,
            "contact_email": "",
            "contact_phone": "+393395040816",
            "contact_name": "Alessandro",
            "urgency": "low",
            "suggested_action": "Reply.",
            "reason": "Pinged via WA.",
            "sources": {"whatsapp_messages": [msg_id]},
        },
    )
    assert ok

    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem

    with get_session() as s:
        row = (
            s.query(TaskItem)
            .filter(TaskItem.owner_id == owner, TaskItem.event_id == msg_id)
            .one()
        )
        assert row.contact_phone == "+393395040816"
        assert row.channel == "whatsapp"  # inferred from event_type
        assert row.contact_email == ""


def test_store_task_item_whitespace_phone_becomes_null(fresh_db):
    """Empty / whitespace-only contact_phone is stored as NULL so it
    doesn't pollute the F8 dedup-by-phone lookup."""
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"

    ok = storage.store_task_item(
        owner,
        {
            "event_type": "email",
            "event_id": "fakeemail-" + uuid.uuid4().hex[:8],
            "contact_email": "bob@example.com",
            "contact_phone": "   ",
            "urgency": "low",
            "suggested_action": "x",
            "reason": "y",
            "sources": {"emails": ["fake"]},
        },
    )
    assert ok

    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem

    with get_session() as s:
        row = s.query(TaskItem).filter(TaskItem.owner_id == owner).one()
        assert row.contact_phone is None


# ---------------------------------------------------------------------
# get_tasks_by_contact_phone
# ---------------------------------------------------------------------


def _insert_task(
    owner: str,
    *,
    event_id: str | None = None,
    contact_phone: str | None = None,
    contact_email: str = "",
    completed: bool = False,
    event_type: str = "whatsapp",
) -> str:
    from zylch.storage.storage import Storage

    storage = Storage()
    eid = event_id or uuid.uuid4().hex
    storage.store_task_item(
        owner,
        {
            "event_type": event_type,
            "event_id": eid,
            "contact_email": contact_email,
            "contact_phone": contact_phone,
            "urgency": "low",
            "suggested_action": "x",
            "reason": "y",
            "sources": {},
        },
    )
    if completed:
        from zylch.storage.database import get_session
        from zylch.storage.models import TaskItem

        with get_session() as s:
            s.query(TaskItem).filter(
                TaskItem.owner_id == owner, TaskItem.event_id == eid
            ).update({"completed_at": datetime.now(timezone.utc)})
    return eid


def test_get_tasks_by_contact_phone_empty_input(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    assert storage.get_tasks_by_contact_phone("alice", "") == []
    assert storage.get_tasks_by_contact_phone("alice", "   ") == []


def test_get_tasks_by_contact_phone_returns_open_plural(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    e1 = _insert_task(owner, contact_phone="+393395040816")
    e2 = _insert_task(owner, contact_phone="+393395040816")
    _insert_task(owner, contact_phone="+390000000000")  # different phone
    _insert_task(owner, contact_phone="+393395040816", completed=True)

    out = storage.get_tasks_by_contact_phone(owner, "+393395040816")
    event_ids = {r["event_id"] for r in out}
    assert event_ids == {e1, e2}


def test_get_tasks_by_contact_phone_strips_input_whitespace(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    _insert_task(owner, contact_phone="+393395040816")

    out = storage.get_tasks_by_contact_phone(owner, "  +393395040816  ")
    assert len(out) == 1


def test_get_tasks_by_contact_phone_isolates_owner(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    _insert_task("alice", contact_phone="+393395040816")
    _insert_task("bob", contact_phone="+393395040816")

    out = storage.get_tasks_by_contact_phone("alice", "+393395040816")
    assert len(out) == 1


# ---------------------------------------------------------------------
# get_unprocessed_whatsapp_messages_for_task
# ---------------------------------------------------------------------


def test_get_unprocessed_wa_for_task_filters_group_and_processed(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    new_id = _make_wa_message(owner)
    _make_wa_message(owner, is_group=True)  # excluded: group
    _make_wa_message(owner, task_processed=True)  # excluded: already processed

    out = storage.get_unprocessed_whatsapp_messages_for_task(owner)
    ids = {r["id"] for r in out}
    assert ids == {new_id}


def test_get_unprocessed_wa_for_task_orders_desc(fresh_db):
    """Mirrors the email path (date_timestamp DESC) so the Phase-2 sort
    key in task_creation._collect keeps user_reply branches running
    AFTER the LLM branch for any given pair (a message and its sibling)."""
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    old = datetime.now(timezone.utc) - timedelta(days=2)
    new = datetime.now(timezone.utc) - timedelta(hours=1)
    old_id = _make_wa_message(owner, timestamp=old)
    new_id = _make_wa_message(owner, timestamp=new)

    out = storage.get_unprocessed_whatsapp_messages_for_task(owner)
    assert [r["id"] for r in out] == [new_id, old_id]


def test_get_unprocessed_wa_for_task_isolates_owner(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    _make_wa_message("alice")
    _make_wa_message("bob")

    assert len(storage.get_unprocessed_whatsapp_messages_for_task("alice")) == 1


# ---------------------------------------------------------------------
# mark_whatsapp_task_processed + bulk variant
# ---------------------------------------------------------------------


def test_mark_whatsapp_task_processed_stamps_watermark(fresh_db):
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    msg = _make_wa_message(owner)

    storage.mark_whatsapp_task_processed(owner, msg)

    with get_session() as s:
        row = s.query(WhatsAppMessage).filter(WhatsAppMessage.id == msg).one()
        assert row.task_processed_at is not None


def test_mark_whatsapp_task_processed_removes_from_unprocessed_list(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    msg = _make_wa_message(owner)

    assert len(storage.get_unprocessed_whatsapp_messages_for_task(owner)) == 1
    storage.mark_whatsapp_task_processed(owner, msg)
    assert storage.get_unprocessed_whatsapp_messages_for_task(owner) == []


def test_bulk_mark_whatsapp_task_processed_empty_is_noop(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    # Should not raise on an empty input list.
    storage.mark_whatsapp_messages_task_processed("alice", [])


def test_bulk_mark_whatsapp_task_processed_stamps_all(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    ids = [_make_wa_message(owner) for _ in range(3)]

    storage.mark_whatsapp_messages_task_processed(owner, ids)
    assert storage.get_unprocessed_whatsapp_messages_for_task(owner) == []


# ---------------------------------------------------------------------
# update_task_item: add_source_whatsapp_message
# ---------------------------------------------------------------------


def test_update_task_item_appends_whatsapp_message(fresh_db):
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    eid = _insert_task(owner, contact_phone="+393395040816", event_type="whatsapp")

    # Resolve the task PK to call update_task_item.
    with get_session() as s:
        row = s.query(TaskItem).filter(TaskItem.event_id == eid).one()
        task_id = row.id

    storage.update_task_item(
        owner,
        task_id,
        add_source_whatsapp_message="some-other-wa-msg-id",
        suggested_action="updated",
    )

    with get_session() as s:
        row = s.query(TaskItem).filter(TaskItem.id == task_id).one()
        assert row.sources.get("whatsapp_messages") == ["some-other-wa-msg-id"]
        assert row.suggested_action == "updated"


def test_update_task_item_whatsapp_dedup(fresh_db):
    """Same WA message id appended twice must not produce a duplicate."""
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    eid = _insert_task(owner, contact_phone="+391", event_type="whatsapp")

    with get_session() as s:
        task_id = s.query(TaskItem).filter(TaskItem.event_id == eid).one().id

    storage.update_task_item(owner, task_id, add_source_whatsapp_message="wa-1")
    storage.update_task_item(owner, task_id, add_source_whatsapp_message="wa-1")

    with get_session() as s:
        row = s.query(TaskItem).filter(TaskItem.id == task_id).one()
        assert row.sources.get("whatsapp_messages") == ["wa-1"]


def test_update_task_item_email_and_whatsapp_coexist(fresh_db):
    """Cross-channel task: starts as email, gets a WA touchpoint appended.
    Sources end up carrying BOTH lists."""
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    eid = _insert_task(
        owner, contact_email="contact@example.com", event_type="email", contact_phone=None
    )

    with get_session() as s:
        task_id = s.query(TaskItem).filter(TaskItem.event_id == eid).one().id

    storage.update_task_item(owner, task_id, add_source_email="email-2")
    storage.update_task_item(owner, task_id, add_source_whatsapp_message="wa-7")

    with get_session() as s:
        row = s.query(TaskItem).filter(TaskItem.id == task_id).one()
        assert row.sources.get("emails") == ["email-2"]
        assert row.sources.get("whatsapp_messages") == ["wa-7"]


# ---------------------------------------------------------------------
# Fase 4 cross-channel: sources.whatsapp_chat_jid stamping
# ---------------------------------------------------------------------


def test_update_task_item_stamps_whatsapp_chat_jid_on_first_touchpoint(fresh_db):
    """Fase 4: the first WA touchpoint added to an existing email task
    stamps `sources.whatsapp_chat_jid` so the renderer's cross-channel
    toggle knows which chat to fetch."""
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    eid = _insert_task(owner, contact_email="contact@example.com", event_type="email")

    with get_session() as s:
        task_id = s.query(TaskItem).filter(TaskItem.event_id == eid).one().id

    storage.update_task_item(
        owner,
        task_id,
        add_source_whatsapp_message="wa-1",
        whatsapp_chat_jid="393395040816@s.whatsapp.net",
    )

    with get_session() as s:
        row = s.query(TaskItem).filter(TaskItem.id == task_id).one()
        assert row.sources.get("whatsapp_chat_jid") == "393395040816@s.whatsapp.net"
        assert row.sources.get("whatsapp_messages") == ["wa-1"]


def test_update_task_item_does_not_overwrite_existing_chat_jid(fresh_db):
    """Fase 4: a second WA touchpoint on the same task must NOT
    overwrite the chat_jid stamped by the first. (Defensive in case a
    cross-blob match surfaces a WA message from a different chat — the
    renderer toggle opens the first chat we associated; everything else
    is reachable via the WA tab.)"""
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    eid = _insert_task(owner, contact_email="contact@example.com", event_type="email")

    with get_session() as s:
        task_id = s.query(TaskItem).filter(TaskItem.event_id == eid).one().id

    storage.update_task_item(
        owner,
        task_id,
        add_source_whatsapp_message="wa-1",
        whatsapp_chat_jid="393395040816@s.whatsapp.net",
    )
    storage.update_task_item(
        owner,
        task_id,
        add_source_whatsapp_message="wa-2",
        whatsapp_chat_jid="999999999999@s.whatsapp.net",  # different chat
    )

    with get_session() as s:
        row = s.query(TaskItem).filter(TaskItem.id == task_id).one()
        # Original chat_jid preserved.
        assert row.sources.get("whatsapp_chat_jid") == "393395040816@s.whatsapp.net"
        # Both messages accumulated.
        assert row.sources.get("whatsapp_messages") == ["wa-1", "wa-2"]


def test_update_task_item_whatsapp_chat_jid_only_with_a_message(fresh_db):
    """If the caller passes `whatsapp_chat_jid` without an
    `add_source_whatsapp_message`, the chat_jid is NOT stamped — the
    field only makes sense as a marker that at least one WA message is
    associated with the task."""
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    eid = _insert_task(owner, contact_email="contact@example.com", event_type="email")

    with get_session() as s:
        task_id = s.query(TaskItem).filter(TaskItem.event_id == eid).one().id

    storage.update_task_item(
        owner,
        task_id,
        whatsapp_chat_jid="393395040816@s.whatsapp.net",
        urgency="high",
    )

    with get_session() as s:
        row = s.query(TaskItem).filter(TaskItem.id == task_id).one()
        assert row.sources.get("whatsapp_chat_jid") is None
        assert row.urgency == "high"


# ---------------------------------------------------------------------
# reset_task_processing_timestamps gains whatsapp
# ---------------------------------------------------------------------


def test_reset_task_timestamps_whatsapp_only(fresh_db):
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    m = _make_wa_message(owner, task_processed=True)

    counts = storage.reset_task_processing_timestamps(owner, channel="whatsapp")
    assert counts.get("whatsapp_messages") == 1

    with get_session() as s:
        row = s.query(WhatsAppMessage).filter(WhatsAppMessage.id == m).one()
        assert row.task_processed_at is None


def test_reset_task_timestamps_all_includes_whatsapp(fresh_db):
    from zylch.storage.storage import Storage

    storage = Storage()
    owner = "alice@example.com"
    _make_wa_message(owner, task_processed=True)

    counts = storage.reset_task_processing_timestamps(owner, channel="all")
    assert counts.get("whatsapp_messages") == 1
