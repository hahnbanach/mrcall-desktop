"""End-to-end tests for `TaskWorker._analyze_recent_whatsapp_events`
(whatsapp-pipeline-parity Fase 3b).

Locks the WhatsApp task path:

1. A WA message from a contact creates ONE task with
   ``channel='whatsapp'``, ``contact_phone`` populated, and
   ``sources.whatsapp_messages = [msg_id]``,
   ``sources.thread_id = chat_jid``.

2. A second WA message in the SAME chat (after the LLM picks UPDATE)
   does NOT create a duplicate — the existing task is updated and the
   new ``msg_id`` is appended to ``sources.whatsapp_messages``.

3. ``is_from_me=True`` after a contact's message → user_reply branch
   closes the open task without burning an LLM call.

4. Cross-channel: an existing email task whose ``sources.blobs``
   overlaps the blobs extracted from a new WA message gets the WA
   message appended onto it (UPDATE), not a brand-new task.

5. ``is_group=True`` messages are filtered out at the storage helper
   level — they never reach the worker.

The LLM call (`_analyze_event`) is mocked. Storage / hybrid_search are
real against the per-test SQLite fixture.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "tasks_wa.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))
    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield db_path
    db_mod.dispose_engine()


def _insert_wa_message(
    owner: str,
    *,
    text: str = "Ciao Mario, sono Carmine.",
    chat_jid: str = "393395040816@s.whatsapp.net",
    sender_jid: str | None = None,
    sender_name: str = "Carmine",
    is_from_me: bool = False,
    is_group: bool = False,
    timestamp: datetime | None = None,
) -> str:
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage

    row_id = str(uuid.uuid4())
    with get_session() as s:
        s.add(
            WhatsAppMessage(
                id=row_id,
                owner_id=owner,
                message_id=row_id,
                chat_jid=chat_jid,
                sender_jid=sender_jid or chat_jid,
                sender_name=sender_name,
                text=text,
                timestamp=timestamp or datetime.now(timezone.utc),
                is_from_me=is_from_me,
                is_group=is_group,
            )
        )
    return row_id


def _make_worker(owner: str, *, analyze_returns: list):
    """Build a TaskWorker with the LLM call short-circuited.

    `make_llm_client` and `hybrid_search` are mocked; storage is real.
    `_get_task_prompt` returns a fake non-empty string so the worker
    doesn't bail in the "no prompt" branch. `_analyze_event` is replaced
    by an AsyncMock that returns the next dict from `analyze_returns` on
    each call.
    """
    from zylch.workers import task_creation as tc_mod

    fake_client = MagicMock()
    with patch.object(tc_mod, "make_llm_client", return_value=fake_client):
        worker = tc_mod.TaskWorker(
            storage=__import__("zylch.storage", fromlist=["Storage"]).Storage(),
            owner_id=owner,
            user_email="alice@example.com",
        )

    worker._task_prompt = "FAKE TASK PROMPT"
    worker._task_prompt_loaded = True

    # Stub hybrid_search.search → empty so `_get_blob_for_contact` returns
    # ("(no prior context)", None) and tests don't depend on the embedding
    # backend.
    worker.hybrid_search = MagicMock()
    worker.hybrid_search.search.return_value = []

    # Each WA chat winner gets one call. Pop in order.
    worker._analyze_event = AsyncMock(side_effect=list(analyze_returns))
    return worker


def _decision(
    *,
    action: str = "create",
    target_task_id: str | None = None,
    urgency: str = "medium",
    suggested: str = "Reply to Carmine about the course.",
    reason: str = "Carmine pinged via WhatsApp and is waiting for a reply on the safety course logistics.",
    action_required: bool = True,
) -> dict:
    return {
        "action_required": action_required,
        "task_action": action,
        "target_task_id": target_task_id,
        "urgency": urgency,
        "suggested_action": suggested,
        "reason": reason,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------
# 1) Single WA message → ONE task channel=whatsapp
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_wa_message_creates_whatsapp_task(fresh_db):
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem, WhatsAppMessage

    owner = "alice@example.com"
    msg_id = _insert_wa_message(owner)

    worker = _make_worker(owner, analyze_returns=[_decision(action="create")])
    await worker._analyze_recent_whatsapp_events()

    with get_session() as s:
        tasks = s.query(TaskItem).filter(TaskItem.owner_id == owner).all()
    assert len(tasks) == 1
    t = tasks[0]
    assert t.channel == "whatsapp"
    assert t.event_type == "whatsapp"
    assert t.contact_phone == "+393395040816"
    assert t.contact_email == ""  # explicitly empty for WA tasks
    assert (t.sources or {}).get("whatsapp_messages") == [msg_id]
    assert (t.sources or {}).get("emails") == []
    assert (t.sources or {}).get("thread_id") == "393395040816@s.whatsapp.net"
    # Fase 4 cross-channel: explicit chat_jid pointer for the renderer
    # toggle (here equals thread_id since this is a WA-only task).
    assert (
        (t.sources or {}).get("whatsapp_chat_jid") == "393395040816@s.whatsapp.net"
    )

    # watermark advanced — message no longer unprocessed
    with get_session() as s:
        row = s.query(WhatsAppMessage).filter(WhatsAppMessage.id == msg_id).one()
    assert row.task_processed_at is not None


# ---------------------------------------------------------------------
# 2) Second WA in same chat → UPDATE, no duplicate
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_wa_message_updates_existing_task(fresh_db):
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem

    owner = "alice@example.com"
    _insert_wa_message(owner, text="Primo messaggio")

    # Round 1 — LLM says CREATE.
    worker = _make_worker(owner, analyze_returns=[_decision(action="create")])
    await worker._analyze_recent_whatsapp_events()

    with get_session() as s:
        task = s.query(TaskItem).filter(TaskItem.owner_id == owner).one()
        existing_id = task.id

    # Round 2 — new message in same chat. LLM picks UPDATE on the same task.
    msg2 = _insert_wa_message(owner, text="Allora, ci aggiorniamo?")
    worker2 = _make_worker(
        owner,
        analyze_returns=[_decision(action="update", target_task_id=existing_id)],
    )
    await worker2._analyze_recent_whatsapp_events()

    with get_session() as s:
        tasks = s.query(TaskItem).filter(TaskItem.owner_id == owner).all()
    assert len(tasks) == 1  # no duplicate
    sources = tasks[0].sources or {}
    assert msg2 in (sources.get("whatsapp_messages") or [])
    assert len(sources.get("whatsapp_messages") or []) == 2


# ---------------------------------------------------------------------
# 3) is_from_me=True after contact's message → user_reply close
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_from_me_after_contact_closes_task(fresh_db):
    """The user replied on WhatsApp AFTER the contact's message — the
    open task on the chat must be auto-closed, no LLM call."""
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem

    owner = "alice@example.com"

    # Round 1 — contact's incoming message creates a task.
    earlier = datetime.now(timezone.utc).replace(microsecond=0)
    contact_ts = earlier
    _insert_wa_message(owner, text="Ciao Mario, novità?", timestamp=contact_ts)

    worker = _make_worker(owner, analyze_returns=[_decision(action="create")])
    await worker._analyze_recent_whatsapp_events()

    with get_session() as s:
        tasks = s.query(TaskItem).filter(TaskItem.owner_id == owner).all()
    assert len(tasks) == 1
    assert tasks[0].completed_at is None

    # Round 2 — user replies on WhatsApp (is_from_me=True), AFTER the
    # contact's timestamp.
    later = datetime.now(timezone.utc).replace(microsecond=0)
    _insert_wa_message(
        owner,
        text="Sì certo, ti chiamo entro stasera.",
        is_from_me=True,
        timestamp=later,
    )

    # No LLM should be called for the user_reply branch — analyze_returns
    # is empty AsyncMock with no side_effect list. We pre-fill the worker
    # with one decision and assert it's NOT consumed.
    worker2 = _make_worker(owner, analyze_returns=[_decision(action="none")])
    await worker2._analyze_recent_whatsapp_events()

    with get_session() as s:
        task = s.query(TaskItem).filter(TaskItem.owner_id == owner).one()
    assert task.completed_at is not None  # closed
    # _analyze_event should NOT have been called for this round.
    assert worker2._analyze_event.call_count == 0


# ---------------------------------------------------------------------
# 4) Cross-channel — WA hits same blob as a pre-existing email task → UPDATE
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_channel_wa_updates_existing_email_task(fresh_db):
    """An email task already references a memory blob about Carmine.
    A new WA message from Carmine extracts into the SAME blob (Phase 1b
    identifier match — simulated here by linking the blob to the WA
    message directly via whatsapp_blobs, since we're not running the
    memory worker in this test). F7 topical lookup finds the existing
    email task → LLM picks UPDATE → both channels coexist on the SAME
    task."""
    from zylch.storage.database import get_session
    from zylch.storage.models import Blob, TaskItem
    from zylch.storage.storage import Storage

    owner = "alice@example.com"
    storage = Storage()

    # Pre-existing memory blob for Carmine.
    blob_id = str(uuid.uuid4())
    with get_session() as s:
        s.add(
            Blob(
                id=blob_id,
                owner_id=owner,
                namespace=f"user:{owner}",
                content=(
                    "#IDENTIFIERS\nName: Carmine Salamone\nPhone: +393395040816\n"
                ),
            )
        )

    # Pre-existing email task that references the blob.
    email_event_id = "fake-email-" + uuid.uuid4().hex[:8]
    storage.store_task_item(
        owner,
        {
            "event_type": "email",
            "event_id": email_event_id,
            "contact_email": "carmine@cnit.it",
            "contact_name": "Carmine",
            "action_required": True,  # F7 lookup filters on this
            "urgency": "high",
            "suggested_action": "Reply to Carmine about CNIT course logistics.",
            "reason": "Original email from carmine@cnit.it asking about safety course.",
            "sources": {
                "emails": [email_event_id],
                "blobs": [blob_id],
                "calendar_events": [],
                "thread_id": "<email-thread@example.com>",
            },
        },
    )
    with get_session() as s:
        pre_task = s.query(TaskItem).filter(TaskItem.event_id == email_event_id).one()
        email_task_id = pre_task.id

    # New WA message. Link it to the same blob via whatsapp_blobs so F7
    # finds the existing email task.
    wa_id = _insert_wa_message(owner, text="Carmine: ti chiamo per il corso?")
    storage.add_whatsapp_blob_link(owner, wa_id, blob_id)

    # LLM picks UPDATE on the email task id.
    worker = _make_worker(
        owner,
        analyze_returns=[_decision(action="update", target_task_id=email_task_id)],
    )
    await worker._analyze_recent_whatsapp_events()

    with get_session() as s:
        tasks = s.query(TaskItem).filter(TaskItem.owner_id == owner).all()
    assert len(tasks) == 1  # still ONE task across both channels
    t = tasks[0]
    assert t.id == email_task_id
    sources = t.sources or {}
    assert wa_id in (sources.get("whatsapp_messages") or [])
    assert email_event_id in (sources.get("emails") or [])
    # Fase 4 cross-channel: chat_jid stamped by the WA touchpoint so
    # the renderer toggle can fetch the WhatsApp chat alongside the
    # original email thread.
    assert sources.get("whatsapp_chat_jid") == "393395040816@s.whatsapp.net"


# ---------------------------------------------------------------------
# 5) Group chats are filtered at storage level
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_chats_excluded(fresh_db):
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem

    owner = "alice@example.com"
    _insert_wa_message(owner, is_group=True, text="Riunione di lavoro")

    worker = _make_worker(owner, analyze_returns=[_decision(action="create")])
    await worker._analyze_recent_whatsapp_events()

    with get_session() as s:
        tasks = s.query(TaskItem).filter(TaskItem.owner_id == owner).all()
    assert tasks == []  # group filtered out, no LLM call, no task
    assert worker._analyze_event.call_count == 0


# ---------------------------------------------------------------------
# 6) Fix-D for WA chats — same-chat second message under CREATE is force-updated
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_on_same_chat_is_force_updated(fresh_db):
    """If the LLM says CREATE but the chat already has an open task,
    we mirror Fix-D and downgrade to UPDATE. (The standalone Fix-D
    test on the email side is in test_task_creation_f7_create_respect.py.)
    """
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem

    owner = "alice@example.com"
    _insert_wa_message(owner)

    worker1 = _make_worker(owner, analyze_returns=[_decision(action="create")])
    await worker1._analyze_recent_whatsapp_events()

    msg2 = _insert_wa_message(owner, text="Aggiornamento")
    # LLM mistakenly says CREATE again — Fix-D should force-update onto
    # the existing same-chat task.
    worker2 = _make_worker(owner, analyze_returns=[_decision(action="create")])
    await worker2._analyze_recent_whatsapp_events()

    with get_session() as s:
        tasks = s.query(TaskItem).filter(TaskItem.owner_id == owner).all()
    assert len(tasks) == 1
    sources = tasks[0].sources or {}
    assert msg2 in (sources.get("whatsapp_messages") or [])
