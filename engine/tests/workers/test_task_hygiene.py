"""Backlog-correctness regression tests (support-llm-cost-fix / P2).

Three separate bugs let the unprocessed-email backlog grow silently on
the support@ daemon; this file locks the fix for each:

1. **Auto-ack sink** — a user-authored auto-reply that is the ONLY
   unprocessed email in its thread was never marked task-processed, so
   it was re-fetched every tick forever. Covered on BOTH paths:
   - the grouping-loop fix in ``analyze_recent_email_events`` (runs at
     analysis time, needs the LLM up), and
   - the ``run_task_backlog_hygiene`` stage (runs with the LLM down).

2. **Silent task loss on LLM failure** — a failed ``_analyze_event``
   used to mark the whole thread processed anyway; the email never got
   retried and never produced a task. The fix leaves the thread
   UNPROCESSED and retries next tick.

3. **Unbounded retry** — the hygiene stage marks anything older than
   ``TASK_BACKLOG_MAX_AGE_DAYS`` (read LIVE from ``os.environ``) so the
   no-mark-on-failure change can't turn into an infinite retry loop.

Storage is REAL against a per-test SQLite fixture (``fresh_db``); only
the LLM call (``_analyze_event``) is mocked — no key, no spend.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zylch.workers.task_creation_email import analyze_recent_email_events
from zylch.workers.task_hygiene import run_task_backlog_hygiene


# ---------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "hygiene.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))
    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield db_path
    db_mod.dispose_engine()


def _store():
    from zylch.storage import Storage

    return Storage()


def _insert_email(
    owner: str,
    *,
    from_email: str,
    email_id: str | None = None,
    thread_id: str | None = None,
    is_auto_reply: bool = False,
    age_days: float = 0.0,
    with_timestamp: bool = True,
    subject: str = "Hello",
    body: str = "Some actionable body text worth a task.",
    to_email: str = "alice@example.com",
) -> str:
    """Insert one email row and return its id.

    ``age_days`` sets both ``date`` and (when ``with_timestamp``)
    ``date_timestamp`` that many days in the past. ``with_timestamp=False``
    leaves ``date_timestamp`` NULL so the hygiene age check must fall back
    to parsing the ISO ``date`` string.
    """
    from zylch.storage.database import get_session
    from zylch.storage.models import Email

    eid = email_id or str(uuid.uuid4())
    when = datetime.now(timezone.utc) - timedelta(days=age_days)
    with get_session() as s:
        s.add(
            Email(
                id=eid,
                owner_id=owner,
                gmail_id=eid,
                thread_id=thread_id or eid,
                from_email=from_email,
                from_name="",
                to_email=to_email,
                subject=subject,
                date=when,
                date_timestamp=(int(when.timestamp()) if with_timestamp else None),
                body_plain=body,
                snippet=body[:60],
                is_auto_reply=is_auto_reply,
                has_attachments=False,
            )
        )
    return eid


def _task_processed_at(owner: str, email_id: str):
    from zylch.storage.database import get_session
    from zylch.storage.models import Email

    with get_session() as s:
        row = s.query(Email).filter(Email.owner_id == owner, Email.id == email_id).one()
        return row.task_processed_at


def _make_email_worker(owner: str, user_email: str, analyze_returns: list):
    """Real TaskWorker with the LLM call short-circuited (mirror of the
    builder in test_tasks_whatsapp)."""
    from zylch.storage import Storage
    from zylch.workers import task_creation as tc_mod

    with patch.object(tc_mod, "make_llm_client", return_value=MagicMock()):
        worker = tc_mod.TaskWorker(
            storage=Storage(),
            owner_id=owner,
            user_email=user_email,
        )
    worker._task_prompt = "FAKE TASK PROMPT"
    worker._task_prompt_loaded = True
    worker.hybrid_search = MagicMock()
    worker.hybrid_search.search.return_value = []
    worker._analyze_event = AsyncMock(side_effect=list(analyze_returns))
    return worker


def _decision(action: str = "create") -> dict:
    return {
        "action_required": True,
        "task_action": action,
        "target_task_id": None,
        "urgency": "medium",
        "suggested_action": "Reply to the customer about their request.",
        "reason": "Customer is waiting for a reply.",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }


# =====================================================================
# 1) Hygiene stage — rules + rule order + live env read
# =====================================================================


def test_hygiene_marks_user_authored_auto_reply(fresh_db, monkeypatch, caplog):
    monkeypatch.setenv("EMAIL_ADDRESS", "support@mrcall.ai")
    owner = "owner-a"
    eid = _insert_email(owner, from_email="support@mrcall.ai", is_auto_reply=True, age_days=30)

    with caplog.at_level(logging.INFO, logger="zylch.workers.task_hygiene"):
        result = run_task_backlog_hygiene(owner, _store())

    assert result == {"auto_ack_marked": 1, "expired_marked": 0}
    assert _task_processed_at(owner, eid) is not None
    assert "never analyzable" in caplog.text


def test_hygiene_expires_old_contact_row_with_warning(fresh_db, monkeypatch, caplog):
    monkeypatch.setenv("EMAIL_ADDRESS", "support@mrcall.ai")
    owner = "owner-b"
    eid = _insert_email(owner, from_email="info@labaitacase.com", is_auto_reply=False, age_days=20)

    with caplog.at_level(logging.WARNING, logger="zylch.workers.task_hygiene"):
        result = run_task_backlog_hygiene(owner, _store())

    assert result == {"auto_ack_marked": 0, "expired_marked": 1}
    assert _task_processed_at(owner, eid) is not None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("expired unanalyzed" in r.getMessage() for r in warnings)


def test_hygiene_leaves_recent_contact_row_untouched(fresh_db, monkeypatch):
    monkeypatch.setenv("EMAIL_ADDRESS", "support@mrcall.ai")
    owner = "owner-c"
    eid = _insert_email(owner, from_email="eva@fanimotors.it", is_auto_reply=False, age_days=2)

    result = run_task_backlog_hygiene(owner, _store())

    assert result == {"auto_ack_marked": 0, "expired_marked": 0}
    assert _task_processed_at(owner, eid) is None


def test_hygiene_rule_order_user_auto_and_expired_counts_as_auto_ack(fresh_db, monkeypatch, caplog):
    """A row that is BOTH a user-auto reply AND older than the cap must
    be counted as auto_ack — the auto-ack rule is checked first — and it
    must NOT emit the 'expired' warning. This is the 2026-06 sink case:
    support@'s own auto-acks are 20-30 days old."""
    monkeypatch.setenv("EMAIL_ADDRESS", "support@mrcall.ai")
    owner = "owner-d"
    eid = _insert_email(owner, from_email="support@mrcall.ai", is_auto_reply=True, age_days=24)

    with caplog.at_level(logging.INFO, logger="zylch.workers.task_hygiene"):
        result = run_task_backlog_hygiene(owner, _store())

    assert result == {"auto_ack_marked": 1, "expired_marked": 0}
    assert _task_processed_at(owner, eid) is not None
    assert "never analyzable" in caplog.text
    assert "expired unanalyzed" not in caplog.text  # NOT the expiry path


