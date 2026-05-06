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

    logger.debug(f"[rpc] method={method} params={params}")
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


async def serve() -> None:
    """Main loop: read stdin lines, dispatch concurrently, write responses."""
    logger.info("[rpc] server starting")
    loop = asyncio.get_event_loop()
    tasks: set[asyncio.Task] = set()

    async for line in _read_lines(loop):
        task = asyncio.create_task(_handle_request(line))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    # Drain outstanding handlers before exiting.
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("[rpc] server stopped (stdin closed)")
