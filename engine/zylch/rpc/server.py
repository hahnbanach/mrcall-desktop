"""Line-delimited JSON-RPC 2.0 server over stdin/stdout.

Protocol:
- Input: one JSON object per line on stdin. Fields: `jsonrpc: "2.0"`,
  `id` (number/string, optional for notifications), `method`, `params`.
- Output: one JSON object per line on stdout. Either a response
  (`result` or `error`) or a notification (no `id`).

Critical: stdout is the wire. NEVER write logs to stdout. Everything
goes to stderr or the log file (configured in zylch.cli.main).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
from typing import Any, Dict, Optional

from zylch.rpc.methods import METHODS

logger = logging.getLogger(__name__)

# JSON-RPC 2.0 standard error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# Thread-safe lock for stdout writes. We use threading.Lock (not asyncio.Lock)
# so sync callbacks (e.g. SyncService on_progress) can write immediately,
# instead of queuing behind the awaiting handler's final response.
_stdout_lock = threading.Lock()

# Capture the real stdout at import time. Handlers like `update.run` swap
# `sys.stdout` for the duration of a subcommand (to keep rich.Console
# chatter off the wire). The RPC writer must always target the real
# stdout, not whatever `sys.stdout` happens to be right now.
_REAL_STDOUT = sys.stdout


def _write_line_sync(obj: Dict[str, Any]) -> None:
    """Serialize obj and write one line to stdout immediately, flushed."""
    line = json.dumps(obj, ensure_ascii=False, default=str)
    with _stdout_lock:
        _REAL_STDOUT.write(line + "\n")
        _REAL_STDOUT.flush()


async def _write_line(obj: Dict[str, Any]) -> None:
    """Async wrapper — kept for symmetry; the write itself is sync."""
    _write_line_sync(obj)


# Secrets MUST never reach the DEBUG-level "method=X params=Y" line —
# stderr is captured by the renderer's narration pipeline and forwarded
# to the LLM proxy for summarisation, so anything that lands here ends
# up in Anthropic's request logs. Keep this list sync'd with any RPC
# method that takes a JWT, API key, password, OTP, OAuth code, etc.
# 2026-05-31: Mario observed the Firebase id_token (1160 chars) flowing
# all the way to Anthropic via narration.summarize because the dispatcher
# was dumping `account.set_firebase_token`'s full params at DEBUG. After
# switching the engine's default log level to DEBUG that became a
# silent data-leak channel.
_SECRET_PARAM_KEYS_BY_METHOD: Dict[str, set[str]] = {
    "account.set_firebase_token": {"id_token"},
}
_SECRET_PARAM_KEYS_GLOBAL: set[str] = {
    # Defence-in-depth: redact these regardless of method, in case a
    # new RPC ships before this table is updated. Keep names broad but
    # not so broad we redact innocent fields like "passenger" or "tokens"
    # (output_tokens, input_tokens etc. in usage payloads).
    "id_token",
    "access_token",
    "refresh_token",
    "api_key",
    "password",
    "client_secret",
    "secret",
}


def _redact_params(method: Optional[str], params: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of ``params`` with known-sensitive fields masked.

    The dispatcher's "method=X params=Y" debug line ends up on stderr,
    which the renderer's narration pipeline forwards to the LLM proxy
    for summarisation. We never want a Firebase JWT, an Anthropic key,
    or any other bearer credential to flow that path.
    """
    if not isinstance(params, dict) or not params:
        return params
    per_method = _SECRET_PARAM_KEYS_BY_METHOD.get(method or "", set())
    secret_keys = per_method | _SECRET_PARAM_KEYS_GLOBAL
    redacted = dict(params)
    for k in list(redacted.keys()):
        if k in secret_keys and redacted[k]:
            v = redacted[k]
            if isinstance(v, str):
                redacted[k] = f"<redacted len={len(v)}>"
            else:
                redacted[k] = "<redacted>"
    return redacted


def _make_notify():
    """Return a sync `notify(method, params)` that writes immediately."""

    def notify(method: str, params: Dict[str, Any]) -> None:
        _write_line_sync(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )

    return notify