def test_hygiene_reads_max_age_live_from_environ(fresh_db, monkeypatch):
    """Changing TASK_BACKLOG_MAX_AGE_DAYS in os.environ mid-run changes
    the verdict, with no restart / no re-import."""
    monkeypatch.setenv("EMAIL_ADDRESS", "support@mrcall.ai")
    owner = "owner-e"
    eid = _insert_email(owner, from_email="info@labaitacase.com", is_auto_reply=False, age_days=20)

    # cap = 30 → a 20-day row is NOT expired
    monkeypatch.setenv("TASK_BACKLOG_MAX_AGE_DAYS", "30")
    r1 = run_task_backlog_hygiene(owner, _store())
    assert r1 == {"auto_ack_marked": 0, "expired_marked": 0}
    assert _task_processed_at(owner, eid) is None

    # cap = 10 → now the same 20-day row IS expired
    monkeypatch.setenv("TASK_BACKLOG_MAX_AGE_DAYS", "10")
    r2 = run_task_backlog_hygiene(owner, _store())
    assert r2 == {"auto_ack_marked": 0, "expired_marked": 1}
    assert _task_processed_at(owner, eid) is not None


def test_hygiene_is_idempotent(fresh_db, monkeypatch):
    monkeypatch.setenv("EMAIL_ADDRESS", "support@mrcall.ai")
    owner = "owner-f"
    _insert_email(owner, from_email="support@mrcall.ai", is_auto_reply=True, age_days=25)

    first = run_task_backlog_hygiene(owner, _store())
    second = run_task_backlog_hygiene(owner, _store())

    assert first == {"auto_ack_marked": 1, "expired_marked": 0}
    assert second == {"auto_ack_marked": 0, "expired_marked": 0}  # nothing left pending


