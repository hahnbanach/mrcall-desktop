"""JSON-RPC method handlers for the Zylch sidecar.

Each handler is an async callable `(params: dict, notify: Callable) -> Any`.
- `params` is the JSON-RPC `params` object (already defaulted to {}).
- `notify(method, params)` emits a JSON-RPC notification to stdout.
- The return value becomes the `result` field of the response.

All handlers log at DEBUG to the log file (not stdout — stdout is the wire).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


# ─── Solve state ─────────────────────────────────────────────
# Single-user, single-process: only one solve can run at a time.
_solve_lock = asyncio.Lock()
_active_executor = None  # type: Optional[Any]


class SolveInProgressError(Exception):
    """Raised when a second tasks.solve starts while one is running."""

    code = -32000


class ChatBusyError(Exception):
    """Raised when a chat.send arrives for a conversation whose previous
    turn is still awaiting approval."""

    code = -32001


# ─── Chat approval state ─────────────────────────────────────
# tool_use_id -> Future[bool] (resolved by chat.approve)
_pending_approvals: Dict[str, asyncio.Future] = {}
# conversation_id -> asyncio.Task running the current chat.send
_active_chats: Dict[str, asyncio.Task] = {}
# conversation_id -> set[tool_name] of tools auto-approved for the rest of
# this conversation. Populated when the user picks "Allow for session" on
# an approval prompt; consulted before notifying the desktop.
_session_auto_approvals: Dict[str, set] = {}
# tool_use_id -> (conversation_id, tool_name). Populated when we notify
# the desktop of a pending approval; used by chat.approve to attribute a
# "session" grant to the right conversation + tool without trusting the
# client to send them again.
_approval_meta: Dict[str, tuple] = {}


def _should_auto_approve(conversation_id: str, tool_name: str) -> bool:
    """Return True if `tool_name` was whitelisted for `conversation_id`
    via a prior `chat.approve(mode="session")`.
    """
    allowed = _session_auto_approvals.get(conversation_id)
    return bool(allowed and tool_name in allowed)


def _approval_preview(tool_name: str, tool_input: Dict[str, Any]) -> str:
    """Build a short, human-friendly preview string (<500 chars, no full body)."""
    try:
        from zylch.services.task_executor import format_approval_preview

        preview = format_approval_preview(tool_name, tool_input)
    except Exception:
        preview = f"{tool_name}: keys={list((tool_input or {}).keys())}"
    if preview and len(preview) > 500:
        preview = preview[:497] + "..."
    return preview


def _owner_id() -> str:
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


# ─── Tasks ───────────────────────────────────────────────────


async def tasks_list(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """tasks.list(include_completed=False, include_skipped=False,
    limit=200) -> list of task dicts."""
    from zylch.storage.storage import Storage

    include_completed = bool(params.get("include_completed", False))
    include_skipped = bool(params.get("include_skipped", False))
    limit = int(params.get("limit", 200))
    owner_id = _owner_id()
    logger.debug(
        f"[rpc] tasks.list owner_id={owner_id} "
        f"include_completed={include_completed} "
        f"include_skipped={include_skipped} limit={limit}"
    )

    store = Storage.get_instance()
    tasks = store.get_task_items(
        owner_id=owner_id,
        limit=limit,
        include_completed=include_completed,
    )
    if not include_skipped:
        tasks = [t for t in tasks if not (t.get("sources") or {}).get("skipped_at")]
    logger.debug(f"[rpc] tasks.list -> {len(tasks)} tasks")
    return tasks


async def tasks_complete(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """tasks.complete(task_id, note?) -> {ok: bool}.

    `note` is an optional free-text closing reason. Stored on
    `task_items.close_note` and shown next to the task in the
    Closed view; never injected into any LLM prompt.
    """
    from zylch.storage.storage import Storage

    task_id = params.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")

    raw_note = params.get("note")
    note: str | None
    if raw_note is None:
        note = None
    elif isinstance(raw_note, str):
        note = raw_note
    else:
        raise ValueError("note must be a string when provided")

    owner_id = _owner_id()
    logger.debug(
        f"[rpc] tasks.complete owner_id={owner_id} task_id={task_id} "
        f"note_len={len(note) if note else 0}"
    )
    store = Storage.get_instance()
    ok = store.complete_task_item(owner_id=owner_id, task_id=task_id, note=note)
    logger.debug(f"[rpc] tasks.complete -> {ok}")
    return {"ok": bool(ok)}


async def tasks_reopen(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """tasks.reopen(task_id) -> {ok: bool}.

    Clears `completed_at` so a closed task is open again. Mirrors
    tasks.complete.
    """
    from zylch.storage.storage import Storage

    task_id = params.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")

    owner_id = _owner_id()
    logger.debug(f"[rpc] tasks.reopen owner_id={owner_id} task_id={task_id}")
    store = Storage.get_instance()
    ok = store.reopen_task_item(owner_id=owner_id, task_id=task_id)
    logger.debug(f"[rpc] tasks.reopen -> {ok}")
    return {"ok": bool(ok)}


async def tasks_pin(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """tasks.pin(task_id, pinned: bool) -> {ok: bool}.

    Toggles the pinned flag on a task. Pinned tasks float to the top of
    `tasks.list` regardless of urgency.
    """
    from zylch.storage.storage import Storage

    task_id = params.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")
    if "pinned" not in params:
        raise ValueError("pinned is required")
    pinned = bool(params.get("pinned"))

    owner_id = _owner_id()
    logger.debug(f"[rpc] tasks.pin owner_id={owner_id} task_id={task_id} pinned={pinned}")
    store = Storage.get_instance()
    ok = store.set_task_pinned(owner_id=owner_id, task_id=task_id, pinned=pinned)
    logger.debug(f"[rpc] tasks.pin -> {ok}")
    return {"ok": bool(ok)}


async def tasks_skip(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """tasks.skip(task_id) -> {ok: bool}.

    Non-destructive: stores `skipped_at` ISO timestamp inside the
    existing `sources` JSON field. Skipped tasks are filtered out
    of `tasks.list` unless `include_skipped=True`.
    """
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem

    task_id = params.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")
    owner_id = _owner_id()
    logger.debug(f"[rpc] tasks.skip owner_id={owner_id} task_id={task_id}")

    try:
        with get_session() as session:
            task = (
                session.query(TaskItem)
                .filter(
                    TaskItem.id == task_id,
                    TaskItem.owner_id == owner_id,
                )
                .one_or_none()
            )
            if task is None:
                return {"ok": False, "error": "task not found"}
            sources = dict(task.sources or {})
            sources["skipped_at"] = datetime.now(timezone.utc).isoformat()
            task.sources = sources
            session.flush()
    except Exception as e:
        logger.exception(f"[rpc] tasks.skip failed for {task_id}")
        return {"ok": False, "error": str(e)}
    return {"ok": True}


# ─── Solve ───────────────────────────────────────────────────


async def tasks_reanalyze(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """tasks.reanalyze(task_id) -> {ok, action, reason, task_id}.

    Forces an LLM re-evaluation of a single open task using the latest
    thread history. Applies the decision to storage:
      - action='close'  -> sets completed_at = now() (returned as 'closed')
      - action='update' -> updates urgency/suggested_action/reason (returned
        as 'updated')
      - action='keep'   -> no DB change (returned as 'kept')

    Reuses the exact same thread history builder as the task worker.
    """
    from zylch.workers.task_reanalyze import reanalyze_task

    task_id = params.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")

    owner_id = _owner_id()
    logger.debug(f"[rpc] tasks.reanalyze owner_id={owner_id} task_id={task_id}")
    result = await reanalyze_task(task_id=task_id, owner_id=owner_id)
    logger.debug(f"[rpc] tasks.reanalyze -> {result}")
    return result


async def tasks_solve(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """tasks.solve(task_id, instructions="") — streams `tasks.solve.event`
    notifications; pauses on tool approval (waits for tasks.solve.approve).
    Returns {ok, result} when done.
    """
    from zylch.llm.client import LLMClient
    from zylch.services.solve_constants import (
        SOLVE_SYSTEM_PROMPT,
        SOLVE_TOOLS,
        build_task_context,
        get_personal_data_section,
    )
    from zylch.services.task_executor import TaskExecutor
    from zylch.storage.storage import Storage

    global _active_executor

    task_id = params.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")
    instructions = params.get("instructions", "") or ""

    if _solve_lock.locked():
        # Match JSON-RPC error path via custom exception code.
        raise SolveInProgressError("solve already in progress")

    async with _solve_lock:
        owner_id = _owner_id()
        logger.debug(
            f"[rpc] tasks.solve owner_id={owner_id} task_id={task_id} "
            f"instructions_len={len(instructions)}"
        )

        store = Storage.get_instance()
        # Fetch task
        tasks = store.get_task_items(owner_id=owner_id, limit=1000)
        task = next((t for t in tasks if t.get("id") == task_id), None)
        if task is None:
            return {"ok": False, "error": "task not found"}

        context = build_task_context(task, store, owner_id)
        user_email = os.environ.get("EMAIL_ADDRESS", "")
        user_name = user_email.split("@")[0] if user_email else "the user"

        api_key = (
            os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("LLM_API_KEY")
            or ""
        )
        provider = os.environ.get("LLM_PROVIDER", "anthropic")
        client = LLMClient(api_key=api_key, provider=provider)
        system = SOLVE_SYSTEM_PROMPT.format(
            user_name=user_name,
            personal_data_section=get_personal_data_section(owner_id=owner_id),
        )

        user_msg = (
            f"Solve this task. Use tools to research if needed,"
            f" then propose a concrete solution.\n\n{context}"
        )
        if instructions.strip():
            user_msg += f"\n\nUser instructions: {instructions}"
        messages = [{"role": "user", "content": user_msg}]

        executor = TaskExecutor(
            client,
            system,
            messages,
            store,
            owner_id,
            SOLVE_TOOLS,
        )
        _active_executor = executor
        try:
            final: Dict[str, Any] = {}
            async for event in executor.run():
                # Forward event as a notification; omit tool_input
                # contents for pending events if they look sensitive
                # (we still send preview text).
                logger.debug(f"[rpc] tasks.solve.event type={event.get('type')}")
                notify("tasks.solve.event", event)
                if event["type"] == "done":
                    final = {"ok": True, "result": event["result"]}
                    break
                if event["type"] == "error":
                    final = {"ok": False, "error": event["message"]}
                    break
            return final or {"ok": False, "error": "stream ended"}
        finally:
            _active_executor = None


async def tasks_solve_approve(
    params: Dict[str, Any],
    notify: NotifyFn,
) -> Any:
    """tasks.solve.approve(tool_use_id, approved, edited_input=None)."""
    tool_use_id = params.get("tool_use_id")
    approved = bool(params.get("approved", False))
    edited_input = params.get("edited_input")
    if not tool_use_id:
        raise ValueError("tool_use_id is required")
    logger.debug(
        f"[rpc] tasks.solve.approve tool_use_id={tool_use_id} "
        f"approved={approved} has_edit={edited_input is not None}"
    )
    ex = _active_executor
    if ex is None:
        return {"ok": False, "error": "no active solve"}
    ok = await ex.approve(tool_use_id, approved, edited_input)
    return {"ok": bool(ok)}


# ─── Chat ────────────────────────────────────────────────────


async def chat_send(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """chat.send(message, conversation_history=[], conversation_id="general",
    context={}) -> ChatService result dict.

    Destructive tools trigger `chat.pending_approval` notifications; the
    client must respond via `chat.approve` to resume.
    """
    from zylch.services.chat_service import ChatService

    message = params.get("message")
    if not message:
        raise ValueError("message is required")
    conversation_history = params.get("conversation_history") or []
    conversation_id = str(params.get("conversation_id") or "general")
    req_context = params.get("context") or {}
    if not isinstance(req_context, dict):
        req_context = {}

    # Concurrency guard per conversation_id
    existing = _active_chats.get(conversation_id)
    if existing is not None and not existing.done():
        raise ChatBusyError("chat busy, approve or decline pending action first")

    owner_id = _owner_id()
    logger.debug(
        f"[rpc] chat.send owner_id={owner_id} "
        f"conversation_id={conversation_id} "
        f"message_len={len(message)} "
        f"history_len={len(conversation_history)} "
        f"has_context={bool(req_context)}"
    )

    # Optional context notification (confirms task scoping to the UI)
    task_id = req_context.get("task_id") if isinstance(req_context, dict) else None
    if task_id:
        try:
            notify(
                "chat.context",
                {
                    "conversation_id": conversation_id,
                    "task_id": task_id,
                },
            )
        except Exception as e:
            logger.warning(f"[rpc] chat.context notify failed: {e}")

    async def approval_callback(
        tool_use_id: str,
        tool_name: str,
        tool_input: Dict[str, Any],
    ) -> bool:
        # Session-level auto-approval: if the user previously picked
        # "Allow for session" on this tool in this conversation, skip the
        # prompt entirely.
        if _should_auto_approve(conversation_id, tool_name):
            logger.debug(
                f"[approval] auto-approved by session: tool={tool_name} " f"conv={conversation_id}"
            )
            return True

        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        _pending_approvals[tool_use_id] = fut
        # Remember which conversation owns this tool_use so chat.approve
        # can attribute a session-mode grant to the right conversation.
        _approval_meta[tool_use_id] = (conversation_id, tool_name)
        preview = _approval_preview(tool_name, tool_input)
        try:
            input_keys = list((tool_input or {}).keys())
        except Exception:
            input_keys = []
        logger.debug(
            f"[rpc] chat.pending_approval conversation_id={conversation_id} "
            f"tool_use_id={tool_use_id} tool={tool_name} keys={input_keys}"
        )
        try:
            notify(
                "chat.pending_approval",
                {
                    "conversation_id": conversation_id,
                    "tool_use_id": tool_use_id,
                    "name": tool_name,
                    "input": tool_input,
                    "preview": preview,
                },
            )
        except Exception as e:
            logger.warning(f"[rpc] pending_approval notify failed: {e}")
        try:
            approved = await asyncio.wait_for(fut, timeout=600)
        except asyncio.TimeoutError:
            logger.warning(f"[rpc] approval timeout tool_use_id={tool_use_id}")
            if not fut.done():
                fut.cancel()
            approved = False
        finally:
            _pending_approvals.pop(tool_use_id, None)
            _approval_meta.pop(tool_use_id, None)
        logger.debug(f"[approval] tool={tool_name} approved={approved}")
        return bool(approved)

    service = ChatService()

    async def _run():
        return await service.process_message(
            user_message=message,
            user_id=owner_id,
            conversation_history=conversation_history,
            context=req_context,
            approval_callback=approval_callback,
        )

    task = asyncio.create_task(_run())
    _active_chats[conversation_id] = task
    try:
        result = await task
    finally:
        if _active_chats.get(conversation_id) is task:
            _active_chats.pop(conversation_id, None)

    logger.debug("[rpc] chat.send -> result keys=%s", list(result.keys()))
    return result


async def chat_approve(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """chat.approve(tool_use_id, mode | approved) -> {ok: true}.

    Three modes:
      - "once"    -> approve only this single tool call (default).
      - "session" -> approve this call AND auto-approve future calls to
                     the same tool_name within the same conversation.
      - "deny"    -> reject this single tool call.

    Back-compat: if `mode` is absent, the legacy `approved: bool` is
    honored (`true` -> "once", `false` -> "deny").

    Unknown tool_use_id -> ValueError (maps to JSON-RPC -32602 via
    server's INVALID_PARAMS handling).
    """
    tool_use_id = params.get("tool_use_id")
    if not tool_use_id:
        raise ValueError("tool_use_id is required")

    mode = params.get("mode")
    if mode is None:
        # Legacy path: `approved: bool`.
        mode = "once" if bool(params.get("approved", False)) else "deny"
    if mode not in ("once", "session", "deny"):
        err = ValueError(f"invalid mode: {mode!r} (expected once|session|deny)")
        err.code = -32602  # type: ignore[attr-defined]
        raise err

    approved = mode in ("once", "session")
    logger.debug(
        f"[rpc] chat.approve tool_use_id={tool_use_id} mode={mode} " f"approved={approved}"
    )

    fut = _pending_approvals.pop(tool_use_id, None)
    meta = _approval_meta.pop(tool_use_id, None)
    if fut is None:
        err = ValueError(f"no pending approval for tool_use_id={tool_use_id}")
        err.code = -32602  # type: ignore[attr-defined]
        raise err

    if mode == "session" and meta is not None:
        conv_id, tool_name = meta
        allowed = _session_auto_approvals.setdefault(conv_id, set())
        allowed.add(tool_name)
        logger.debug(f"[approval] session-approval added: conv={conv_id} " f"tool={tool_name}")

    if not fut.done():
        fut.set_result(approved)
    return {"ok": True}


# ─── Update ──────────────────────────────────────────────────


def _task_change_key(task: Dict[str, Any]) -> str:
    """Return the field used to detect whether an open task was touched by
    the pipeline. `TaskItem` has no `updated_at` column; `analyzed_at`
    is rewritten each time the analyzer revisits a thread, so it is
    the de-facto 'last changed' marker.
    """
    return str(task.get("analyzed_at") or "")


def _estimate_update_eta(store, owner_id: str) -> str:
    """Rough human-readable ETA for update.run based on how many emails
    the pipeline will have to touch.

    The real per-email time dominates: IMAP fetch + 2 LLM passes
    (memory extraction, task detection). On a typical run each email
    costs somewhere between 1 and 3 seconds wall clock. We don't try
    to be precise — a coarse bucket is enough for the user to decide
    whether to wait or go do something else.
    """
    from sqlalchemy import or_

    from zylch.storage.database import get_session
    from zylch.storage.models import Email

    try:
        with get_session() as session:
            # Pending = not yet memory-extracted OR not yet task-analyzed.
            pending = (
                session.query(Email)
                .filter(Email.owner_id == owner_id)
                .filter(
                    or_(
                        Email.memory_processed_at.is_(None),
                        Email.task_processed_at.is_(None),
                    )
                )
                .count()
            )
            # If the local store is empty this is a first-time sync: IMAP
            # will pull the whole window (default 60 days) before the
            # pipeline even starts counting, so nudge the estimate up.
            total = session.query(Email).filter(Email.owner_id == owner_id).count()
    except Exception as e:
        logger.warning(f"[rpc] update ETA calc failed: {e}")
        return "unknown"

    first_run_bump = 0
    if total == 0:
        # Assume ~25 emails/day on a typical business inbox × 60 days.
        first_run_bump = 1500

    load = pending + first_run_bump
    if load < 20:
        return "under 1 minute"
    if load < 100:
        return "2-5 minutes"
    if load < 500:
        return "15-30 minutes"
    if load < 2000:
        return "1-2 hours"
    return "2+ hours (first sync — grab a coffee)"


def _truncate(s: Any, n: int) -> str:
    s = "" if s is None else str(s)
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def _format_task_line(task: Dict[str, Any]) -> str:
    """One bullet: **Contact**: reason (id prefix)."""
    contact = task.get("contact_name") or task.get("contact_email") or "(unknown)"
    reason = _truncate(task.get("reason") or task.get("suggested_action") or "", 200)
    task_id = str(task.get("id") or "")
    id_prefix = task_id[:8] if task_id else ""
    suffix = f" ({id_prefix})" if id_prefix else ""
    return f"- **{contact}**: {reason}{suffix}"


def build_update_diff_summary(
    before_open: Dict[str, str],
    after_open_by_id: Dict[str, Dict[str, Any]],
    closed_after: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the markdown summary + machine-readable diff for `update.run`.

    Args:
        before_open: {task_id: analyzed_at_iso} of tasks open BEFORE the
            pipeline ran.
        after_open_by_id: {task_id: task_dict} of tasks still open AFTER
            the pipeline.
        closed_after: {task_id: task_dict} of tasks that were in
            `before_open` but are now completed.

    Returns:
        {"summary": markdown, "updated_tasks": {"created": [...],
         "closed": [...], "updated": [...]}}
    """
    before_ids = set(before_open.keys())
    after_ids = set(after_open_by_id.keys())

    created_ids = sorted(after_ids - before_ids)
    closed_ids = sorted(closed_after.keys())
    updated_ids = sorted(
        tid
        for tid in (before_ids & after_ids)
        if _task_change_key(after_open_by_id[tid]) != before_open.get(tid, "")
    )

    created_tasks = [after_open_by_id[tid] for tid in created_ids]
    closed_tasks = [closed_after[tid] for tid in closed_ids]
    updated_tasks = [after_open_by_id[tid] for tid in updated_ids]

    if not created_ids and not closed_ids and not updated_ids:
        summary = "**Update complete**\n\nNo changes this run."
    else:
        parts: list[str] = ["**Update complete**"]
        if created_tasks:
            parts.append("")
            parts.append(f"🆕 Created ({len(created_tasks)}):")
            parts.extend(_format_task_line(t) for t in created_tasks)
        if closed_tasks:
            parts.append("")
            parts.append(f"✅ Closed ({len(closed_tasks)}):")
            parts.extend(_format_task_line(t) for t in closed_tasks)
        if updated_tasks:
            parts.append("")
            parts.append(f"✏️ Updated ({len(updated_tasks)}):")
            parts.extend(_format_task_line(t) for t in updated_tasks)
        summary = "\n".join(parts)

    return {
        "summary": summary,
        "updated_tasks": {
            "created": created_ids,
            "closed": closed_ids,
            "updated": updated_ids,
        },
    }


async def update_run(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """update.run() -> pipeline result with a DIFF summary.

    Mirrors the CLI `zylch update` path: calls
    `process_pipeline.handle_process([], config, owner_id)`, but
    replaces the inner "dump every open task" summary with a diff of
    THIS run (tasks created / closed / updated since we started).

    Emits coarse `update.progress` notifications at start (0%) and end
    (100%).

    Return shape:
        {
            "success": True,
            "summary": "<markdown diff>",
            "updated_tasks": {"created": [...], "closed": [...],
                              "updated": [...]},
        }
    """
    from zylch.services.process_pipeline import handle_process
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem
    from zylch.storage.storage import Storage
    from zylch.tools.config import ToolConfig

    owner_id = _owner_id()
    logger.debug(f"[rpc] update.run owner_id={owner_id}")

    email_addr = os.environ.get("EMAIL_ADDRESS", "")
    email_pass = os.environ.get("EMAIL_PASSWORD", "")
    if not email_addr or not email_pass:
        raise RuntimeError("Email not configured for this profile — run `zylch init`.")

    def _emit(pct: int, message: str) -> None:
        try:
            notify(
                "update.progress",
                {"pct": int(pct), "message": str(message)},
            )
        except Exception as e:
            logger.warning(f"[rpc] update.progress notify failed: {e}")

    store = Storage.get_instance()

    # ── Snapshot BEFORE ──────────────────────────────────────
    # Map {task_id: analyzed_at} of currently-open tasks. We use
    # `analyzed_at` as the change-marker because `TaskItem` has no
    # `updated_at` column and `analyzed_at` is rewritten on every
    # re-analysis of the underlying thread.
    try:
        before_tasks = store.get_task_items(owner_id=owner_id, limit=10000)
        before_open: Dict[str, str] = {
            str(t.get("id")): _task_change_key(t) for t in before_tasks if t.get("id")
        }
    except Exception as e:
        logger.warning(f"[rpc] update.run: before-snapshot failed, diff will be empty: {e}")
        before_open = {}

    # Rough ETA from the number of emails the pipeline will have to
    # touch (unprocessed memory + unprocessed tasks). Not a real
    # estimator — just enough to tell the user "quick" vs "go walk
    # the dog" vs "first sync, clear your afternoon".
    eta_text = _estimate_update_eta(store, owner_id)
    try:
        notify(
            "update.progress",
            {"pct": 0, "message": "Starting full pipeline…", "eta": eta_text},
        )
    except Exception as e:
        logger.warning(f"[rpc] update.progress eta notify failed: {e}")

    # Run the pipeline in a worker thread with its own event loop. The
    # pipeline is declared async but internally does blocking work
    # (IMAP, SQLAlchemy sync, FTS) that would otherwise starve the
    # RPC server's main loop — meaning settings.schema, tasks.list,
    # etc. can't respond for the 2+ minutes update.run takes. With
    # to_thread the main loop stays free. process_pipeline.console now
    # writes to stderr, so we no longer need to swap sys.stdout.
    try:
        config = ToolConfig.from_settings()
        # We intentionally discard the inner summary — it is the full
        # open-tasks dump we are replacing with the diff below.
        await asyncio.to_thread(asyncio.run, handle_process([], config, owner_id))
    except Exception as e:
        logger.exception("[rpc] update.run failed")
        _emit(100, f"Failed: {e}")
        raise

    # ── Snapshot AFTER ───────────────────────────────────────
    try:
        after_tasks = store.get_task_items(owner_id=owner_id, limit=10000)
        after_open_by_id: Dict[str, Dict[str, Any]] = {
            str(t.get("id")): t for t in after_tasks if t.get("id")
        }
    except Exception as e:
        logger.warning(f"[rpc] update.run: after-snapshot failed: {e}")
        after_open_by_id = {}

    # Tasks that were open before but no longer appear in the open list
    # — either completed or hard-deleted. Fetch those rows directly so
    # we can present their contact/reason in the "Closed" section.
    closed_after: Dict[str, Dict[str, Any]] = {}
    missing_from_after = [tid for tid in before_open if tid not in after_open_by_id]
    if missing_from_after:
        try:
            with get_session() as session:
                rows = (
                    session.query(TaskItem)
                    .filter(
                        TaskItem.owner_id == owner_id,
                        TaskItem.id.in_(missing_from_after),
                        TaskItem.completed_at.isnot(None),
                    )
                    .all()
                )
                for r in rows:
                    d = r.to_dict()
                    tid = str(d.get("id") or "")
                    if tid:
                        closed_after[tid] = d
        except Exception as e:
            logger.warning(f"[rpc] update.run: closed-lookup failed: {e}")

    diff = build_update_diff_summary(before_open, after_open_by_id, closed_after)
    _emit(100, "Done")

    logger.debug(
        "[rpc] update.run -> diff created=%d closed=%d updated=%d",
        len(diff["updated_tasks"]["created"]),
        len(diff["updated_tasks"]["closed"]),
        len(diff["updated_tasks"]["updated"]),
    )
    return {
        "success": True,
        "summary": diff["summary"],
        "updated_tasks": diff["updated_tasks"],
    }


# ─── Narration ───────────────────────────────────────────────


async def narration_summarize(
    params: Dict[str, Any],
    notify: NotifyFn,
) -> Any:
    """narration.summarize(lines, context="") -> {"text": str}.

    Summarizes recent sidecar stderr lines into a short first-person
    Italian sentence using Haiku, for display while a chat.send is
    in flight. Never raises; returns {"text": ""} on any failure.
    """
    import re

    lines = params.get("lines") or []
    context = params.get("context") or ""
    if not isinstance(lines, list) or not lines:
        return {"text": ""}

    # Layer 1 — pre-filter locally: drop init/startup/technical log lines
    # before paying for a Haiku call. These produce narrations like "Sto
    # inizializzando il client LLM…" which are noise to the user.
    init_patterns = [
        re.compile(r"initiali[sz]ing", re.IGNORECASE),
        re.compile(r"\bstart(?:ing|up)\b", re.IGNORECASE),
        re.compile(r"connect(?:ing|ed)\s+to", re.IGNORECASE),
        re.compile(r"loading\s+model", re.IGNORECASE),
        re.compile(r"spawn(?:ed|ing)", re.IGNORECASE),
        re.compile(r"asyncio\."),
        re.compile(r"\[rpc\]\s+server\s+(?:start|listening)", re.IGNORECASE),
        re.compile(r"\bPRAGMA\b"),
        re.compile(r"\bSELECT\s"),
        re.compile(r"__init__"),
    ]

    ansi = re.compile(r"\x1b\[[0-9;]*m")
    cleaned = []
    for ln in lines[-20:]:
        s = ansi.sub("", str(ln)).strip()
        if not s:
            continue
        if " DEBUG " in s:
            continue
        if any(p.search(s) for p in init_patterns):
            continue
        cleaned.append(s[:300])
    if not cleaned:
        return {"text": ""}

    joined = "\n".join(cleaned)
    # Layer 2 — tighter Haiku prompt: explicitly tell the model to ignore
    # any remaining setup/SQL/startup noise and only narrate user-visible
    # actions.
    system = (
        "Riassumi in una singola frase in italiano, in prima persona, "
        "al presente, max 80 caratteri, cosa Zylch sta facendo adesso "
        "in base alle righe di log fornite. Parla come Zylch stesso "
        "('Sto scaricando…', 'Sto cercando…', 'Sto componendo l'email…')."
        " Ignora righe di log di inizializzazione, startup, loading, "
        "connessione, query SQL interne. Concentrati SOLO su azioni "
        "concrete che l'utente può capire: scaricare, cercare, inviare, "
        "leggere, firmare. Se le righe contengono solo setup tecnico, "
        "rispondi con 'Sto pensando alla tua richiesta.' (esatto). "
        " Se vedi un errore o warning importante, dillo in modo empatico "
        "e breve. Se non c'è niente di significativo, rispondi con una "
        "stringa vuota. Non aggiungere virgolette, prefissi, o spiegazioni."
    )
    if context:
        user = f"Contesto utente: {context[:200]}\n\n" f"Ultime righe di log:\n{joined}"
    else:
        user = f"Ultime righe di log:\n{joined}"

    try:
        from zylch.config import settings
        from zylch.llm.client import LLMClient

        api_key = getattr(settings, "anthropic_api_key", None)
        if not api_key:
            return {"text": ""}

        client = LLMClient(
            api_key=api_key,
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
        )
        resp = await asyncio.to_thread(
            client.create_message_sync,
            messages=[{"role": "user", "content": user}],
            system=system,
            max_tokens=60,
        )
        text = ""
        if resp.content:
            blk = resp.content[0]
            text = getattr(blk, "text", "") or ""
        text = text.strip().strip("\"'").strip()
        logger.debug(f"[rpc] narration.summarize -> {text!r}")
        return {"text": text}
    except Exception as e:
        logger.warning(f"[rpc] narration.summarize failed: {e}")
        return {"text": ""}


# ─── Emails ──────────────────────────────────────────────────


async def emails_list_by_thread(
    params: Dict[str, Any],
    notify: NotifyFn,
) -> Any:
    """emails.list_by_thread(thread_id) -> {"emails": [...]}.

    Returns the full thread in chronological order (date ASC) with a
    provider-uniform shape. Dispatch:
      - provider == 'imap'      -> local DB (Email table)
      - provider == 'google'    -> GmailClient.threads.get (not available
                                    in standalone repo; returns error)
      - provider == 'microsoft' -> not implemented
    """
    from zylch.api.token_storage import get_email, get_provider
    from zylch.storage.storage import Storage
    from zylch.workers.thread_presenter import strip_quoted

    thread_id = params.get("thread_id")
    if not thread_id:
        raise ValueError("thread_id is required")

    owner_id = _owner_id()
    provider = get_provider(owner_id)
    user_email = (get_email(owner_id) or "").lower()
    logger.debug(
        f"[rpc] emails.list_by_thread owner_id={owner_id} "
        f"provider={provider} thread_id={thread_id}"
    )

    if provider == "imap":
        store = Storage.get_instance()
        rows = store.get_thread_emails(owner_id=owner_id, thread_id=thread_id)
        out = []
        for r in rows:
            from_email = (r.get("from_email") or "").strip()
            date_val = r.get("date")
            # `to_dict()` isoformats datetime columns.
            date_iso = date_val if isinstance(date_val, str) else ""
            body_raw = r.get("body_plain") or ""
            body_clean = strip_quoted(body_raw, cap=None) if body_raw else ""
            # HTML body is returned raw: strip_quoted is a plain-text
            # heuristic and would mangle tags. The renderer sandboxes
            # the HTML inside an <iframe sandbox=""> so untrusted markup
            # can't execute scripts or navigate the host.
            body_html_raw = r.get("body_html") or ""
            # Attachment metadata persisted by IMAPClient at sync time
            # (see imap_client._extract_attachment_filenames). JSON column
            # may come back as a list or, on legacy rows, a JSON-encoded
            # string — normalize both.
            raw_attach = r.get("attachment_filenames")
            if isinstance(raw_attach, list):
                attach_names = [str(n) for n in raw_attach if n]
            elif isinstance(raw_attach, str) and raw_attach.strip():
                try:
                    import json as _json

                    decoded = _json.loads(raw_attach)
                    attach_names = (
                        [str(n) for n in decoded if n] if isinstance(decoded, list) else []
                    )
                except Exception:
                    attach_names = []
            else:
                attach_names = []
            out.append(
                {
                    "id": r.get("id") or "",
                    "from_email": from_email,
                    "from_name": r.get("from_name") or "",
                    "to_email": r.get("to_email") or "",
                    "cc_email": r.get("cc_email") or "",
                    "date": date_iso,
                    "subject": r.get("subject") or "",
                    "body_plain": body_clean,
                    "body_html": body_html_raw,
                    "is_auto_reply": bool(r.get("is_auto_reply")),
                    "is_user_sent": bool(user_email and from_email.lower() == user_email),
                    "has_attachments": bool(r.get("has_attachments")) or bool(attach_names),
                    "attachment_filenames": attach_names,
                }
            )
        logger.debug(
            f"[rpc] emails.list_by_thread -> {len(out)} emails " f"(thread_id={thread_id})"
        )
        return {"emails": out}

    if provider == "google":
        # No GmailClient module exists in the standalone repo — every
        # `from zylch.tools.gmail import GmailClient` is a broken import.
        err = ValueError("Google provider: GmailClient not available in standalone build")
        err.code = -32000  # type: ignore[attr-defined]
        raise err

    if provider == "microsoft":
        err = ValueError("Microsoft provider not implemented yet for this call")
        err.code = -32000  # type: ignore[attr-defined]
        raise err

    err = ValueError(f"Unknown provider: {provider!r}")
    err.code = -32000  # type: ignore[attr-defined]
    raise err


async def emails_list_inbox(
    params: Dict[str, Any],
    notify: NotifyFn,
) -> Any:
    """emails.list_inbox(limit=50, offset=0) -> {"threads": [...]}.

    Returns thread summaries for the desktop Email tab's Inbox. See
    `Storage.list_inbox_threads` for the precise grouping/filtering
    rules. Each thread dict carries the latest message's metadata plus
    `pinned`, `unread`, `message_count`.
    """
    from zylch.api.token_storage import get_email
    from zylch.storage.storage import Storage

    limit = int(params.get("limit", 50))
    offset = int(params.get("offset", 0))
    owner_id = _owner_id()
    user_email = (get_email(owner_id) or "").lower()
    logger.debug(
        f"[rpc] emails.list_inbox owner_id={owner_id} "
        f"limit={limit} offset={offset} user_email={'present' if user_email else 'absent'}"
    )
    store = Storage.get_instance()
    threads = store.list_inbox_threads(
        owner_id=owner_id,
        user_email=user_email,
        limit=limit,
        offset=offset,
    )
    logger.debug(f"[rpc] emails.list_inbox -> {len(threads)} threads")
    return {"threads": threads}


async def emails_list_sent(
    params: Dict[str, Any],
    notify: NotifyFn,
) -> Any:
    """emails.list_sent(limit=50, offset=0) -> {"threads": [...]}.

    Symmetric to `emails.list_inbox` but filters for threads whose
    latest email was sent by the profile owner (from_email ==
    owner_email).
    """
    from zylch.api.token_storage import get_email
    from zylch.storage.storage import Storage

    limit = int(params.get("limit", 50))
    offset = int(params.get("offset", 0))
    owner_id = _owner_id()
    user_email = (get_email(owner_id) or "").lower()
    logger.debug(
        f"[rpc] emails.list_sent owner_id={owner_id} "
        f"limit={limit} offset={offset} user_email={'present' if user_email else 'absent'}"
    )
    store = Storage.get_instance()
    threads = store.list_sent_threads(
        owner_id=owner_id,
        user_email=user_email,
        limit=limit,
        offset=offset,
    )
    logger.debug(f"[rpc] emails.list_sent -> {len(threads)} threads")
    return {"threads": threads}


async def emails_pin(
    params: Dict[str, Any],
    notify: NotifyFn,
) -> Any:
    """emails.pin(thread_id, pinned: bool) -> {ok, affected}.

    Pin is a thread-level flag stored on every row of the thread via
    `pinned_at`. `affected` is the number of rows whose pinned_at
    actually changed — re-pinning an already pinned thread returns 0.
    """
    from zylch.storage.storage import Storage

    thread_id = params.get("thread_id")
    if not thread_id:
        raise ValueError("thread_id is required")
    if "pinned" not in params:
        raise ValueError("pinned is required")
    pinned = bool(params.get("pinned"))

    owner_id = _owner_id()
    logger.debug(f"[rpc] emails.pin owner_id={owner_id} thread_id={thread_id} pinned={pinned}")
    store = Storage.get_instance()
    affected = store.set_thread_pinned(owner_id=owner_id, thread_id=thread_id, pinned=pinned)
    logger.debug(f"[rpc] emails.pin -> affected={affected}")
    return {"ok": True, "affected": int(affected)}


async def emails_mark_read(
    params: Dict[str, Any],
    notify: NotifyFn,
) -> Any:
    """emails.mark_read(thread_id) -> {ok, affected}.

    Sets `read_at = now()` on every row of the thread that doesn't
    already have one. Idempotent; fire-and-forget from the renderer
    when the user opens a thread.
    """
    from zylch.storage.storage import Storage

    thread_id = params.get("thread_id")
    if not thread_id:
        raise ValueError("thread_id is required")

    owner_id = _owner_id()
    logger.debug(f"[rpc] emails.mark_read owner_id={owner_id} thread_id={thread_id}")
    store = Storage.get_instance()
    affected = store.mark_thread_read(owner_id=owner_id, thread_id=thread_id)
    logger.debug(f"[rpc] emails.mark_read -> affected={affected}")
    return {"ok": True, "affected": int(affected)}


async def narration_predict(
    params: Dict[str, Any],
    notify: NotifyFn,
) -> Any:
    """narration.predict(message, context="") -> {"text": str}.

    Predicts in first-person Italian what Zylch is about to do, based on
    the user's message. Used as the immediate placeholder while a
    chat.send is in flight, before stderr-driven narration kicks in.
    Never raises; returns {"text": ""} on any failure.
    """
    message = params.get("message") or ""
    context = params.get("context") or ""
    if not isinstance(message, str):
        message = str(message)
    message = message.strip()
    if not message:
        return {"text": ""}

    logger.debug(
        f"[rpc] narration.predict message_len={len(message)} " f"has_context={bool(context)}"
    )

    system = (
        "You predict, in Italian first person, what Zylch is about to do "
        "based on the user's request. "
        "Respond with EXACTLY ONE Italian sentence, max 80 characters, "
        "starting with 'Sto '. "
        "Do not explain. Do not warn. Do not comment on the content. "
        "Do not analyze phishing/fraud/risk. "
        "Do not use markdown, bullets, emoji, or newlines. "
        "Do not quote the user's message. "
        "If the request is ambiguous, respond exactly: "
        "'Sto pensando alla tua richiesta.'"
    )
    user = f"Richiesta: {message[:500]}"
    if context:
        user += f"\nContesto: {context[:300]}"

    fallback = "Sto pensando alla tua richiesta."

    try:
        from zylch.config import settings
        from zylch.llm.client import LLMClient

        api_key = getattr(settings, "anthropic_api_key", None)
        if not api_key:
            return {"text": ""}

        client = LLMClient(
            api_key=api_key,
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
        )
        resp = await asyncio.to_thread(
            client.create_message_sync,
            messages=[{"role": "user", "content": user}],
            system=system,
            max_tokens=40,
            stop_sequences=["---"],
        )
        text = ""
        if resp.content:
            blk = resp.content[0]
            text = getattr(blk, "text", "") or ""

        # Post-process: first non-empty line only, strip decorations.
        raw = text
        first_line = ""
        for line in (raw or "").split("\n"):
            stripped = line.strip()
            if stripped:
                first_line = stripped
                break
        # Strip common decorations: quotes, asterisks, emoji-bullets, leading dashes
        cleaned = first_line.strip()
        for ch in ("\U0001f6a9", "\U0001f534", "\U0001f7e2", "\U0001f7e1"):
            cleaned = cleaned.replace(ch, "")
        cleaned = cleaned.strip().strip("\"'`").strip()
        # Remove leading markdown markers
        while cleaned.startswith(("**", "- ", "* ", "> ", "#")):
            if cleaned.startswith("**"):
                cleaned = cleaned[2:].strip()
            else:
                cleaned = cleaned[2:].strip()
        # Strip trailing ** if present
        if cleaned.endswith("**"):
            cleaned = cleaned[:-2].strip()
        # Safety cap
        if len(cleaned) > 100:
            cleaned = cleaned[:100].rstrip()

        # Validate: must start with "Sto " (accept case-insensitive 'sto ')
        if not cleaned or not cleaned[:4].lower().startswith("sto "):
            logger.debug(f"[rpc] narration.predict fallback: raw={raw!r} cleaned={cleaned!r}")
            return {"text": fallback}

        logger.debug(f"[rpc] narration.predict -> {cleaned!r}")
        return {"text": cleaned}
    except Exception as e:
        logger.warning(f"[rpc] narration.predict failed: {e}")
        return {"text": ""}


# ─── Settings ────────────────────────────────────────────────


async def settings_schema(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """settings.schema() -> list of field descriptors (no values)."""
    from zylch.services.settings_schema import get_schema

    schema = get_schema()
    logger.debug(f"[rpc] settings.schema -> {len(schema)} fields")
    return {"fields": schema}


async def settings_get(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """settings.get() -> {key: value} for the active profile's .env.

    Secret fields (password / api_key) are ALWAYS masked: returns
    `"<set>"` if a value is present, `""` if absent. Non-secret fields
    are returned verbatim. There is no `include_secrets` opt-out — for
    editing, the user simply types a new value to overwrite.
    """
    from zylch.services.settings_io import read_env
    from zylch.services.settings_schema import KNOWN_KEYS, SECRET_KEYS

    raw = read_env()
    out: Dict[str, str] = {}
    for key in KNOWN_KEYS:
        value = raw.get(key, "")
        if key in SECRET_KEYS:
            out[key] = "<set>" if value else ""
        else:
            out[key] = value
    # NEVER log values. Just key counts.
    masked = sum(1 for k in KNOWN_KEYS if k in SECRET_KEYS and raw.get(k))
    logger.debug(
        f"[rpc] settings.get -> {len(out)} keys, {masked} secrets masked",
    )
    return {"values": out}


_EMAIL_REGEX = None


def _is_valid_email(email: str) -> bool:
    """Lightweight email check: must contain `@` and a dotted domain.

    Deliberately permissive — RFC-strict validation belongs in the IMAP
    handshake, not in the wizard. We just want to reject obvious junk
    (empty / no `@` / no domain dot).
    """
    import re

    global _EMAIL_REGEX
    if _EMAIL_REGEX is None:
        _EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    return bool(_EMAIL_REGEX.match((email or "").strip()))


async def profiles_create(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """profiles.create(email, values) -> {ok, profile} | error.

    Creates a brand-new profile under `~/.zylch/profiles/<email>/` and
    writes the supplied `values` dict into its `.env`. Validates:
      - email shape (`@` + dotted domain)
      - profile does NOT already exist
      - all keys in `values` are part of the settings schema
      - required obligatory fields are present (LLM provider + matching
        API key + email address)

    NEVER logs values — only key names and counts.
    """
    import os

    from zylch.cli.profiles import get_profile_dir, profile_exists
    from zylch.services.settings_io import _quote
    from zylch.services.settings_schema import KNOWN_KEYS

    email = (params.get("email") or "").strip()
    values = params.get("values")

    if not isinstance(values, dict):
        err = ValueError("'values' must be an object {key: value}")
        err.code = -32602  # type: ignore[attr-defined]
        raise err

    if not _is_valid_email(email):
        err = ValueError(f"Invalid email address: {email!r}")
        err.code = -32602  # type: ignore[attr-defined]
        raise err

    if profile_exists(email):
        err = ValueError(f"Profile already exists: {email}")
        err.code = -32602  # type: ignore[attr-defined]
        raise err

    profile_dir = get_profile_dir(email)
    # Defensive: even if `.env` does not exist, the directory might (e.g.
    # a half-written previous attempt). Still treat that as "exists" so
    # we never clobber files belonging to another in-flight wizard.
    if os.path.isdir(profile_dir):
        err = ValueError(f"Profile directory already exists: {email}")
        err.code = -32602  # type: ignore[attr-defined]
        raise err

    # Validate keys against the known schema.
    cleaned: Dict[str, str] = {}
    unknown: list[str] = []
    for key, value in values.items():
        if key not in KNOWN_KEYS:
            unknown.append(key)
            continue
        if not isinstance(value, str):
            value = "" if value is None else str(value)
        cleaned[key] = value
    if unknown:
        err = ValueError(f"unknown setting keys: {sorted(unknown)}")
        err.code = -32602  # type: ignore[attr-defined]
        raise err

    # Required fields. We require provider + matching API key + the
    # email address (so the profile is actually usable). IMAP password
    # is recommended but not strictly required — the UI marks it
    # required, but server-side we let the user defer it.
    provider = cleaned.get("SYSTEM_LLM_PROVIDER", "").strip().lower()
    if provider not in ("anthropic", "openai"):
        err = ValueError("SYSTEM_LLM_PROVIDER must be 'anthropic' or 'openai'")
        err.code = -32602  # type: ignore[attr-defined]
        raise err
    if provider == "anthropic" and not cleaned.get("ANTHROPIC_API_KEY"):
        err = ValueError("ANTHROPIC_API_KEY is required when provider=anthropic")
        err.code = -32602  # type: ignore[attr-defined]
        raise err
    if provider == "openai" and not cleaned.get("OPENAI_API_KEY"):
        err = ValueError("OPENAI_API_KEY is required when provider=openai")
        err.code = -32602  # type: ignore[attr-defined]
        raise err
    if not cleaned.get("EMAIL_ADDRESS"):
        # Force the email field to match the profile name so the .env is
        # internally consistent.
        cleaned["EMAIL_ADDRESS"] = email

    logger.debug(
        f"[rpc] profiles.create email={email} keys={sorted(cleaned.keys())}",
    )

    # Create the profile directory (mode 0o700 — same as zylch init).
    try:
        os.makedirs(profile_dir, mode=0o700, exist_ok=False)
    except FileExistsError:
        err = ValueError(f"Profile directory already exists: {email}")
        err.code = -32602  # type: ignore[attr-defined]
        raise err
    except OSError as e:
        err = RuntimeError(f"Failed to create profile dir: {e}")
        raise err

    # Write `.env` directly. We deliberately do NOT call
    # `settings_io.update_env`, because that helper resolves the path
    # from the *active* profile (this RPC runs inside an existing
    # sidecar bound to a different profile). Instead we write the file
    # ourselves with the same quoting semantics.
    env_path = os.path.join(profile_dir, ".env")
    lines: list[str] = ["# Created by Zylch desktop New Profile wizard\n"]
    for key, value in cleaned.items():
        lines.append(f"{key}={_quote(value)}\n")
    fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(lines)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        # Best-effort cleanup of the partial env file + dir.
        try:
            os.unlink(env_path)
        except OSError:
            pass
        try:
            os.rmdir(profile_dir)
        except OSError:
            pass
        raise

    logger.info(
        f"[rpc] profiles.create -> created profile={email} keys={sorted(cleaned.keys())}",
    )
    return {"ok": True, "profile": email}


async def settings_update(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """settings.update(updates: {key: value}) -> {ok, applied: [keys]}.

    Validates that all keys are known (defined in the schema). Skips
    secret values that look like the unmasked placeholder `"<set>"` —
    that means the UI sent the masked value back unchanged.
    """
    from zylch.services.settings_io import update_env
    from zylch.services.settings_schema import KNOWN_KEYS, SECRET_KEYS

    updates = params.get("updates")
    if not isinstance(updates, dict):
        err = ValueError("'updates' must be an object {key: value}")
        err.code = -32602  # type: ignore[attr-defined]
        raise err

    # Filter and validate.
    cleaned: Dict[str, str] = {}
    skipped: list[str] = []
    unknown: list[str] = []
    for key, value in updates.items():
        if key not in KNOWN_KEYS:
            unknown.append(key)
            continue
        if not isinstance(value, str):
            value = "" if value is None else str(value)
        if key in SECRET_KEYS and value == "<set>":
            # UI sent the placeholder back unchanged — keep stored value.
            skipped.append(key)
            continue
        cleaned[key] = value

    if unknown:
        err = ValueError(f"unknown setting keys: {sorted(unknown)}")
        err.code = -32602  # type: ignore[attr-defined]
        raise err

    logger.debug(
        f"[rpc] settings.update keys={sorted(cleaned.keys())} "
        f"skipped_unchanged={sorted(skipped)}",
    )
    applied = update_env(cleaned)
    return {"ok": True, "applied": applied, "skipped_unchanged": skipped}


# Dispatch table — kept explicit so adding/removing methods is obvious.
METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "tasks.list": tasks_list,
    "tasks.complete": tasks_complete,
    "tasks.reopen": tasks_reopen,
    "tasks.skip": tasks_skip,
    "tasks.pin": tasks_pin,
    "tasks.reanalyze": tasks_reanalyze,
    "tasks.solve": tasks_solve,
    "tasks.solve.approve": tasks_solve_approve,
    "chat.send": chat_send,
    "chat.approve": chat_approve,
    "update.run": update_run,
    "narration.summarize": narration_summarize,
    "narration.predict": narration_predict,
    "emails.list_by_thread": emails_list_by_thread,
    "emails.list_inbox": emails_list_inbox,
    "emails.list_sent": emails_list_sent,
    "emails.pin": emails_pin,
    "emails.mark_read": emails_mark_read,
    "settings.schema": settings_schema,
    "settings.get": settings_get,
    "settings.update": settings_update,
    "profiles.create": profiles_create,
}

# Archive + soft-delete handlers live in a sibling module to keep this
# dispatcher from growing. Merged after the explicit table so a name
# collision surfaces immediately via the duplicate-key guard.
from zylch.rpc.email_actions import METHODS as _EMAIL_ACTION_METHODS  # noqa: E402

for _name, _fn in _EMAIL_ACTION_METHODS.items():
    if _name in METHODS:
        raise RuntimeError(f"Duplicate RPC method name: {_name}")
    METHODS[_name] = _fn

# Task read-only queries (thread filter for the desktop "Open from Inbox"
# flow) — same merge pattern as email_actions to keep dispatcher small.
from zylch.rpc.task_queries import METHODS as _TASK_QUERY_METHODS  # noqa: E402

for _name, _fn in _TASK_QUERY_METHODS.items():
    if _name in METHODS:
        raise RuntimeError(f"Duplicate RPC method name: {_name}")
    METHODS[_name] = _fn