async def _handle_request(raw_line: str) -> None:
    """Parse one line and dispatch. Always produces one response (unless notification)."""
    line = raw_line.strip()
    if not line:
        return

    # Parse
    try:
        req = json.loads(line)
    except json.JSONDecodeError as e:
        logger.debug(f"[rpc] parse error: {e}")
        await _write_line(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": PARSE_ERROR,
                    "message": f"Parse error: {e}",
                },
            }
        )
        return

    if not isinstance(req, dict):
        await _write_line(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": INVALID_REQUEST,
                    "message": "Request must be a JSON object",
                },
            }
        )
        return

    req_id: Optional[Any] = req.get("id")
    method: Optional[str] = req.get("method")
    params: Dict[str, Any] = req.get("params") or {}
    is_notification = "id" not in req

    if not isinstance(method, str) or not method:
        if is_notification:
            return
        await _write_line(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": INVALID_REQUEST,
                    "message": "Missing or invalid 'method'",
                },
            }
        )
        return

    if not isinstance(params, dict):
        if is_notification:
            return
        await _write_line(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": INVALID_PARAMS,
                    "message": "'params' must be an object",
                },
            }
        )
        return

    handler = METHODS.get(method)
    if handler is None:
        logger.debug(f"[rpc] unknown method={method}")
        if is_notification:
            return
        await _write_line(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": METHOD_NOT_FOUND,
                    "message": f"Method not found: {method}",
                },
            }
        )
        return

    logger.debug(f"[rpc] method={method} params={_redact_params(method, params)}")
    notify = _make_notify()
    try:
        result = await handler(params, notify)
    except Exception as e:
        # Handlers may raise errors with a `.code` attribute to map
        # cleanly to JSON-RPC application error codes (e.g. -32000
        # for "solve already in progress", -32010 for "no signed-in
        # session"). Those are intentional protocol-level signals —
        # the JSON-RPC response below carries the code, so we log a
        # one-liner instead of a full stack trace. Unknown / unhandled
        # exceptions still get the full traceback at ERROR.
        err_code = getattr(e, "code", None)
        if isinstance(err_code, int):
            logger.warning(
                f"[rpc] handler {method} failed code={err_code} "
                f"{type(e).__name__}: {e}"
            )
        else:
            logger.exception(f"[rpc] handler {method} failed")
            err_code = INTERNAL_ERROR
        if is_notification:
            return
        await _write_line(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": err_code,
                    "message": f"{type(e).__name__}: {e}",
                },
            }
        )
        return

    if is_notification:
        return
    await _write_line(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result,
        }
    )


async def _read_lines(loop: asyncio.AbstractEventLoop):
    """Async iterator over stdin lines (without blocking the loop).

    The default asyncio StreamReader limit is 64 KiB per line. A single
    chat.send request can easily exceed that once conversation_history
    contains a few turns with embedded email bodies or tool_result
    payloads. We raise the limit to 16 MiB — any JSON-RPC frame larger
    than that is a bug on the caller side, not a line buffer issue.
    """
    reader = asyncio.StreamReader(limit=16 * 1024 * 1024)
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    while True:
        line_bytes = await reader.readline()
        if not line_bytes:
            return
        try:
            yield line_bytes.decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"[rpc] decode error: {e}")
            continue


