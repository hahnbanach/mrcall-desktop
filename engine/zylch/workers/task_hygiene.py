"""Backlog hygiene for the task pipeline — no LLM involved.

Two structural bugs let the unprocessed-email backlog grow silently
(support-llm-cost-fix / P2):

1. **The auto-ack sink.** support@'s own auto-acknowledgment emails are
   user-authored auto-replies. They can never become a task, and when
   such an email is alone in its thread no marking path ever ran — it
   was re-fetched every tick forever. The grouping-loop fix in
   ``task_creation_email.py`` now marks them at analysis time, but that
   path only runs when the LLM is up. This stage marks them even when
   the key is dead / the budget is exhausted, so the two already-stuck
   rows drain without needing a working LLM.

2. **Unbounded retry of failed analyses.** With the no-mark-on-failure
   fix, a thread whose LLM analysis fails is left unprocessed and
   retried next tick — correct, but a *permanently* failing row would
   be re-fetched every tick without bound. This stage caps that: any
   still-unanalyzed row older than ``TASK_BACKLOG_MAX_AGE_DAYS`` is
   marked task-processed with a WARNING, so the backlog can never grow
   silently again.

The single entry point is :func:`run_task_backlog_hygiene`. It uses no
LLM and is called from ``process_pipeline.handle_process`` BEFORE the
daily-budget gate and the preflight ping — exactly so it still runs in
the states (dead key, exhausted budget) where the LLM stages are
skipped. That is the whole point: the backlog must stop growing in
precisely those states.

Coverage: emails, WhatsApp messages and calendar events. The expiry
rule now spans all three because the WhatsApp and calendar branches
stopped marking their rows processed on LLM failure (defects F1/F2) —
without a bound, "retry next tick" would become "retry forever". The
auto-ack rule stays email-only: it exists for the user's own SMTP
auto-responder, which has no WhatsApp or calendar analogue.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, Optional

from zylch.workers.thread_presenter import load_user_aliases_for_owner

logger = logging.getLogger(__name__)

# Default age (days) after which a still-unanalyzed email is marked
# task-processed by the expiry rule. Read LIVE from os.environ at call
# time (see task_backlog_max_age_days) so a settings.update takes effect
# with no daemon restart — same precedent as LLM_DAILY_BUDGET_USD (T1).
DEFAULT_TASK_BACKLOG_MAX_AGE_DAYS = 14.0


def task_backlog_max_age_days() -> float:
    """Age cap in days, read LIVE from ``os.environ`` at call time.

    Default :data:`DEFAULT_TASK_BACKLOG_MAX_AGE_DAYS` (14) when
    unset/blank. Deliberately NOT read from the pydantic ``settings``
    object — that snapshot is frozen at daemon start, so a
    ``settings.update`` to the profile ``.env`` would be invisible until
    a restart (see engine commit 06fb766 and zylch/llm/usage.py).
    """
    raw = os.environ.get("TASK_BACKLOG_MAX_AGE_DAYS")
    if raw is None or str(raw).strip() == "":
        return DEFAULT_TASK_BACKLOG_MAX_AGE_DAYS
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning(
            f"[hygiene] invalid TASK_BACKLOG_MAX_AGE_DAYS={raw!r} — using "
            f"default {DEFAULT_TASK_BACKLOG_MAX_AGE_DAYS} days"
        )
        return DEFAULT_TASK_BACKLOG_MAX_AGE_DAYS


def _row_age_days(
    row: Dict,
    now: datetime,
    epoch_fields: tuple = ("date_timestamp", "timestamp_epoch"),
    date_fields: tuple = ("date", "timestamp", "start_time"),
) -> Optional[float]:
    """Age of a pending row in days, or ``None`` when it can't be told.

    Prefers a numeric epoch field; falls back to parsing an ISO
    timestamp string. The field names differ per channel — emails carry
    ``date_timestamp`` / ``date``, WhatsApp rows ``timestamp_epoch`` /
    ``timestamp``, calendar events ``start_time`` — so both lookups walk
    a small candidate list.

    Returns ``None`` when nothing is usable: an undatable row is left
    untouched (we can't prove it's expired) rather than marked.
    """
    for field in epoch_fields:
        ts = row.get(field)
        if isinstance(ts, (int, float)) and ts > 0:
            return (now.timestamp() - float(ts)) / 86400.0
    for field in date_fields:
        date_str = row.get(field)
        if not date_str:
            continue
        try:
            dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now - dt).total_seconds() / 86400.0
    return None


def run_task_backlog_hygiene(owner_id: str, store) -> Dict[str, int]:
    """Drain never-analyzable rows and expire ancient ones. No LLM.

    Walks ``store.get_unprocessed_emails_for_task(owner_id)`` and, per
    row, applies exactly one of two rules (the auto-ack rule is checked
    FIRST, so a row that is BOTH user-auto and expired counts as
    auto-ack):

    1. **Auto-ack rule** — a user-authored auto-reply (from ==
       ``EMAIL_ADDRESS`` case-insensitive, OR one of the owner's
       ``EMAIL_ALIASES``, AND the stored ``is_auto_reply`` flag is set)
       is marked task-processed with an INFO log. It can never become a
       task; leaving it unmarked is the structural sink.
    2. **Expiry rule** — any remaining row older than
       ``TASK_BACKLOG_MAX_AGE_DAYS`` is marked task-processed with a
       WARNING. This bounds retry of failed analyses so the backlog
       cannot grow silently.

    It then applies the SAME expiry rule to the WhatsApp and calendar
    task backlogs (:func:`expire_stale_channel_backlog`), which became
    retry-forever surfaces when F1/F2 stopped marking them processed on
    LLM failure.

    Returns ``{"auto_ack_marked": int, "expired_marked": int,
    "expired_whatsapp": int, "expired_calendar": int}``.
    """
    max_age_days = task_backlog_max_age_days()
    now = datetime.now(timezone.utc)

    user_email = (os.environ.get("EMAIL_ADDRESS") or "").strip().lower()
    user_identities = set(load_user_aliases_for_owner(owner_id))
    if user_email:
        user_identities.add(user_email)

    rows = store.get_unprocessed_emails_for_task(owner_id)
    logger.debug(
        f"[hygiene] run_task_backlog_hygiene(owner_id={owner_id}) "
        f"rows={len(rows)} max_age_days={max_age_days} "
        f"user_identities={sorted(user_identities)}"
    )

    auto_ack_marked = 0
    expired_marked = 0

    for row in rows:
        email_id = row.get("id") or ""
        if not email_id:
            continue
        from_email = (row.get("from_email") or "").strip().lower()

        # Rule 1 (checked FIRST): user-authored auto-reply.
        is_user = from_email in user_identities
        is_auto = bool(row.get("is_auto_reply"))
        if is_user and is_auto:
            store.mark_email_task_processed(owner_id, email_id)
            auto_ack_marked += 1
            logger.info(
                f"[hygiene] user auto-reply {email_id} from={from_email} "
                f"date={row.get('date')} marked task-processed "
                f"(never analyzable)"
            )
            continue

        # Rule 2: expire anything older than the cap.
        age_days = _row_age_days(row, now)
        if age_days is not None and age_days > max_age_days:
            store.mark_email_task_processed(owner_id, email_id)
            expired_marked += 1
            logger.warning(
                f"[hygiene] expired unanalyzed email {email_id} "
                f"from={from_email} date={row.get('date')} — marked after "
                f"{max_age_days:g} days"
            )

    channel_expired = expire_stale_channel_backlog(owner_id, store, max_age_days, now)

    result = {
        "auto_ack_marked": auto_ack_marked,
        "expired_marked": expired_marked,
        **channel_expired,
    }
    logger.debug(f"[hygiene] run_task_backlog_hygiene -> {result}")
    return result


def expire_stale_channel_backlog(
    owner_id: str,
    store,
    max_age_days: float,
    now: datetime,
) -> Dict[str, int]:
    """Apply the expiry rule to the WhatsApp + calendar task backlogs.

    Same contract as the email expiry rule above: a row still awaiting
    task analysis after ``max_age_days`` is marked task-processed with a
    WARNING, so a permanently failing analysis cannot be retried without
    bound. Undatable rows are left alone.

    Each channel is guarded separately — a storage helper that raises
    (an older DB missing a column, say) must not take the other channel
    or the email pass down with it.

    Returns ``{"expired_whatsapp": int, "expired_calendar": int}``.
    """
    out = {"expired_whatsapp": 0, "expired_calendar": 0}

    try:
        wa_rows = store.get_unprocessed_whatsapp_messages_for_task(owner_id)
    except Exception as e:
        logger.warning(f"[hygiene] WhatsApp backlog read failed, skipping: {e}")
        wa_rows = []
    for row in wa_rows:
        msg_id = row.get("id") or ""
        if not msg_id:
            continue
        age_days = _row_age_days(row, now)
        if age_days is not None and age_days > max_age_days:
            store.mark_whatsapp_task_processed(owner_id, msg_id)
            out["expired_whatsapp"] += 1
            logger.warning(
                f"[hygiene] expired unanalyzed WhatsApp message {msg_id} "
                f"chat={row.get('chat_jid')} timestamp={row.get('timestamp')} "
                f"— marked after {max_age_days:g} days"
            )

    try:
        cal_rows = store.get_unprocessed_calendar_events_for_task(owner_id)
    except Exception as e:
        logger.warning(f"[hygiene] calendar backlog read failed, skipping: {e}")
        cal_rows = []
    for row in cal_rows:
        event_id = row.get("id") or ""
        if not event_id:
            continue
        age_days = _row_age_days(row, now)
        if age_days is not None and age_days > max_age_days:
            store.mark_calendar_event_task_processed(owner_id, event_id)
            out["expired_calendar"] += 1
            logger.warning(
                f"[hygiene] expired unanalyzed calendar event {event_id} "
                f"summary={row.get('summary')} start_time={row.get('start_time')} "
                f"— marked after {max_age_days:g} days"
            )

    logger.debug(
        f"[hygiene] expire_stale_channel_backlog(owner_id={owner_id}, "
        f"max_age_days={max_age_days}) -> {out}"
    )
    return out
