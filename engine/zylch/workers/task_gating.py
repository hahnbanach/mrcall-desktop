"""Event-gating for the background pipeline (support-llm-cost-fix / P3).

Before this module, every 5-minute tick did Opus-priced work whether or
not anything changed: F4 re-judged every open task hourly forever
(``analyzed_at`` is bumped even on "keep", so each task re-arms), F8/F9
re-clustered the same unchanged open list every tick, the merge-gate
canary burned a call on every mail-bearing tick, and the preflight ping
ran always. This module makes cost scale with information change:

- **F4 gate** (:func:`f4_candidates`): a task is re-analyzed only when
  its thread — or other mail from the same contact, or its WhatsApp
  chat — has activity NEWER than the task's last analysis. Pure SQL.
- **F8/F9 gate** (:func:`open_tasks_fingerprint` + ``worker_state``):
  the dedup sweeps run only when a fingerprint of the open-task set
  changed since the last sweep. Any create/close/update changes the
  fingerprint, so reactivity to real changes stays at one tick.
- **Daily full pass** (:func:`daily_pass_due`): once per 24h everything
  is forced — the safety net for changes the gates can't see (e.g. a
  USER_NOTES edit that should rewrite suggested_actions).
- **FORCE_FULL_SWEEPS** env: emergency bypass — every tick behaves like
  the daily pass, restoring the pre-gating cost profile.

The memory-side sibling (the merge-gate canary policy) lives in
:mod:`zylch.workers.merge_canary_gate`.

An idle tick — nothing pending, no task with new activity, fingerprint
unchanged, no daily pass — makes ZERO LLM call attempts; the pipeline
must not even construct an LLM client (see ``handle_process``).

Persistent state lives in the ``worker_state`` KV
(:mod:`zylch.storage.worker_state`); everything here is fail-open —
a broken read degrades to "the sweep is due", never to a skipped one.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from zylch.storage.worker_state import get_state, set_state

logger = logging.getLogger(__name__)


# worker_state keys owned by this module.
WS_KEY_DEDUP_FINGERPRINT = "dedup_fingerprint"
WS_KEY_LAST_FULL_SWEEP = "last_full_sweep_at"

# The daily full-pass cadence.
DAILY_FULL_SWEEP_HOURS = 24

# Fields hashed into the open-task fingerprint. CRITICAL: analyzed_at
# is deliberately EXCLUDED — F4 bumps it on every "keep" decision, so
# including it would change the fingerprint on every F4 pass and
# re-trigger F8/F9 forever, defeating the whole gate. Set membership
# (created/closed tasks) is captured by the ids themselves.
_FINGERPRINT_FIELDS = (
    "id",
    "urgency",
    "suggested_action",
    "reason",
    "title",
    "contact_email",
    "contact_phone",
    "channel",
)


def force_full_sweeps_enabled() -> bool:
    """Live ``os.environ`` read of the FORCE_FULL_SWEEPS escape hatch.

    "1" / "true" / "yes" (any case) → every tick behaves like the daily
    full pass. Read live — NOT from the frozen pydantic settings — so a
    ``settings.update`` takes effect with no daemon restart (precedent:
    engine commit 06fb766, LLM_DAILY_BUDGET_USD, TASK_BACKLOG_MAX_AGE_DAYS).
    """
    raw = (os.environ.get("FORCE_FULL_SWEEPS") or "").strip().lower()
    return raw in ("1", "true", "yes")


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse an ISO string / datetime into an aware-UTC datetime.

    Naive values are assumed UTC (matches how the storage layer writes
    them — same convention as ``_reanalyze_sweep``). Unparseable → None.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _max_dt(a: Optional[datetime], b: Optional[datetime]) -> Optional[datetime]:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def open_tasks_fingerprint(tasks: Optional[List[Dict[str, Any]]]) -> str:
    """SHA-256 over the SORTED per-task field tuples of the open set.

    Order-insensitive: the rendered rows are sorted before hashing, so
    two fetches of the same set in different order hash identically.
    See ``_FINGERPRINT_FIELDS`` for what participates (and why
    ``analyzed_at`` must not).
    """
    rows = ["\x1f".join(str(t.get(f) or "") for f in _FINGERPRINT_FIELDS) for t in (tasks or [])]
    rows.sort()
    return hashlib.sha256("\x1e".join(rows).encode("utf-8")).hexdigest()


def _email_activity_max(session, owner_id: str, *filters) -> Optional[datetime]:
    """Latest email activity matching ``filters``.

    Prefers the epoch ``date_timestamp`` and falls back to the DateTime
    ``date`` column (nullable timestamps exist on legacy rows); returns
    the max across both, aware UTC.
    """
    from sqlalchemy import func

    from zylch.storage.models import Email

    ts_max, date_max = (
        session.query(func.max(Email.date_timestamp), func.max(Email.date))
        .filter(Email.owner_id == owner_id, *filters)
        .one()
    )
    best: Optional[datetime] = None
    if ts_max:
        best = datetime.fromtimestamp(int(ts_max), tz=timezone.utc)
    return _max_dt(best, _parse_dt(date_max))


def _latest_task_activity(session, owner_id: str, task: Dict[str, Any]) -> Optional[datetime]:
    """Latest timestamp of any activity relevant to ``task``, or None.

    Activity sources — any one suffices; the max across all resolvable
    ones is returned:

    1. the task's primary email thread, resolved exactly like
       ``task_reanalyze._resolve_thread_id`` (``sources.thread_id``,
       else ``sources.emails[0]`` → ``emails.thread_id``);
    2. any mail exchanged with the task's contact — ``from_email``
       equals, or ``to_email``/``cc_email`` contains, the canonical
       lowercased ``contact_email``. This covers the sibling-thread
       resolution case F6 exists for (user replied on a different
       thread with the same contact);
    3. the task's WhatsApp chat (``sources.whatsapp_chat_jid``, legacy
       fallback ``sources.thread_id`` when channel == 'whatsapp').

    ``None`` means no source could be resolved at all — the caller
    treats that as NO new activity (the daily pass covers such tasks).
    """
    from sqlalchemy import func, or_

    from zylch.storage.models import Email, WhatsAppMessage
    from zylch.workers.task_reanalyze import _resolve_thread_id

    best: Optional[datetime] = None
    channel = (task.get("channel") or "").lower()
    sources = task.get("sources") or {}
    wa_jid = (sources.get("whatsapp_chat_jid") or "").strip()
    if not wa_jid and channel == "whatsapp":
        wa_jid = (sources.get("thread_id") or "").strip()

    # 1. Primary email thread. Skipped for whatsapp-channel tasks whose
    #    sources.thread_id actually holds a chat JID (legacy layout) —
    #    matching emails on a JID string can only ever find nothing.
    if channel != "whatsapp":
        thread_id = _resolve_thread_id({**task, "owner_id": owner_id}, session)
        if thread_id:
            best = _max_dt(
                best, _email_activity_max(session, owner_id, Email.thread_id == thread_id)
            )

    # 2. Same contact anywhere.
    contact = (task.get("contact_email") or "").strip().lower()
    if contact:
        like = f"%{contact}%"
        best = _max_dt(
            best,
            _email_activity_max(
                session,
                owner_id,
                or_(
                    func.lower(Email.from_email) == contact,
                    Email.to_email.like(like),
                    Email.cc_email.like(like),
                ),
            ),
        )

    # 3. WhatsApp chat.
    if wa_jid:
        (wa_max,) = (
            session.query(func.max(WhatsAppMessage.timestamp))
            .filter(WhatsAppMessage.owner_id == owner_id, WhatsAppMessage.chat_jid == wa_jid)
            .one()
        )
        best = _max_dt(best, _parse_dt(wa_max))

    return best


def f4_candidates(
    owner_id: str,
    store,
    tasks: Optional[List[Dict[str, Any]]],
    force_all: bool = False,
) -> List[Dict[str, Any]]:
    """Open ``action_required`` tasks with NEW ACTIVITY since analysis.

    "New activity" = the latest relevant activity (see
    :func:`_latest_task_activity`) is strictly newer than the task's
    ``analyzed_at`` (falling back to ``created_at``; naive → UTC, same
    parsing as ``_reanalyze_sweep``). ``force_all=True`` skips the
    activity filter but still restricts to open + action_required —
    that is the daily-pass / FORCE_FULL_SWEEPS behavior, which matches
    the pre-gating sweep input exactly.

    Per-task queries are acceptable: open counts are small (~10-35).
    The 1h min-age and cap-10 rules stay where they always lived, in
    ``process_pipeline._reanalyze_sweep`` — this function only answers
    "did anything move since we last judged this task?".
    """
    open_tasks = [
        t for t in (tasks or []) if not t.get("completed_at") and t.get("action_required")
    ]
    if force_all or not open_tasks:
        return open_tasks

    from zylch.storage.database import get_session

    out: List[Dict[str, Any]] = []
    with get_session() as session:
        for t in open_tasks:
            analyzed = _parse_dt(t.get("analyzed_at") or t.get("created_at"))
            if analyzed is None:
                # Undatable task — can't tell what "new" means; the
                # daily pass covers it.
                continue
            try:
                latest = _latest_task_activity(session, owner_id, t)
            except Exception as e:  # noqa: BLE001 — one bad task must not kill the plan
                logger.warning(f"[gating] activity resolution failed for task {t.get('id')}: {e}")
                continue
            if latest is not None and latest > analyzed:
                out.append(t)
    return out


def sweeps_due(owner_id: str, fingerprint: str) -> bool:
    """True when ``fingerprint`` differs from the stored F8/F9 baseline.

    No stored baseline (fresh profile, or the sweeps have never
    completed since gating landed) also reads as due — the safe
    direction. The caller logs the decision.
    """
    stored = get_state(owner_id, WS_KEY_DEDUP_FINGERPRINT)
    return stored is None or stored != fingerprint


def daily_pass_due(owner_id: str) -> bool:
    """True when the last full sweep is missing or older than 24h."""
    stamp = _parse_dt(get_state(owner_id, WS_KEY_LAST_FULL_SWEEP))
    if stamp is None:
        return True
    return datetime.now(timezone.utc) - stamp >= timedelta(hours=DAILY_FULL_SWEEP_HOURS)


@dataclass
class WorkPlan:
    """One tick's gating decisions, computed before any LLM code runs.

    The dedup decision is ADVISORY — detection and F4 can change the
    open set, so :func:`run_gated_sweeps` recomputes the final call.
    ``sweeps_ran`` / ``daily_stamped`` are outcome fields written back
    by :func:`run_gated_sweeps` for the ``[update.summary]`` line.
    """

    pending_mem: int = 0
    pending_wa: int = 0
    pending_tasks: int = 0
    pending_tasks_wa: int = 0
    pending_tasks_cal: int = 0
    open_count: int = 0
    f4_eligible: int = 0
    daily_pass: bool = False
    force_full_sweeps: bool = False
    force_all: bool = False
    dedup_due: bool = False
    idle: bool = False
    sweeps_ran: bool = False
    daily_stamped: bool = False

    @property
    def pending_detect(self) -> int:
        """Total events awaiting TASK detection across all channels.

        ``_analyze_recent_events`` processes email AND WhatsApp AND
        calendar task-pendings in one detection pass, so the pipeline's
        "is detection due" question must sum all three — counting only
        emails (the pre-T5 behavior, inherited from main) let a tick
        with only WhatsApp/calendar task work read as idle (T5 review,
        finding a).
        """
        return self.pending_tasks + self.pending_tasks_wa + self.pending_tasks_cal


def build_work_plan(owner_id: str, store) -> WorkPlan:
    """Compute + log the tick's work plan. Pure SQL, no LLM.

    Called by ``handle_process`` AFTER the hygiene stage (which may
    drain pending rows) and BEFORE any budget/preflight/LLM code. The
    four ``[gating]`` lines below appear on EVERY tick — they are the
    audit trail for "why did/didn't this tick spend".
    """
    pending_mem = len(store.get_unprocessed_emails(owner_id))
    pending_wa = len(store.get_unprocessed_whatsapp_messages(owner_id))
    pending_tasks = len(store.get_unprocessed_emails_for_task(owner_id))
    # Task detection is cross-channel: `_analyze_recent_events` also
    # consumes WhatsApp and calendar task-pendings, so they must count
    # toward "is there detection work" or a WA/calendar-only tick would
    # read as idle and silently skip real task work (T5, finding a).
    pending_tasks_wa = len(store.get_unprocessed_whatsapp_messages_for_task(owner_id))
    pending_tasks_cal = len(store.get_unprocessed_calendar_events_for_task(owner_id))
    open_tasks = store.get_task_items(owner_id=owner_id, action_required=True, limit=10000)

    force = force_full_sweeps_enabled()
    daily = daily_pass_due(owner_id)
    force_all = force or daily

    eligible = f4_candidates(owner_id, store, open_tasks, force_all=force_all)
    changed = sweeps_due(owner_id, open_tasks_fingerprint(open_tasks))
    dedup_due = force_all or changed

    idle = (
        pending_mem == 0
        and pending_wa == 0
        and pending_tasks == 0
        and pending_tasks_wa == 0
        and pending_tasks_cal == 0
        and not eligible
        and not dedup_due
    )

    logger.info(
        f"[gating] pending: mem={pending_mem} wa={pending_wa} tasks={pending_tasks} "
        f"wa_tasks={pending_tasks_wa} cal_tasks={pending_tasks_cal}"
    )
    logger.info(
        f"[gating] f4 eligible={len(eligible)} of {len(open_tasks)} open "
        f"(force_all={force_all})"
    )
    logger.info(
        f"[gating] dedup fingerprint {'changed' if changed else 'unchanged'} → "
        f"F8/F9 {'due' if dedup_due else 'not due'} (advisory)"
    )
    logger.info(f"[gating] daily_pass={daily} force_full_sweeps={force}")

    return WorkPlan(
        pending_mem=pending_mem,
        pending_wa=pending_wa,
        pending_tasks=pending_tasks,
        pending_tasks_wa=pending_tasks_wa,
        pending_tasks_cal=pending_tasks_cal,
        open_count=len(open_tasks),
        f4_eligible=len(eligible),
        daily_pass=daily,
        force_full_sweeps=force,
        force_all=force_all,
        dedup_due=dedup_due,
        idle=idle,
    )


def fallback_work_plan(owner_id: str, store) -> WorkPlan:
    """Fail-open plan for when :func:`build_work_plan` raised.

    Reproduces the pre-gating pipeline: F4 considers every open task
    (``force_all``, on which ``_reanalyze_sweep`` still applies its own
    1h/cap-10 rules), F8/F9 run, never idle. The daily stamp is NOT
    advanced from a fallback tick (``daily_pass`` stays False), so the
    real daily pass is retried once the plan builder recovers.
    """
    plan = WorkPlan(force_all=True, dedup_due=True, idle=False)
    try:
        plan.pending_mem = len(store.get_unprocessed_emails(owner_id))
        plan.pending_wa = len(store.get_unprocessed_whatsapp_messages(owner_id))
        plan.pending_tasks = len(store.get_unprocessed_emails_for_task(owner_id))
        plan.pending_tasks_wa = len(store.get_unprocessed_whatsapp_messages_for_task(owner_id))
        plan.pending_tasks_cal = len(store.get_unprocessed_calendar_events_for_task(owner_id))
    except Exception as e:  # noqa: BLE001 — a dead count query must not kill the tick
        logger.error(f"[gating] fallback plan pending counts failed: {e}")
    return plan


async def run_gated_sweeps(owner_id: str, store, plan: WorkPlan) -> Dict[str, Any]:
    """The ONE shared sweep stage (F4 + F8/F9 + phone age-close).

    Used by BOTH pipeline branches — ``_run_tasks`` (mail-bearing) and
    ``_reanalyze_only`` (no-mail) — so the two code paths cannot drift.
    Preserves ``_reanalyze_only``'s property of never constructing a
    ``TaskWorker``.

    Ordering matters: detection (when it ran) and F4 can create/close/
    update tasks, so the FINAL F8/F9 decision is recomputed HERE from
    the post-F4 open set; the work-plan line was advisory. The
    post-sweep fingerprint is stored only when F8/F9 actually ran — a
    skipped sweep keeps the old baseline, losing nothing.
    """
    # Lazy import — the sweep implementations (cap-10 + 529-abort, the
    # cluster arbiters) stay in process_pipeline / their workers; this
    # module only decides WHEN they run. Function-level on both sides,
    # so no import cycle.
    from zylch.services.process_pipeline import (
        PHONE_TASK_MAX_AGE_DAYS,
        _reanalyze_sweep,
        _run_dedup_sweep,
        _run_topic_dedup,
    )

    result: Dict[str, Any] = {
        "reanalyzed": 0,
        "dedup_summary": {},
        "topic_summary": {},
        "aged_phone": 0,
        "f8f9_ran": False,
        "f4_aborted": False,
    }

    # F4 — recompute eligibility on the CURRENT open set (detection may
    # have just run: tasks it created carry analyzed_at=now and drop
    # out; tasks it closed are gone from the list).
    open_tasks = store.get_task_items(owner_id=owner_id, action_required=True, limit=10000)
    candidates = f4_candidates(owner_id, store, open_tasks, force_all=plan.force_all)
    if candidates:
        reanalyzed, f4_aborted = await _reanalyze_sweep(owner_id, store, candidates)
        result["reanalyzed"] = int(reanalyzed or 0)
        result["f4_aborted"] = bool(f4_aborted)

    # F8/F9 — final decision from the post-detection+post-F4 open set.
    after_f4 = store.get_task_items(owner_id=owner_id, action_required=True, limit=10000)
    if plan.force_all or sweeps_due(owner_id, open_tasks_fingerprint(after_f4)):
        result["dedup_summary"] = await _run_dedup_sweep(owner_id)
        result["topic_summary"] = await _run_topic_dedup(owner_id)
        result["f8f9_ran"] = True
        plan.sweeps_ran = True
    else:
        logger.info("[gating] F8/F9 skipped after recheck (fingerprint unchanged)")

    # Free SQL-only close — runs regardless of gating (it also runs on
    # idle / LLM-down ticks from the pipeline). Placed BEFORE the
    # post-sweep fingerprint store so the baseline reflects the closes
    # and doesn't re-trigger F8/F9 on the next tick for no new info.
    result["aged_phone"] = int(
        store.auto_close_stale_phone_tasks(owner_id, max_age_days=PHONE_TASK_MAX_AGE_DAYS) or 0
    )

    if result["f8f9_ran"]:
        final = store.get_task_items(owner_id=owner_id, action_required=True, limit=10000)
        set_state(owner_id, WS_KEY_DEDUP_FINGERPRINT, open_tasks_fingerprint(final))
        logger.info("[gating] post-sweep fingerprint stored")

        # Daily-pass stamp: ONLY after the sweeps actually COMPLETED with
        # an LLM transport. A no_llm no-op proves nothing; neither does a
        # pass where F4 aborted on consecutive 529s, F8 aborted its
        # arbiter loop, or F9's single call / a whole sweep failed — a
        # HALF-completed pass stamped as done would silence the 24h
        # safety net (T5 review, finding b). Any of those leaves the
        # stamp untouched so the next tick retries the full pass (529s
        # are not billed; the budget cap still bounds the worst day).
        # A blocked tick (budget gate, preflight failure) never reaches
        # this code, so the next tick retries the full pass.
        dedup_s = result["dedup_summary"] or {}
        topic_s = result["topic_summary"] or {}
        incomplete = bool(
            dedup_s.get("no_llm")
            or topic_s.get("no_llm")
            or dedup_s.get("aborted_overload")
            or dedup_s.get("llm_failed")
            or topic_s.get("llm_failed")
            or result["f4_aborted"]
        )
        if (plan.daily_pass or plan.force_full_sweeps) and not incomplete:
            set_state(owner_id, WS_KEY_LAST_FULL_SWEEP, datetime.now(timezone.utc).isoformat())
            plan.daily_stamped = True
            logger.info("[gating] daily full pass complete — last_full_sweep_at stamped")
        elif (plan.daily_pass or plan.force_full_sweeps) and incomplete:
            logger.warning(
                "[gating] daily pass INCOMPLETE (sweep aborted/failed) — "
                "stamp not advanced, next tick retries"
            )

    return result