def test_hygiene_expiry_falls_back_to_iso_date_when_timestamp_null(fresh_db, monkeypatch):
    """date_timestamp is nullable; the age check must fall back to
    parsing the ISO ``date`` string."""
    monkeypatch.setenv("EMAIL_ADDRESS", "support@mrcall.ai")
    owner = "owner-g"
    eid = _insert_email(
        owner,
        from_email="info@labaitacase.com",
        is_auto_reply=False,
        age_days=20,
        with_timestamp=False,
    )

    result = run_task_backlog_hygiene(owner, _store())

    assert result == {"auto_ack_marked": 0, "expired_marked": 1}
    assert _task_processed_at(owner, eid) is not None


def test_hygiene_matches_user_via_email_aliases(fresh_db, monkeypatch):
    """A user-auto reply sent from a secondary identity in EMAIL_ALIASES
    is still recognised as user-authored (auto-ack rule)."""
    monkeypatch.setenv("EMAIL_ADDRESS", "support@mrcall.ai")
    monkeypatch.setenv("EMAIL_ALIASES", "team@mrcall.ai, noreply@mrcall.ai")
    owner = "owner-h"
    eid = _insert_email(owner, from_email="team@mrcall.ai", is_auto_reply=True, age_days=1)

    result = run_task_backlog_hygiene(owner, _store())

    assert result == {"auto_ack_marked": 1, "expired_marked": 0}
    assert _task_processed_at(owner, eid) is not None


# =====================================================================
# 2) Sink — grouping-loop fix in analyze_recent_email_events
# =====================================================================


@pytest.mark.asyncio
async def test_grouping_loop_marks_lone_user_auto_reply(fresh_db, caplog):
    """The 2026-06 sink: a user-authored auto-reply that is the only
    unprocessed email in its thread is marked task-processed by the
    grouping loop WITHOUT any LLM call."""
    owner = "owner-sink"
    user = "support@mrcall.ai"
    eid = _insert_email(
        owner,
        from_email=user,
        thread_id="thread-sink",
        is_auto_reply=True,
        age_days=1,
    )
    worker = _make_email_worker(owner, user_email=user, analyze_returns=[])

    with caplog.at_level(logging.INFO, logger="zylch.workers.task_creation_email"):
        analyzed, action = await analyze_recent_email_events(worker)

    assert (analyzed, action) == (0, 0)
    assert _task_processed_at(owner, eid) is not None  # no longer re-fetched
    worker._analyze_event.assert_not_called()  # zero LLM spend
    assert "marked task-processed (never analyzable)" in caplog.text


# =====================================================================
# 3) No-mark-on-failure — Phase 2 result=None
# =====================================================================


@pytest.mark.asyncio
async def test_llm_failure_leaves_thread_unprocessed(fresh_db, caplog):
    """A failed _analyze_event (returns None) must leave the email
    UNPROCESSED so the next tick retries it — the opposite of the old
    silent-task-loss behaviour."""
    owner = "owner-fail"
    eid = _insert_email(
        owner,
        from_email="info@labaitacase.com",
        thread_id="thread-fail",
        is_auto_reply=False,
        age_days=1,
    )
    worker = _make_email_worker(owner, user_email="alice@example.com", analyze_returns=[None])

    with caplog.at_level(logging.WARNING, logger="zylch.workers.task_creation_email"):
        await analyze_recent_email_events(worker)

    assert _task_processed_at(owner, eid) is None  # left for retry
    assert any(
        "left unprocessed, will retry next tick" in r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING
    )


@pytest.mark.asyncio
async def test_llm_success_marks_thread_processed(fresh_db):
    """A successful analysis still marks the thread processed (unchanged
    behaviour) — proving the no-mark-on-failure change is scoped to the
    failure path only."""
    owner = "owner-ok"
    eid = _insert_email(
        owner,
        from_email="info@labaitacase.com",
        thread_id="thread-ok",
        is_auto_reply=False,
        age_days=1,
    )
    worker = _make_email_worker(
        owner, user_email="alice@example.com", analyze_returns=[_decision("create")]
    )

    await analyze_recent_email_events(worker)

    assert _task_processed_at(owner, eid) is not None
    worker._analyze_event.assert_awaited_once()
