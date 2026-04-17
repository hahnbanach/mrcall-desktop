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
    tasks = store.get_task_items(owner_id=owner_id, limit=limit)
    if not include_skipped:
        tasks = [t for t in tasks if not (t.get("sources") or {}).get("skipped_at")]
    logger.debug(f"[rpc] tasks.list -> {len(tasks)} tasks")
    return tasks


async def tasks_complete(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """tasks.complete(task_id) -> {ok: bool}."""
    from zylch.storage.storage import Storage

    task_id = params.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")

    owner_id = _owner_id()
    logger.debug(f"[rpc] tasks.complete owner_id={owner_id} task_id={task_id}")
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
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        _pending_approvals[tool_use_id] = fut
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
    """chat.approve(tool_use_id, approved) -> {ok: true}.

    Unknown tool_use_id -> ValueError (maps to JSON-RPC -32602 via
    server's INVALID_PARAMS handling).
    """
    tool_use_id = params.get("tool_use_id")
    if not tool_use_id:
        raise ValueError("tool_use_id is required")
    approved = bool(params.get("approved", False))
    logger.debug(f"[rpc] chat.approve tool_use_id={tool_use_id} approved={approved}")
    fut = _pending_approvals.pop(tool_use_id, None)
    if fut is None:
        err = ValueError(f"no pending approval for tool_use_id={tool_use_id}")
        err.code = -32602  # type: ignore[attr-defined]
        raise err
    if not fut.done():
        fut.set_result(approved)
    return {"ok": True}


# ─── Update ──────────────────────────────────────────────────


async def update_run(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """update.run() -> full pipeline result (sync + memory + tasks).

    Mirrors the CLI `zylch update` path: calls
    `process_pipeline.handle_process([], config, owner_id)`.

    Emits coarse `update.progress` notifications at start (0%) and end
    (100%). Phase-granularity progress is NOT available because
    `handle_process` does not accept an `on_progress` callback —
    adding that is a separate scope.
    """
    from zylch.services.process_pipeline import handle_process
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

    _emit(0, "Starting full pipeline…")
    # `handle_process` (and its inner `rich.Console()`) writes status to
    # stdout. stdout is the JSON-RPC wire for this sidecar, so we swap
    # sys.stdout -> sys.stderr for the duration of the pipeline to
    # keep the wire clean. Notifications still go out via `notify`,
    # which writes via the server's dedicated writer using the captured
    # real-stdout reference.
    import sys

    real_stdout = sys.stdout
    try:
        config = ToolConfig.from_settings()
        sys.stdout = sys.stderr
        try:
            summary = await handle_process([], config, owner_id)
        finally:
            sys.stdout = real_stdout
    except Exception as e:
        logger.exception("[rpc] update.run failed")
        _emit(100, f"Failed: {e}")
        raise
    _emit(100, "Done")

    logger.debug("[rpc] update.run -> ok (summary_len=%d)", len(summary or ""))
    return {"success": True, "summary": summary or ""}


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

    ansi = re.compile(r"\x1b\[[0-9;]*m")
    cleaned = []
    for ln in lines[-20:]:
        s = ansi.sub("", str(ln)).strip()
        if not s:
            continue
        if " DEBUG " in s:
            continue
        cleaned.append(s[:300])
    if not cleaned:
        return {"text": ""}

    joined = "\n".join(cleaned)
    system = (
        "Riassumi in una singola frase in italiano, in prima persona, "
        "al presente, max 80 caratteri, cosa Zylch sta facendo adesso "
        "in base alle righe di log fornite. Parla come Zylch stesso "
        "('Sto scaricando…', 'Sto cercando…', 'Sto componendo l'email…')."
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


# Dispatch table — kept explicit so adding/removing methods is obvious.
METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "tasks.list": tasks_list,
    "tasks.complete": tasks_complete,
    "tasks.skip": tasks_skip,
    "tasks.solve": tasks_solve,
    "tasks.solve.approve": tasks_solve_approve,
    "chat.send": chat_send,
    "chat.approve": chat_approve,
    "update.run": update_run,
    "narration.summarize": narration_summarize,
}
