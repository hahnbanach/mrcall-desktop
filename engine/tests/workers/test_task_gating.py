"""Event-gating regression tests (support-llm-cost-fix / P3).

Locks the T3 contract: a tick with no new information makes ZERO LLM
call attempts, while a real change re-arms the machinery within one
tick. Covers the open-set fingerprint (F8/F9 gate), the F4 activity
gate, the daily full pass, the FORCE_FULL_SWEEPS escape hatch, the
merge-canary policy, and — the headline — the idle pipeline path where
no LLM client may even be CONSTRUCTED.

Storage is REAL against a per-test SQLite fixture (``fresh_db``); the
sweep implementations and every LLM factory are mocked — no key, no
spend.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from zylch.storage.worker_state import get_state, set_state
from zylch.workers import merge_canary_gate as mcg
from zylch.workers.task_gating import (
    WS_KEY_DEDUP_FINGERPRINT,
    WS_KEY_LAST_FULL_SWEEP,
    WorkPlan,
    build_work_plan,
    daily_pass_due,
    f4_candidates,
    open_tasks_fingerprint,
    run_gated_sweeps,
    sweeps_due,
)

# ---------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "gating.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))
    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield db_path
    db_mod.dispose_engine()


def _store():
    from zylch.storage import Storage

    return Storage()


def _now():
    return datetime.now(timezone.utc)


def _insert_email(owner, *, thread_id, from_email, to_email="", cc_email="", ts=None):
    from zylch.storage.database import get_session
    from zylch.storage.models import Email

    eid = str(uuid.uuid4())
    when = ts or _now()
    with get_session() as s:
        s.add(
            Email(
                id=eid,
                owner_id=owner,
                gmail_id=eid,
                thread_id=thread_id,
                from_email=from_email,
                to_email=to_email,
                cc_email=cc_email,
                subject="s",
                date=when,
                date_timestamp=int(when.timestamp()),
                body_plain="b",
            )
        )
    return eid


def _insert_wa(owner, *, chat_jid, ts=None, memory_processed=False, task_processed=False):
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage

    mid = str(uuid.uuid4())
    when = ts or _now()
    with get_session() as s:
        s.add(
            WhatsAppMessage(
                id=mid,
                owner_id=owner,
                message_id=mid,
                chat_jid=chat_jid,
                sender_jid=chat_jid,
                text="hi",
                timestamp=when,
                is_from_me=False,
                is_group=False,
                memory_processed_at=(when if memory_processed else None),
                task_processed_at=(when if task_processed else None),
            )
        )
    return mid


def _insert_cal(owner, *, task_processed=False):
    from zylch.storage.database import get_session
    from zylch.storage.models import CalendarEvent

    cid = str(uuid.uuid4())
    when = _now()
    with get_session() as s:
        s.add(
            CalendarEvent(
                id=cid,
                owner_id=owner,
                google_event_id=cid,
                summary="Sync call",
                start_time=when,
                end_time=when,
                memory_processed_at=when,  # memory side already done
                task_processed_at=(when if task_processed else None),
            )
        )
    return cid


def _insert_task_row(owner, **overrides):
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem

    tid = overrides.pop("id", str(uuid.uuid4()))
    fields = {
        "id": tid,
        "owner_id": owner,
        "event_type": "email",
        "event_id": str(uuid.uuid4()),
        "action_required": True,
        "urgency": "medium",
        "suggested_action": "Reply",
        "reason": "waiting",
        "analyzed_at": _now().replace(tzinfo=None),
        "sources": {},
    }
    fields.update(overrides)
    with get_session() as s:
        s.add(TaskItem(**fields))
    return tid


def _task_dict(**overrides):
    """Hand-built task dict in the get_task_items shape."""
    d = {
        "id": str(uuid.uuid4()),
        "completed_at": None,
        "action_required": True,
        "urgency": "medium",
        "suggested_action": "Reply to the customer",
        "reason": "They are waiting",
        "title": "Reply",
        "contact_email": "",
        "contact_phone": "",
        "channel": "email",
        "analyzed_at": (_now() - timedelta(hours=2)).isoformat(),
        "created_at": (_now() - timedelta(days=1)).isoformat(),
        "sources": {},
    }
    d.update(overrides)
    return d


def _sweeps_patched(dedup=None, topic=None, reanalyze=0, f4_aborted=False, forbid=False):
    """Patch the three sweep impls on process_pipeline.

    ``_reanalyze_sweep`` returns ``(ok_count, aborted)`` since the T5
    daily-stamp fix. ``forbid=True`` makes any call fail the test —
    used to prove a gated-off sweep is truly never invoked.
    """
    from zylch.services import process_pipeline as pp

    if forbid:
        boom = AsyncMock(side_effect=AssertionError("sweep must not run"))
        return (
            patch.object(pp, "_reanalyze_sweep", boom),
            patch.object(pp, "_run_dedup_sweep", boom),
            patch.object(pp, "_run_topic_dedup", boom),
        )
    return (
        patch.object(pp, "_reanalyze_sweep", AsyncMock(return_value=(reanalyze, f4_aborted))),
        patch.object(
            pp,
            "_run_dedup_sweep",
            AsyncMock(return_value=dedup or {"tasks_closed": 0, "no_llm": False}),
        ),
        patch.object(
            pp,
            "_run_topic_dedup",
            AsyncMock(return_value=topic or {"tasks_closed": 0, "no_llm": False}),
        ),
    )


# =====================================================================
# 1) Fingerprint
# =====================================================================


def test_fingerprint_ignores_analyzed_at():
    """F4 bumps analyzed_at on every 'keep' — if it participated, the
    fingerprint would change every pass and F8/F9 would re-run forever."""
    t = _task_dict()
    a = open_tasks_fingerprint([t])
    b = open_tasks_fingerprint([{**t, "analyzed_at": _now().isoformat()}])
    assert a == b


def test_fingerprint_changes_on_real_change():
    t = _task_dict()
    assert open_tasks_fingerprint([t]) != open_tasks_fingerprint([{**t, "urgency": "high"}])
    assert open_tasks_fingerprint([t]) != open_tasks_fingerprint([])  # set membership


def test_fingerprint_order_insensitive():
    t1, t2 = _task_dict(), _task_dict()
    assert open_tasks_fingerprint([t1, t2]) == open_tasks_fingerprint([t2, t1])


# =====================================================================
# 2) f4_candidates — the activity gate
# =====================================================================


def test_f4_newer_thread_mail_is_eligible(fresh_db):
    owner = "o-f4a"
    t = _task_dict(sources={"thread_id": "T1"})
    _insert_email(owner, thread_id="T1", from_email="carla@x.it", ts=_now())
    assert f4_candidates(owner, _store(), [t]) == [t]


def test_f4_no_new_activity_not_eligible(fresh_db):
    owner = "o-f4b"
    t = _task_dict(sources={"thread_id": "T1"})
    _insert_email(owner, thread_id="T1", from_email="carla@x.it", ts=_now() - timedelta(hours=5))
    assert f4_candidates(owner, _store(), [t]) == []


def test_f4_contact_sibling_mail_is_eligible(fresh_db):
    """User corresponded with the same contact on a DIFFERENT thread
    (the case F6 sibling-resolution exists for) — still new activity."""
    owner = "o-f4c"
    t = _task_dict(sources={"thread_id": "T1"}, contact_email="carla@x.it")
    _insert_email(
        owner,
        thread_id="T-other",
        from_email="me@mrcall.ai",
        to_email="Carla <carla@x.it>",
        ts=_now(),
    )
    assert f4_candidates(owner, _store(), [t]) == [t]


def test_f4_whatsapp_task_with_newer_message_is_eligible(fresh_db):
    owner = "o-f4d"
    jid = "393331234567@s.whatsapp.net"
    # Legacy layout: chat JID stored in sources.thread_id.
    t = _task_dict(channel="whatsapp", contact_email="", sources={"thread_id": jid})
    _insert_wa(owner, chat_jid=jid, ts=_now())
    assert f4_candidates(owner, _store(), [t]) == [t]


def test_f4_unresolvable_task_not_eligible(fresh_db):
    """No thread, no contact, no jid → treated as NO new activity; the
    daily pass covers it."""
    owner = "o-f4e"
    t = _task_dict(sources={}, contact_email="")
    _insert_email(owner, thread_id="T1", from_email="x@y.it", ts=_now())
    assert f4_candidates(owner, _store(), [t]) == []


def test_f4_force_all_returns_all_open(fresh_db):
    owner = "o-f4f"
    open1 = _task_dict()
    open2 = _task_dict()
    done = _task_dict(completed_at=_now().isoformat())
    fyi = _task_dict(action_required=False)
    got = f4_candidates(owner, _store(), [open1, done, open2, fyi], force_all=True)
    assert got == [open1, open2]


# =====================================================================
# 3) Daily pass + fingerprint gate state
# =====================================================================


def test_daily_pass_due_when_stamp_missing(fresh_db):
    assert daily_pass_due("o-d1") is True


def test_daily_pass_due_when_stamp_25h_old(fresh_db):
    set_state("o-d2", WS_KEY_LAST_FULL_SWEEP, (_now() - timedelta(hours=25)).isoformat())
    assert daily_pass_due("o-d2") is True


def test_daily_pass_not_due_when_stamp_fresh(fresh_db):
    set_state("o-d3", WS_KEY_LAST_FULL_SWEEP, (_now() - timedelta(hours=1)).isoformat())
    assert daily_pass_due("o-d3") is False


@pytest.mark.asyncio
async def test_daily_stamp_written_only_after_sweeps_ran(fresh_db):
    owner = "o-d4"
    plan = WorkPlan(daily_pass=True, force_all=True, dedup_due=True)
    assert get_state(owner, WS_KEY_LAST_FULL_SWEEP) is None
    p1, p2, p3 = _sweeps_patched()
    with p1, p2, p3:
        await run_gated_sweeps(owner, _store(), plan)
    assert get_state(owner, WS_KEY_LAST_FULL_SWEEP) is not None
    assert plan.daily_stamped is True
    assert plan.sweeps_ran is True
    assert get_state(owner, WS_KEY_DEDUP_FINGERPRINT) == open_tasks_fingerprint([])


@pytest.mark.asyncio
async def test_daily_stamp_not_written_when_sweeps_had_no_llm(fresh_db):
    """A no_llm no-op proves nothing — the stamp must not advance, so
    the next tick retries the full pass."""
    owner = "o-d5"
    plan = WorkPlan(daily_pass=True, force_all=True, dedup_due=True)
    p1, p2, p3 = _sweeps_patched(dedup={"tasks_closed": 0, "no_llm": True})
    with p1, p2, p3:
        await run_gated_sweeps(owner, _store(), plan)
    assert get_state(owner, WS_KEY_LAST_FULL_SWEEP) is None
    assert plan.daily_stamped is False


# T5 review, finding b: a HALF-completed daily pass (F4 aborted on
# consecutive 529s, F8 aborted its arbiter loop, or F9's single call
# failed) must NOT be stamped as done for 24h — the stamp is the 24h
# safety net's only proof of completion.


@pytest.mark.asyncio
async def test_daily_stamp_not_written_when_f4_aborted(fresh_db, caplog):
    owner = "o-d6"
    _insert_task_row(owner)  # force_all makes it an F4 candidate
    plan = WorkPlan(daily_pass=True, force_all=True, dedup_due=True)
    p1, p2, p3 = _sweeps_patched(f4_aborted=True)
    with caplog.at_level(logging.WARNING), p1, p2, p3:
        result = await run_gated_sweeps(owner, _store(), plan)
    assert result["f4_aborted"] is True
    assert result["f8f9_ran"] is True  # F8/F9 still ran…
    assert get_state(owner, WS_KEY_LAST_FULL_SWEEP) is None  # …but no stamp
    assert plan.daily_stamped is False
    assert "daily pass INCOMPLETE" in caplog.text


@pytest.mark.asyncio
async def test_daily_stamp_not_written_when_dedup_aborted_overload(fresh_db):
    owner = "o-d7"
    plan = WorkPlan(daily_pass=True, force_all=True, dedup_due=True)
    p1, p2, p3 = _sweeps_patched(
        dedup={"tasks_closed": 0, "no_llm": False, "aborted_overload": True}
    )
    with p1, p2, p3:
        await run_gated_sweeps(owner, _store(), plan)
    assert get_state(owner, WS_KEY_LAST_FULL_SWEEP) is None
    assert plan.daily_stamped is False


@pytest.mark.asyncio
async def test_daily_stamp_not_written_when_topic_llm_failed(fresh_db):
    owner = "o-d8"
    plan = WorkPlan(daily_pass=True, force_all=True, dedup_due=True)
    p1, p2, p3 = _sweeps_patched(topic={"tasks_closed": 0, "no_llm": False, "llm_failed": True})
    with p1, p2, p3:
        await run_gated_sweeps(owner, _store(), plan)
    assert get_state(owner, WS_KEY_LAST_FULL_SWEEP) is None
    assert plan.daily_stamped is False


@pytest.mark.asyncio
async def test_f8f9_skipped_after_recheck_when_fingerprint_unchanged(fresh_db, caplog):
    owner = "o-fp1"
    _insert_task_row(owner, sources={}, contact_email="")
    store = _store()
    baseline = open_tasks_fingerprint(
        store.get_task_items(owner_id=owner, action_required=True, limit=10000)
    )
    set_state(owner, WS_KEY_DEDUP_FINGERPRINT, baseline)
    assert sweeps_due(owner, baseline) is False

    plan = WorkPlan()  # no force, no daily
    p1, p2, p3 = _sweeps_patched(forbid=True)  # any sweep call fails the test
    with caplog.at_level(logging.INFO), p1, p2, p3:
        result = await run_gated_sweeps(owner, store, plan)
    assert result["f8f9_ran"] is False
    assert plan.sweeps_ran is False
    assert "F8/F9 skipped after recheck (fingerprint unchanged)" in caplog.text
    assert get_state(owner, WS_KEY_DEDUP_FINGERPRINT) == baseline  # untouched


@pytest.mark.asyncio
async def test_f8f9_run_and_fingerprint_stored_on_real_change(fresh_db, caplog):
    """A changed open set re-arms F8/F9 within one tick, and the
    post-sweep fingerprint becomes the new baseline."""
    owner = "o-fp2"
    store = _store()
    set_state(owner, WS_KEY_DEDUP_FINGERPRINT, open_tasks_fingerprint([]))
    _insert_task_row(owner, sources={}, contact_email="")  # the change

    plan = WorkPlan()
    p1, p2, p3 = _sweeps_patched()
    with caplog.at_level(logging.INFO), p1, p2, p3:
        result = await run_gated_sweeps(owner, store, plan)
    assert result["f8f9_ran"] is True
    assert "post-sweep fingerprint stored" in caplog.text
    stored = get_state(owner, WS_KEY_DEDUP_FINGERPRINT)
    assert stored == open_tasks_fingerprint(
        store.get_task_items(owner_id=owner, action_required=True, limit=10000)
    )
    assert stored != open_tasks_fingerprint([])


def test_new_task_flips_plan_to_due(fresh_db):
    """Acceptance line from the plan: creating a fake task makes exactly
    one F8/F9 run eligible on the next tick."""
    owner = "o-fp3"
    store = _store()
    set_state(owner, WS_KEY_DEDUP_FINGERPRINT, open_tasks_fingerprint([]))
    set_state(owner, WS_KEY_LAST_FULL_SWEEP, _now().isoformat())

    assert build_work_plan(owner, store).idle is True
    _insert_task_row(owner, sources={}, contact_email="")
    plan = build_work_plan(owner, store)
    assert plan.dedup_due is True
    assert plan.idle is False


# =====================================================================
# 4) FORCE_FULL_SWEEPS escape hatch
# =====================================================================


def test_force_full_sweeps_bypasses_gates(fresh_db, monkeypatch):
    owner = "o-force"
    store = _store()
    # Seed a state that would otherwise be fully idle.
    set_state(owner, WS_KEY_DEDUP_FINGERPRINT, open_tasks_fingerprint([]))
    set_state(owner, WS_KEY_LAST_FULL_SWEEP, _now().isoformat())
    _insert_task_row(owner, sources={}, contact_email="")
    set_state(
        owner,
        WS_KEY_DEDUP_FINGERPRINT,
        open_tasks_fingerprint(
            store.get_task_items(owner_id=owner, action_required=True, limit=10000)
        ),
    )
    assert build_work_plan(owner, store).idle is True

    monkeypatch.setenv("FORCE_FULL_SWEEPS", "1")
    plan = build_work_plan(owner, store)
    assert plan.force_full_sweeps is True
    assert plan.force_all is True  # f4 force_all
    assert plan.dedup_due is True  # F8/F9 due
    assert plan.f4_eligible == 1  # the open task, despite no activity
    assert plan.idle is False


# =====================================================================
# 5) Merge-canary policy
# =====================================================================


def test_canary_skipped_when_healthy_and_fresh(fresh_db, monkeypatch):
    owner = "o-c1"
    monkeypatch.setattr(mcg, "_canary_verified_since_start", True)
    set_state(owner, mcg.WS_KEY_CANARY_HEALTHY, "1")
    set_state(owner, mcg.WS_KEY_CANARY_AT, _now().isoformat())
    assert mcg.merge_canary_policy(owner)["run"] is False
    # Merging on: a transient record() call in this state keeps it on.
    assert mcg.record_merge_canary(owner, None) is True


def test_canary_runs_when_stamp_stale_or_first_run(fresh_db, monkeypatch):
    owner = "o-c2"
    set_state(owner, mcg.WS_KEY_CANARY_HEALTHY, "1")
    # first memory pass since daemon start → run even with a fresh stamp
    set_state(owner, mcg.WS_KEY_CANARY_AT, _now().isoformat())
    monkeypatch.setattr(mcg, "_canary_verified_since_start", False)
    assert mcg.merge_canary_policy(owner)["run"] is True
    # verified once, fresh stamp → skip; then a 25h-old stamp → run
    monkeypatch.setattr(mcg, "_canary_verified_since_start", True)
    assert mcg.merge_canary_policy(owner)["run"] is False
    set_state(owner, mcg.WS_KEY_CANARY_AT, (_now() - timedelta(hours=25)).isoformat())
    assert mcg.merge_canary_policy(owner)["run"] is True


def test_canary_unhealthy_is_sticky_until_a_pass(fresh_db, monkeypatch):
    owner = "o-c3"
    monkeypatch.setattr(mcg, "_canary_verified_since_start", True)
    # Broken-open verdict → merging off, state stored.
    assert mcg.record_merge_canary(owner, False) is False
    assert get_state(owner, mcg.WS_KEY_CANARY_HEALTHY) == "0"
    # Sticky: policy re-runs every pass; a transient result keeps
    # merging OFF (never "heals" by accident).
    assert mcg.merge_canary_policy(owner)["run"] is True
    assert mcg.record_merge_canary(owner, None) is False
    assert mcg.merge_canary_policy(owner)["run"] is True
    # A real pass flips it back on.
    assert mcg.record_merge_canary(owner, True) is True
    assert get_state(owner, mcg.WS_KEY_CANARY_HEALTHY) == "1"


def test_canary_no_stored_verdict_runs(fresh_db, monkeypatch):
    monkeypatch.setattr(mcg, "_canary_verified_since_start", True)
    assert mcg.merge_canary_policy("o-c4")["run"] is True


# =====================================================================
# 6) Idle pipeline path — the headline: zero LLM construction
# =====================================================================


@pytest.mark.asyncio
async def test_idle_tick_constructs_no_llm_client(fresh_db, monkeypatch, caplog):
    """With nothing pending, no eligible task, fingerprint unchanged and
    the daily pass fresh, handle_process must log the idle line, skip
    the budget log AND the preflight, record no llm_usage row, and
    never even construct an LLM client."""
    owner = "o-idle"
    monkeypatch.setenv("EMAIL_ADDRESS", "support@mrcall.ai")
    set_state(owner, WS_KEY_DEDUP_FINGERPRINT, open_tasks_fingerprint([]))
    set_state(owner, WS_KEY_LAST_FULL_SWEEP, _now().isoformat())

    def _boom(*a, **k):
        raise AssertionError("LLM client constructed on idle path")

    for target in (
        "zylch.llm.client.make_llm_client",
        "zylch.llm.client.try_make_llm_client",
        "zylch.llm.make_llm_client",
        "zylch.llm.try_make_llm_client",
        "zylch.workers.memory.make_llm_client",
        "zylch.workers.task_creation.make_llm_client",
    ):
        monkeypatch.setattr(target, _boom)

    from zylch.services import process_pipeline as pp

    with (
        patch.object(pp, "_run_sync", AsyncMock(return_value={"success": True, "new_messages": 0})),
        patch.object(pp, "_run_whatsapp_sync", return_value={"skipped": True, "reason": "test"}),
        patch(
            "zylch.services.command_handlers.handle_tasks",
            AsyncMock(return_value="no tasks"),
        ),
        caplog.at_level(logging.INFO),
    ):
        out = await pp.handle_process([], None, owner)

    assert out == "no tasks"
    assert "[update] idle tick — zero LLM calls" in caplog.text
    assert "[llm-budget]" not in caplog.text  # budget log skipped
    assert "preflight" not in caplog.text  # no attempt at all
    assert "idle=True" in caplog.text  # update.summary field

    from zylch.storage.database import get_session
    from zylch.storage.models import LlmUsage

    with get_session() as s:
        assert s.query(LlmUsage).count() == 0


# =====================================================================
# 7) Cross-channel task pendings (T5 review, finding a)
# =====================================================================
#
# _analyze_recent_events consumes email AND WhatsApp AND calendar
# task-pendings, so the work plan must count all three: a tick whose
# only pending work is a WhatsApp message (memory-processed but not yet
# task-processed) or a calendar event must NOT read as idle, and must
# route to the detection stage (_run_tasks), not the sweep-only branch.


def _seed_otherwise_idle(owner):
    """worker_state fixture that would make the owner fully idle."""
    set_state(owner, WS_KEY_DEDUP_FINGERPRINT, open_tasks_fingerprint([]))
    set_state(owner, WS_KEY_LAST_FULL_SWEEP, _now().isoformat())


def test_wa_task_pending_blocks_idle(fresh_db):
    owner = "o-wa-pend"
    _seed_otherwise_idle(owner)
    _insert_wa(owner, chat_jid="391112223334@s.whatsapp.net", memory_processed=True)

    plan = build_work_plan(owner, _store())
    assert plan.pending_wa == 0  # memory side already drained…
    assert plan.pending_tasks_wa == 1  # …but task detection still due
    assert plan.pending_detect == 1
    assert plan.idle is False


def test_calendar_task_pending_blocks_idle(fresh_db):
    owner = "o-cal-pend"
    _seed_otherwise_idle(owner)
    _insert_cal(owner)

    plan = build_work_plan(owner, _store())
    assert plan.pending_tasks_cal == 1
    assert plan.pending_detect == 1
    assert plan.idle is False


def test_processed_wa_and_cal_rows_stay_idle(fresh_db):
    """Fully-processed WhatsApp/calendar rows must not un-idle the tick
    — otherwise every historic row would defeat the gate forever."""
    owner = "o-proc-idle"
    _seed_otherwise_idle(owner)
    _insert_wa(
        owner, chat_jid="391112223334@s.whatsapp.net", memory_processed=True, task_processed=True
    )
    _insert_cal(owner, task_processed=True)

    plan = build_work_plan(owner, _store())
    assert plan.pending_detect == 0
    assert plan.idle is True


@pytest.mark.asyncio
async def test_wa_task_pending_routes_to_detection_stage(fresh_db, monkeypatch, caplog):
    """Pipeline-level: a WA-only task pending must reach _run_tasks (the
    detection stage), not fall through to the sweep-only branch."""
    owner = "o-wa-route"
    monkeypatch.setenv("EMAIL_ADDRESS", "support@mrcall.ai")
    _seed_otherwise_idle(owner)
    _insert_wa(owner, chat_jid="391112223334@s.whatsapp.net", memory_processed=True)

    class _OkPreflight:
        async def create_message(self, **kwargs):
            return object()

    from zylch.services import process_pipeline as pp

    ran = AsyncMock(return_value="detection ran")
    with (
        patch.object(pp, "_run_sync", AsyncMock(return_value={"success": True, "new_messages": 0})),
        patch.object(pp, "_run_whatsapp_sync", return_value={"skipped": True, "reason": "test"}),
        patch("zylch.llm.client.make_llm_client", lambda *a, **k: _OkPreflight()),
        patch.object(pp, "_run_tasks", ran),
        patch.object(pp, "_reanalyze_only", AsyncMock(side_effect=AssertionError("wrong branch"))),
        patch.object(pp, "_run_memory", AsyncMock(return_value=(0, 0))),
        patch(
            "zylch.services.command_handlers.handle_tasks",
            AsyncMock(return_value="no tasks"),
        ),
        caplog.at_level(logging.INFO),
    ):
        await pp.handle_process([], None, owner)

    ran.assert_awaited_once()
    assert "wa_tasks=1" in caplog.text
    assert "[update] idle tick" not in caplog.text
