"""Task reanalysis — forces an LLM re-check of a single existing task.

Given a task_id, reconstructs the thread history (same presentation as
`task_creation.TaskWorker`) and asks the LLM whether the task should be
kept, closed, or updated. Applies the decision to storage.

Shared by:
- RPC method `tasks.reanalyze` (zylch/rpc/methods.py)
- CLI slash command `/update <task_id>` (REPL handler in zylch/cli/chat.py)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Reanalysis tool — deliberately a superset of task_decision in task_creation.py.
# The enum matches the spec: kept / closed / updated.
REANALYZE_TOOL = {
    "name": "reanalyze_decision",
    "description": (
        "Decide whether the existing task should be kept as-is, closed "
        "(resolved), or updated with fresh details based on the latest "
        "thread history."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["keep", "close", "update"],
                "description": (
                    "keep = nothing changed, the task is still accurate and open; "
                    "close = the task is resolved (e.g. user already replied, "
                    "thread is closed, deadline passed and no longer actionable); "
                    "update = task is still open but urgency / suggested_action / "
                    "reason need to change based on the latest thread state."
                ),
            },
            "urgency": {
                "type": "string",
                "enum": ["critical", "high", "medium", "low"],
                "description": "Only used when action=update",
            },
            "suggested_action": {
                "type": "string",
                "description": "Only used when action=update — new specific action",
            },
            "reason": {
                "type": "string",
                "description": ("Short reason explaining the decision. Always required."),
            },
        },
        "required": ["action", "reason"],
    },
}


def _resolve_thread_id(task: Dict[str, Any], session) -> Optional[str]:
    """Resolve a thread_id for a task.

    Priority:
    1. `task.sources.thread_id` (newer tasks may store it).
    2. First email in `task.sources.emails` -> `emails.thread_id`.
    """
    from zylch.storage.models import Email

    sources = task.get("sources") or {}
    tid = sources.get("thread_id") or None
    if tid:
        return tid

    emails = sources.get("emails") or []
    if not emails:
        return None
    first_email_id = emails[0]
    row = (
        session.query(Email.thread_id)
        .filter(Email.owner_id == task.get("owner_id"), Email.id == first_email_id)
        .one_or_none()
    )
    if row and row[0]:
        return row[0]
    # owner_id may not be on the dict — retry without owner_id filter
    row2 = session.query(Email.thread_id).filter(Email.id == first_email_id).one_or_none()
    if row2 and row2[0]:
        return row2[0]
    return None


def _build_user_content(
    task: Dict[str, Any],
    thread_history_section: str,
    today_str: str,
) -> str:
    """Build the user message for the reanalysis LLM call.

    Provides the existing task summary + the full thread history so the
    LLM can decide keep/close/update.
    """
    existing = (
        f"EXISTING TASK (ID: {task.get('id')}):\n"
        f"- Contact: {task.get('contact_email') or '(unknown)'}\n"
        f"- Urgency: {task.get('urgency') or '(unknown)'}\n"
        f"- Suggested action: {task.get('suggested_action') or '(empty)'}\n"
        f"- Reason: {task.get('reason') or '(empty)'}\n"
        f"- Created: {task.get('created_at') or '(unknown)'}\n"
        f"- Analyzed: {task.get('analyzed_at') or '(unknown)'}\n"
    )
    parts = [
        "You are re-evaluating an existing task in light of the latest thread "
        "history. Decide KEEP, CLOSE, or UPDATE.",
        f"Today's date: {today_str}",
        existing,
    ]
    if thread_history_section:
        parts.append(thread_history_section)
        parts.append(
            "IMPORTANT — Thread context: if the user already replied "
            "(lines marked 'USER REPLY ✓') resolving the issue, choose "
            "CLOSE. If the conversation moved on and the original suggested "
            "action is now stale, choose UPDATE with a fresh "
            "suggested_action. Otherwise choose KEEP."
        )
    else:
        parts.append(
            "(No thread history available — base decision on the existing " "task fields alone.)"
        )
    return "\n\n".join(parts)


async def reanalyze_task(
    task_id: str,
    owner_id: str,
) -> Dict[str, Any]:
    """Reanalyze a single task and apply the LLM's decision.

    Returns a dict:
      {
        "ok": bool,
        "action": "kept" | "closed" | "updated",
        "reason": str,
        "task_id": str,
        "usage": {"input_tokens": int, "output_tokens": int},
      }

    On failure returns {"ok": False, "error": "...", "task_id": task_id}.
    """
    from zylch.api.token_storage import get_active_llm_provider, get_email
    from zylch.llm import LLMClient
    from zylch.llm.providers import get_system_llm_credentials
    from zylch.storage.database import get_session
    from zylch.storage.storage import Storage
    from zylch.workers.thread_presenter import build_thread_history

    logger.debug(f"[reanalyze_task] owner_id={owner_id} task_id={task_id}")

    store = Storage.get_instance()
    tasks = store.get_task_items(owner_id=owner_id, limit=1000)
    task = next((t for t in tasks if t.get("id") == task_id), None)
    if task is None:
        logger.debug(f"[reanalyze_task] task not found task_id={task_id}")
        return {"ok": False, "error": "task not found", "task_id": task_id}

    # Resolve thread_id (sources.thread_id, else lookup via first source email)
    with get_session() as sess:
        thread_id = _resolve_thread_id({**task, "owner_id": owner_id}, sess)
        if not thread_id:
            logger.debug(f"[reanalyze_task] no thread_id resolved for task_id={task_id}")
            return {
                "ok": False,
                "error": "no thread_id",
                "task_id": task_id,
            }

        user_email = get_email(owner_id) or os.environ.get("EMAIL_ADDRESS", "")
        thread_history_section = build_thread_history(
            session=sess,
            owner_id=owner_id,
            thread_id=thread_id,
            user_email=user_email or "",
        )

    # LLM credentials (BYOK, same resolution order as /tasks)
    llm_provider, api_key = get_active_llm_provider(owner_id)
    if not api_key or not llm_provider:
        llm_provider, api_key = get_system_llm_credentials()
    if not api_key or not llm_provider:
        return {
            "ok": False,
            "error": "no LLM credentials configured",
            "task_id": task_id,
        }

    # Use the same trained system prompt as task_creation (from storage agent
    # prompts). Falls back to a minimal system if the user hasn't trained yet.
    trained = store.get_agent_prompt(owner_id, "task_email") or ""
    system_text = trained.strip() or (
        "You are an executive assistant that evaluates whether an existing "
        "task is still actionable, already done, or needs an update. Use the "
        "thread history to decide."
    )
    system = [
        {
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    user_content = _build_user_content(task, thread_history_section, today_str)

    client = LLMClient(api_key=api_key, provider=llm_provider)
    try:
        response = await client.create_message(
            system=system,
            messages=[{"role": "user", "content": user_content}],
            max_tokens=500,
            tools=[REANALYZE_TOOL],
            tool_choice={"type": "tool", "name": "reanalyze_decision"},
        )
    except Exception as e:
        logger.exception(f"[reanalyze_task] LLM call failed task_id={task_id}")
        return {"ok": False, "error": f"LLM error: {e}", "task_id": task_id}

    decision: Dict[str, Any] = {}
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == ("reanalyze_decision"):
            decision = dict(block.input or {})
            break
    if not decision:
        logger.warning(f"[reanalyze_task] no tool_use in LLM response task_id={task_id}")
        return {
            "ok": False,
            "error": "LLM returned no decision",
            "task_id": task_id,
        }

    action = (decision.get("action") or "keep").lower()
    reason = (decision.get("reason") or "").strip()
    usage = response.usage or {"input_tokens": 0, "output_tokens": 0}

    # Apply decision
    applied: str
    if action == "close":
        ok = store.complete_task_item(owner_id, task_id)
        applied = "closed" if ok else "keep"
        if not ok:
            logger.warning(f"[reanalyze_task] complete_task_item failed task_id={task_id}")
    elif action == "update":
        suggested = (decision.get("suggested_action") or "").strip() or None
        urgency = (decision.get("urgency") or "").strip().lower() or None
        ok = store.update_task_item(
            owner_id=owner_id,
            task_id=task_id,
            urgency=urgency,
            suggested_action=suggested,
            reason=reason or None,
        )
        applied = "updated" if ok else "kept"
        if not ok:
            logger.warning(f"[reanalyze_task] update_task_item failed task_id={task_id}")
    else:
        applied = "kept"

    logger.debug(
        f"[reanalyze_task] owner_id={owner_id} task_id={task_id} "
        f"llm_action={action} applied={applied} usage={usage}"
    )

    return {
        "ok": True,
        "action": applied,
        "reason": reason,
        "task_id": task_id,
        "usage": {
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
        },
    }


def resolve_task_id_prefix(
    owner_id: str,
    prefix: str,
    min_prefix_len: int = 6,
) -> Tuple[Optional[str], List[str]]:
    """Resolve a (possibly-prefix) task id to a full id.

    Returns (full_id, candidates). If an exact match is found, returns it
    immediately. Otherwise requires at least `min_prefix_len` characters and
    a unique prefix match. `candidates` is populated with all matches when
    the resolution is ambiguous (for error messages).
    """
    from zylch.storage.storage import Storage

    if not prefix:
        return None, []
    store = Storage.get_instance()
    tasks = store.get_task_items(owner_id=owner_id, limit=1000)
    # Exact match first
    for t in tasks:
        if t.get("id") == prefix:
            return prefix, [prefix]
    if len(prefix) < min_prefix_len:
        return None, []
    matches = [t.get("id") for t in tasks if (t.get("id") or "").startswith(prefix)]
    if len(matches) == 1:
        return matches[0], matches
    return None, matches


# Sync wrapper for CLI (no running loop)
def reanalyze_task_sync(task_id: str, owner_id: str) -> Dict[str, Any]:
    """Sync wrapper around `reanalyze_task` for non-async callers."""
    try:
        asyncio.get_running_loop()
        # If we're inside a running loop (shouldn't happen for CLI REPL, but
        # defensive), run in a fresh thread with its own loop.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, reanalyze_task(task_id, owner_id)).result()
    except RuntimeError:
        return asyncio.run(reanalyze_task(task_id, owner_id))
