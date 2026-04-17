"""Thread presenter — shared logic for building chronological thread history.

Used by both the task worker (during analysis) and by the RPC/CLI
reanalysis entry points. Extracted out of `task_creation.py` to keep
that module from growing further and to expose the exact same
quoted-history stripping + presentation for reanalysis.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)


# Regex patterns for quoted-history stripping (module-level, compiled once)
_QUOTED_CUT_PATTERNS = [
    re.compile(r"^On .+ wrote:\s*$", re.IGNORECASE),
    re.compile(r"^Il .+ ha scritto:\s*$", re.IGNORECASE),
    re.compile(r"^From: .+$", re.IGNORECASE),
    re.compile(r"^Da: .+$", re.IGNORECASE),
    re.compile(r"^-----Original Message-----\s*$", re.IGNORECASE),
    re.compile(r"^--\s*$"),
]


def strip_quoted(body: str, cap: Optional[int] = 1500) -> str:
    """Return the new (non-quoted) content of an email body.

    Removes lines starting with '>' (quoted), truncates at the first
    quoted-history or signature marker, collapses consecutive blank
    lines. If `cap` is an int (>0), caps the output at that many
    chars; if `cap` is None, no length cap is applied.
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


def build_thread_history(
    session,
    owner_id: str,
    thread_id: str,
    user_email: str,
    exclude_email_id: Optional[str] = None,
    limit: int = 20,
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
        limit: Max emails in the thread to render (chronological).

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
        .limit(limit)
    )
    thread_emails = q.all()
    if exclude_email_id:
        thread_emails = [e for e in thread_emails if str(e.id) != str(exclude_email_id)]

    blocks: List[str] = []
    user_email_lc = (user_email or "").lower()
    for te in thread_emails:
        te_from = (te.from_email or "").lower()
        is_user = bool(user_email_lc) and te_from == user_email_lc
        role = "USER REPLY ✓" if is_user else "CONTACT"
        date_str = ""
        try:
            if te.date_timestamp:
                date_str = datetime.fromtimestamp(te.date_timestamp, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M"
                )
            else:
                date_str = (te.date or "")[:16]
        except Exception:
            date_str = te.date or ""
        body_src = te.body_plain or te.snippet or ""
        body_clean = strip_quoted(body_src, cap=1500)
        if not body_clean:
            body_clean = body_src.strip()
            if len(body_clean) > 1500:
                body_clean = body_clean[:1500].rstrip() + "…[truncated]"
        blocks.append(f"[{date_str}] {role} {te.from_email}:\n{body_clean}")

    if not blocks:
        return ""

    return "THREAD HISTORY (chronological, user replies marked with ✓):\n" + "\n\n".join(blocks)