async def _auto_reconnect_whatsapp() -> None:
    """Reconnect a paired WhatsApp session at boot.

    Without this, every app launch leaves the neonize socket closed —
    the renderer shows the last known thread list (read straight from
    SQLite via ``WhatsApp.tsx:45``'s ``r.connected || r.has_session``
    fallback) but no fresh ``MessageEv`` is delivered, so new chats
    never appear and existing ones don't update. Forcing the user to
    hunt for a "Reconnect" button on every launch is a UX bug.

    We fire-and-forget the same RPC the renderer would call. If no
    session is on disk we skip silently so first-run / unpaired
    profiles don't pay the neonize Go-runtime load cost.
    """
    import os

    from zylch.whatsapp.client import _default_wa_db

    wa_db = _default_wa_db()
    if not os.path.exists(wa_db):
        logger.info("[rpc] auto-reconnect skipped (no WhatsApp session on disk)")
        return

    # Tiny grace period so the renderer's first ``whatsapp.status``
    # poll lands before we mutate ``_active_client``. Not load-bearing.
    await asyncio.sleep(1.0)

    try:
        from zylch.rpc.whatsapp_actions import whatsapp_connect
    except Exception as e:
        logger.warning(f"[rpc] auto-reconnect: could not import whatsapp_connect: {e}")
        return

    logger.info("[rpc] auto-reconnect: WhatsApp session found, reconnecting in background")
    try:
        # Use the REAL notify (writes to stdout) — `whatsapp.qr_ready`
        # and `whatsapp.threads.changed` notifications emitted by
        # `_on_message` / `_on_history` reach the renderer this way.
        # The previous no-op silently dropped every WA notification
        # emitted on the auto-reconnect path, which is the most common
        # case (engine boot → auto-reconnect → history sync delivers
        # the queued messages). The renderer never saw they arrived.
        result = await whatsapp_connect({}, notify=_make_notify())
        if isinstance(result, dict) and result.get("ok"):
            logger.info(
                "[rpc] auto-reconnect: WhatsApp connected "
                f"phone={result.get('phone')} display_name={result.get('display_name')}"
            )
        else:
            logger.warning(f"[rpc] auto-reconnect: connect returned {result}")
    except Exception as e:
        logger.error(f"[rpc] auto-reconnect: connect raised {type(e).__name__}: {e}")


async def serve() -> None:
    """Main loop: read stdin lines, dispatch concurrently, write responses."""
    logger.info("[rpc] server starting")

    # Warm up the costly lazy-init pieces before declaring ready, so the
    # renderer's first batch of mount-time RPCs (settings.get,
    # settings.schema, account.set_firebase_token, tasks.list,
    # mrcall.list_my_businesses) doesn't pay that cost individually and
    # time out at the renderer's 60 s default. On a brand-new profile
    # Storage.init_db (Base.metadata.create_all) + Pydantic Settings .env
    # parse take several seconds on first touch — without the warm-up,
    # `engine.ready` was technically true (dispatcher running) but the
    # first real RPC stretched past the timeout. Idempotent, fast on a
    # warm profile (subsequent boots find the schema already created).
    try:
        from zylch.config import settings as _settings
        from zylch.storage.storage import Storage

        _ = _settings.email_address  # forces Pydantic Settings + .env load
        # `Storage.get_instance()` is a singleton — its `__init__` already
        # calls `database.init_db()` (which runs `Base.metadata.create_all`).
        # Just constructing the instance triggers the schema creation; the
        # previous `.init_db()` call here was a non-existent attribute
        # on Storage and failed silently (`'Storage' object has no
        # attribute 'init_db'`), making the entire warmup a no-op.
        Storage.get_instance()
        logger.info("[rpc] warmup done (Storage + Settings)")
    except Exception as e:
        # Never let a warmup failure prevent the server from starting —
        # the renderer will surface the real error via the per-RPC
        # path (humanize_error) anyway. Log and continue.
        logger.warning(f"[rpc] warmup failed (non-fatal): {e}")

    # Tell the desktop main process the engine is ready to serve RPCs.
    # The renderer gates mount-time RPCs on this notification; the splash
    # in `views/EngineReadySplash` stays visible until it arrives.
    _write_line_sync({"jsonrpc": "2.0", "method": "engine.ready", "params": {}})
    logger.info("[rpc] engine.ready emitted")

    loop = asyncio.get_event_loop()
    tasks: set[asyncio.Task] = set()

    # Best-effort: revive a paired WhatsApp session in the background so
    # MessageEv start flowing without requiring a manual click.
    auto_reconnect_task = asyncio.create_task(_auto_reconnect_whatsapp())
    tasks.add(auto_reconnect_task)
    auto_reconnect_task.add_done_callback(tasks.discard)

    async for line in _read_lines(loop):
        task = asyncio.create_task(_handle_request(line))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    # Drain outstanding handlers before exiting.
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("[rpc] server stopped (stdin closed)")
