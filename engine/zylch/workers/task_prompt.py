"""Pure prompt assembly for task detection.

Extracted from :meth:`TaskWorker._analyze_event` so the system/user split is
unit-testable and — the whole point of support-llm-cost-fix P4 / FIX 1 — so
the CACHED system block is byte-stable across different events for one owner.

Before P4 the trained prompt's ``{event_data}`` / ``{blob_context}``
placeholders were interpolated with per-email data INSIDE the block marked
``cache_control: ephemeral``. Every detection call therefore paid the 1.25x
cache-WRITE premium on a prefix that could never be re-read (the next email
has a different body → different prefix → cache miss), and the same data was
sent AGAIN in the user message. This module puts all per-event data ONLY in
the user message and keeps the system block owner-stable, so the ephemeral
cache actually hits across the batch's concurrent calls and near-in-time
ticks.

Kept deliberately pure: no DB, no ``os.environ``, no wall-clock. Everything
that varies (the trained template, the personal-data section, today's date)
is passed in by the caller.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Tuple

# Per-event placeholders: their VALUES change every email, so in the cached
# system block they become this fixed pointer and the real data rides in the
# user message. Keeping them out of the cached prefix is what makes the cache
# reusable across events.
_USER_MSG_POINTER = "(provided in the user message below)"

# {today}'s value is appended AFTER the cached block by
# zylch.llm.client._with_datetime (a separate, un-cached system text block),
# so interpolating a date here would bust the cache every calendar day for no
# benefit. Point the model at that trailing line instead.
_TODAY_POINTER = "(see the Datetime line at the end of the system prompt)"

# Placeholders replaced by the user-message pointer (each in both {x} and
# {{x}} forms — the trainer may emit either).
_PER_EVENT_PLACEHOLDERS = (
    "event_data",
    "blob_context",
    "existing_task",
    "calendar_context",
)


def _replace_both(text: str, name: str, value: str) -> str:
    """Replace both ``{name}`` and ``{{name}}`` occurrences with ``value``."""
    return text.replace("{{" + name + "}}", value).replace("{" + name + "}", value)


def build_detection_prompt(
    *,
    trained_prompt: str,
    event_type: str,
    event_data: Dict[str, Any],
    today_str: str,
    blob_context: str = "",
    existing_task_context: str = "",
    calendar_context: str = "",
    thread_history_section: str = "",
    user_email: str = "",
    personal_section: str = "",
    notifier_hint: str = "",
) -> Tuple[str, str]:
    """Return ``(system_text, user_content)`` for one detection call.

    ``system_text`` — the trained template with per-event placeholders
    (``{event_data}``, ``{blob_context}``, ``{existing_task}``,
    ``{calendar_context}``) swapped for a fixed user-message pointer,
    ``{event_type}`` / ``{user_email}`` interpolated literally (both are
    owner/profile-stable within a batch), ``{today}`` pointed at the trailing
    Datetime line, and ``personal_section`` appended. For a given
    owner+template this is BYTE-IDENTICAL across two different events, so the
    ephemeral prompt cache hits. Templates carrying NO placeholders come
    through as ``template + personal_section`` unchanged — the per-event data
    still reaches the model via ``user_content`` below, so nothing is lost.

    ``user_content`` — the per-event payload, identical to the pre-P4
    behaviour: event JSON, thread history (+ its IMPORTANT note), memory/blob
    context, existing task, calendar context; each included only when
    non-empty.

    ``notifier_hint`` — non-empty only when the sender is a recognised
    notification relay (see :mod:`zylch.utils.notifier_senders`). It asks
    the model to report the REAL correspondent on the decision tool.
    Per-event, so it belongs in ``user_content``: putting it in the
    cache-stable system block would break the ephemeral cache for every
    ordinary email.
    """
    event_data_json = json.dumps(event_data, default=str)

    # ── system block (cache-stable) ──────────────────────────────────────
    system_text = trained_prompt
    # Owner/profile-stable → safe to interpolate literally.
    system_text = _replace_both(system_text, "event_type", event_type)
    system_text = _replace_both(system_text, "user_email", user_email)
    # Per-event → fixed pointer, real value goes in user_content.
    for name in _PER_EVENT_PLACEHOLDERS:
        system_text = _replace_both(system_text, name, _USER_MSG_POINTER)
    # Date is appended after the cache breakpoint by _with_datetime.
    system_text = _replace_both(system_text, "today", _TODAY_POINTER)
    if personal_section:
        system_text += personal_section

    # ── user block (per-event) ───────────────────────────────────────────
    user_content = (
        f"Event type: {event_type}\n" f"Date: {today_str}\n" f"Event data: {event_data_json}\n"
    )
    if thread_history_section:
        user_content += f"\n{thread_history_section}\n"
        user_content += (
            "\nIMPORTANT — THREAD CONTEXT: The THREAD HISTORY above contains the FULL conversation history in chronological order, with user replies marked 'USER REPLY ✓'. "
            "Your task description MUST reflect the LATEST state of the conversation, not just this single email. "
            "If the user has already replied (look for 'USER REPLY ✓'), describe what remains to be done AFTER their reply — do NOT say the user hasn't responded. "
            "If someone proposed a meeting date and is awaiting confirmation, say 'wait for confirmation' not 'propose a date'.\n"
        )
    if notifier_hint:
        user_content += (
            f"\nSENDER IS A NOTIFICATION RELAY.\n{notifier_hint}\n"
            "Fill contact_email / contact_phone / contact_name on the "
            "task_decision tool with the REAL correspondent's details as "
            "stated in the body. Leave a field empty when the body does not "
            "state it — do not guess, and never repeat the relay address.\n"
        )
    if blob_context:
        user_content += f"\nMemory context:\n{blob_context}"
    if existing_task_context:
        user_content += f"\nExisting task:\n{existing_task_context}"
    if calendar_context:
        user_content += f"\nCalendar context:\n{calendar_context}"

    return system_text, user_content
