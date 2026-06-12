"""Thread presenter — shared logic for building chronological thread history.

Used by both the task worker (during analysis) and by the RPC/CLI
reanalysis entry points. Extracted out of `task_creation.py` to keep
that module from growing further and to expose the exact same
quoted-history stripping + presentation for reanalysis.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta as _timedelta, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

# Matches a line that STARTS with "[YYYY-MM-DD HH:MM]" or "[YYYY-MM-DD]"
# — the role-marker prefixes emitted by build_thread_history and
# build_whatsapp_thread_history. Used by `is_last_turn_user_reply` to
# find role lines without confusing them with body content; the capture
# groups feed the newest-turn timestamp comparison. Compiled once at
# module load.
_ROLE_LINE_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?\]")


# Regex patterns for quoted-history stripping (module-level, compiled once)
_QUOTED_CUT_PATTERNS = [
    re.compile(r"^On .+ wrote:\s*$", re.IGNORECASE),
    re.compile(r"^Il .+ ha scritto:\s*$", re.IGNORECASE),
    re.compile(r"^From: .+$", re.IGNORECASE),
    re.compile(r"^Da: .+$", re.IGNORECASE),
    re.compile(r"^-----Original Message-----\s*$", re.IGNORECASE),
    re.compile(r"^--\s*$"),
]


def strip_quoted(body: str, cap: Optional[int] = None) -> str:
    """Return the new (non-quoted) content of an email body.

    Removes lines starting with '>' (quoted), truncates at the first
    quoted-history or signature marker, collapses consecutive blank
    lines. If `cap` is an int (>0), caps the output at that many
    chars; if `cap` is None (default), no length cap is applied.
    """
    if not body:
        return ""
    lines = body.splitlines()
    kept: List[str] = []
    for raw in lines:
        stripped = raw.rstrip()
        if any(p.match(stripped) for p in _QUOTED_CUT_PATTERNS):
            break
        if stripped.lstrip().startswith(">"):
            continue
        kept.append(stripped)
    collapsed: List[str] = []
    prev_blank = False
    for line in kept:
        is_blank = not line.strip()
        if is_blank and prev_blank:
            continue
        collapsed.append(line)
        prev_blank = is_blank
    while collapsed and not collapsed[0].strip():
        collapsed.pop(0)
    while collapsed and not collapsed[-1].strip():
        collapsed.pop()
    result_lines = [re.sub(r"[ \t]+", " ", line) for line in collapsed]
    result = "\n".join(result_lines)
    if cap is not None and len(result) > cap:
        result = result[:cap].rstrip() + "…[truncated]"
    return result


def parse_user_aliases(raw: Optional[str]) -> "frozenset[str]":
    """Parse the ``EMAIL_ALIASES`` setting into a normalised set.

    The setting is a comma-separated free-text string; users will paste
    addresses with quirky whitespace and casing (``Jane.Doe@…``).
    Lowercases, strips, drops empties. Frozen so callers can pass it
    around without worrying about mutation.
    """
    if not raw:
        return frozenset()
    out: set[str] = set()
    for chunk in raw.split(","):
        s = chunk.strip().lower()
        if s and "@" in s:
            out.add(s)
    return frozenset(out)


def load_user_aliases_for_owner(owner_id: str) -> "frozenset[str]":
    """Best-effort fetch of the user's ``EMAIL_ALIASES`` setting.

    Reads from the same Settings layer the renderer writes through.
    Never raises — a missing setting / unbootable Settings object just
    means no aliases (degrades to the pre-2026-05-28 strict-match
    behaviour). Caller passes the result to ``build_thread_history`` /
    ``_is_user_email`` so all turns Jane sent from a secondary identity
    are marked ``USER REPLY ✓``.
    """
    try:
        import os

        from zylch.config import settings as _settings

        raw = (
            os.environ.get("EMAIL_ALIASES")
            or getattr(_settings, "email_aliases", "")
            or ""
        )
        return parse_user_aliases(raw)
    except Exception:
        logger.debug("[thread_presenter] could not load EMAIL_ALIASES — degrading to strict match")
        return frozenset()


def build_thread_history(
    session,
    owner_id: str,
    thread_id: str,
    user_email: str,
    exclude_email_id: Optional[str] = None,
    user_aliases: "Optional[frozenset[str]]" = None,
) -> str:
    """Build a THREAD HISTORY section from emails in a thread.

    Mirrors the logic in `task_creation.TaskWorker._collect` for the
    thread_history_section so reanalysis prompts share the exact same
    presentation.

    Args:
        session: Active SQLAlchemy session.
        owner_id: Owner ID.
        thread_id: Thread ID to fetch emails for.
        user_email: User's email (lowercased) — used to mark user replies.
        exclude_email_id: If set, drop this email from the history.

    Returns:
        A rendered THREAD HISTORY section, or "" if no emails.
    """
    from zylch.storage.models import Email

    if not thread_id:
        return ""

    q = (
        session.query(Email)
        .filter(
            Email.owner_id == owner_id,
            Email.thread_id == thread_id,
        )
        .order_by(Email.date_timestamp.asc())
    )
    thread_emails = q.all()
    if exclude_email_id:
        thread_emails = [e for e in thread_emails if str(e.id) != str(exclude_email_id)]

    blocks: List[str] = []
    user_email_lc = (user_email or "").lower()
    aliases = user_aliases if user_aliases is not None else frozenset()
    for te in thread_emails:
        te_from = (te.from_email or "").lower()
        # USER REPLY ✓ when the address is the profile's primary OR any
        # configured EMAIL_ALIASES entry — without alias support, Jane
        # writing from carol@example.com on a thread keyed
        # under production@example.com gets marked CONTACT and the cap +
        # close-on-user-reply rule both miss.
        is_user = bool(user_email_lc) and (
            te_from == user_email_lc or te_from in aliases
        )
        is_auto = bool(getattr(te, "is_auto_reply", False))
        # Auto-reply guard (2026-05-06): an auto-response from the
        # user's own mailbox (out-of-office, server auto-ack) is NOT
        # user engagement — must not be treated as "USER REPLY ✓" by
        # the LLM (it would close every task on a thread the user
        # never actually answered). Keep them in the history so the
        # model has context, but mark them clearly as auto.
        if is_auto:
            role = "AUTO-REPLY (system, not user engagement)"
        elif is_user:
            role = "USER REPLY ✓"
        else:
            role = "CONTACT"
        date_str = ""
        try:
            if te.date_timestamp:
                date_str = datetime.fromtimestamp(te.date_timestamp, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M"
                )
            else:
                date_str = te.date or ""
        except Exception:
            date_str = te.date or ""
        body_src = te.body_plain or te.snippet or ""
        body_clean = strip_quoted(body_src, cap=None) or body_src.strip()
        blocks.append(f"[{date_str}] {role} {te.from_email}:\n{body_clean}")

    if not blocks:
        return ""

    return (
        "THREAD HISTORY (chronological, user replies marked with ✓; "
        "AUTO-REPLY lines are server auto-acknowledgments and DO NOT "
        "count as user engagement):\n" + "\n\n".join(blocks)
    )


def build_whatsapp_thread_history(
    session,
    owner_id: str,
    chat_jid: str,
    user_email: str = "",
    days: int = 60,
) -> str:
    """Build a THREAD HISTORY section from WhatsApp messages in a chat.

    Companion of :func:`build_thread_history` for the WhatsApp channel.
    Without it, ``reanalyze_task`` on a WA task feeds the LLM the bare
    task fields with "(No thread history available)" — the model then
    reasons solely from ``created_at`` and concludes "task is N days
    old" even when the contact re-asked the same question moments ago.

    Args:
        session: Active SQLAlchemy session.
        owner_id: Owner ID.
        chat_jid: WhatsApp chat_jid (e.g. ``<digits>@lid``).
        user_email: User's email — used as the "from" label on outbound
            rows so the LLM has a stable identity for ``USER REPLY ✓``.
        days: Look-back window in days. 60d matches the email sibling
            window in ``reanalyze_task``.

    Returns:
        A rendered THREAD HISTORY section, or ``""`` if no messages.
    """
    from zylch.storage.models import WhatsAppMessage

    if not chat_jid:
        return ""

    cutoff = datetime.now(timezone.utc) - _timedelta(days=days)
    rows = (
        session.query(WhatsAppMessage)
        .filter(
            WhatsAppMessage.owner_id == owner_id,
            WhatsAppMessage.chat_jid == chat_jid,
            WhatsAppMessage.timestamp >= cutoff,
        )
        .order_by(WhatsAppMessage.timestamp.asc())
        .all()
    )
    if not rows:
        return ""

    blocks: List[str] = []
    for r in rows:
        is_user = bool(r.is_from_me)
        role = "USER REPLY ✓" if is_user else "CONTACT"
        if is_user:
            sender = user_email or "me"
        else:
            sender = (r.sender_name or "").strip() or chat_jid
        date_str = ""
        try:
            if r.timestamp:
                date_str = r.timestamp.strftime("%Y-%m-%d %H:%M")
        except Exception:
            date_str = ""
        # Prefer the transcription for voice notes (the actual content
        # the model can reason about); fall back to text; finally a
        # bracketed media placeholder so silent rows aren't dropped.
        body = (getattr(r, "transcription", None) or "").strip()
        if not body:
            body = (r.text or "").strip()
        if not body and r.media_type:
            body = f"[{r.media_type}]"
        if not body:
            continue
        blocks.append(f"[{date_str}] {role} {sender}:\n{body}")

    if not blocks:
        return ""

    return (
        "THREAD HISTORY (WhatsApp 1-on-1 chat, chronological, user "
        "replies marked with ✓):\n" + "\n\n".join(blocks)
    )


def is_last_turn_user_reply(thread_history_text: str) -> bool:
    """Tell whether the chronologically newest non-auto turn in a rendered
    thread history is the user's reply.

    The input may be a single thread OR a primary thread followed by
    ``--- RELATED THREAD ---`` sibling sections (``reanalyze_task``).
    Each section is chronological internally, but the last line of the
    TEXT belongs to whichever sibling happens to be rendered last — so
    "walk backwards, stop at the first role line" judged an arbitrary
    thread's last turn, not the newest message. Real case (2026-06-12,
    support@): a contact's fresh question in the primary thread was
    outvoted by an old user reply at the bottom of a sibling section and
    the urgency cap demoted the task to low five sweeps in a row.

    Instead, parse the bracketed timestamp on every role line and judge
    the newest non-``AUTO-REPLY`` one (server auto-acks aren't
    engagement). Same-minute ties resolve to the later line in the text
    (within a section, rendering order is chronological). Returns True
    only when that newest turn is a ``USER REPLY ✓``. Regex is
    intentional and safe here: the input is OUR OWN structured
    presentation, not free-form prose.
    """
    if not thread_history_text:
        return False
    best_key: "Optional[tuple[str, int]]" = None
    best_line: Optional[str] = None
    for idx, line in enumerate(thread_history_text.splitlines()):
        m = _ROLE_LINE_RE.match(line)
        if not m:
            continue
        if "AUTO-REPLY" in line:
            continue
        # "YYYY-MM-DD HH:MM" — ISO order == lexicographic order, so the
        # string key compares correctly; date-only lines sort as 00:00.
        ts = f"{m.group(1)} {m.group(2) or '00:00'}"
        key = (ts, idx)
        if best_key is None or key > best_key:
            best_key = key
            best_line = line
    return best_line is not None and "USER REPLY ✓" in best_line


def cap_urgency_for_silent_followup(
    urgency: Optional[str],
    thread_history_text: str,
) -> "tuple[Optional[str], bool]":
    """Cap urgency at ``low`` when the user already had the last word.

    Mario's policy (option B): a task whose latest non-auto turn is the
    user's reply is a *proactive nudge* — the contact is silent, no
    user-side action is pending. These shouldn't sit in the medium/high
    bucket next to genuinely user-blocking items. Critical and low are
    left alone (critical is reserved for fires; low is already gentle).

    Returns ``(possibly-capped urgency, whether_cap_applied)``. Callers
    that want to log the demotion in ``reason`` can use the bool flag.
    """
    if not urgency:
        return urgency, False
    if urgency.lower() not in ("medium", "high"):
        return urgency, False
    if not is_last_turn_user_reply(thread_history_text):
        return urgency, False
    return "low", True


