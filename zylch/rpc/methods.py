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
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


# ─── Solve state ─────────────────────────────────────────────
# Single-user, single-process: only one solve can run at a time.
_solve_lock = asyncio.Lock()
_active_executor = None  # type: Optional[Any]


class SolveInProgressError(Exception):
    """Raised when a second tasks.solve starts while one is running."""

    code = -32000


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
    tasks = store.get_task_items(owner_id=owner_id, limit=limit)
    if not include_skipped:
        tasks = [
            t for t in tasks
            if not (t.get("sources") or {}).get("skipped_at")
        ]
    logger.debug(f"[rpc] tasks.list -> {len(tasks)} tasks")
    return tasks


async def tasks_complete(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """tasks.complete(task_id) -> {ok: bool}."""
    from zylch.storage.storage import Storage

    task_id = params.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")

    owner_id = _owner_id()
    logger.debug(
        f"[rpc] tasks.complete owner_id={owner_id} task_id={task_id}"
    )
    store = Storage.get_instance()
    ok = store.complete_task_item(owner_id=owner_id, task_id=task_id)
    logger.debug(f"[rpc] tasks.complete -> {ok}")
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
            personal_data_section=get_personal_data_section(),
        )

        user_msg = (
            f"Solve this task. Use tools to research if needed,"
            f" then propose a concrete solution.\n\n{context}"
        )
        if instructions.strip():
            user_msg += f"\n\nUser instructions: {instructions}"
        messages = [{"role": "user", "content": user_msg}]

        executor = TaskExecutor(
            client, system, messages, store, owner_id, SOLVE_TOOLS,
        )
        _active_executor = executor
        try:
            final: Dict[str, Any] = {}
            async for event in executor.run():
                # Forward event as a notification; omit tool_input
                # contents for pending events if they look sensitive
                # (we still send preview text).
                logger.debug(
                    f"[rpc] tasks.solve.event type={event.get('type')}"
                )
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
    params: Dict[str, Any], notify: NotifyFn,
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
    """chat.send(message, conversation_history=[]) -> ChatService result dict."""
    from zylch.services.chat_service import ChatService

    message = params.get("message")
    if not message:
        raise ValueError("message is required")
    conversation_history = params.get("conversation_history") or []

    owner_id = _owner_id()
    logger.debug(
        f"[rpc] chat.send owner_id={owner_id} "
        f"message_len={len(message)} "
        f"history_len={len(conversation_history)}"
    )
    service = ChatService()
    result = await service.process_message(
        user_message=message,
        user_id=owner_id,
        conversation_history=conversation_history,
    )
    logger.debug("[rpc] chat.send -> result keys=%s", list(result.keys()))
    return result


# ─── Sync ────────────────────────────────────────────────────


async def sync_run(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """sync.run() -> final sync result. Emits `sync.progress` notifications."""
    from zylch.email.imap_client import IMAPClient
    from zylch.services.sync_service import SyncService
    from zylch.storage.storage import Storage

    owner_id = _owner_id()
    logger.debug(f"[rpc] sync.run owner_id={owner_id}")

    email_addr = os.environ.get("EMAIL_ADDRESS", "")
    email_pass = os.environ.get("EMAIL_PASSWORD", "")
    if not email_addr or not email_pass:
        raise RuntimeError(
            "Email not configured for this profile — run `zylch init`."
        )

    email_client = IMAPClient(
        email_addr=email_addr,
        password=email_pass,
        imap_host=os.environ.get("IMAP_HOST") or None,
        imap_port=(int(os.environ.get("IMAP_PORT", "0")) or None),
        smtp_host=os.environ.get("SMTP_HOST") or None,
        smtp_port=(int(os.environ.get("SMTP_PORT", "0")) or None),
    )
    store = Storage.get_instance()
    sync_svc = SyncService(
        email_client=email_client,
        owner_id=owner_id,
        supabase_storage=store,
    )

    def _on_progress(pct: int, message: str) -> None:
        try:
            notify(
                "sync.progress",
                {"pct": int(pct), "message": str(message)},
            )
        except Exception as e:
            logger.warning(f"[rpc] sync.progress notify failed: {e}")

    result = await sync_svc.sync_emails(on_progress=_on_progress)
    logger.debug(f"[rpc] sync.run -> success={result.get('success')}")
    return result


# Dispatch table — kept explicit so adding/removing methods is obvious.
METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "tasks.list": tasks_list,
    "tasks.complete": tasks_complete,
    "tasks.skip": tasks_skip,
    "tasks.solve": tasks_solve,
    "tasks.solve.approve": tasks_solve_approve,
    "chat.send": chat_send,
    "sync.run": sync_run,
}
