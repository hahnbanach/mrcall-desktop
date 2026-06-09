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
from typing import Any, Dict

from zylch.rpc.dispatch import dispatch_raw
from zylch.rpc.reaper import reap_orphans_loop

logger = logging.getLogger(__name__)

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
    """Dispatch one stdin line and write its response (if any) to stdout.

    The parse + dispatch + error-mapping logic lives in
    ``zylch.rpc.dispatch.dispatch_raw`` so the WebSocket transport
    (``zylch.rpc.server_ws``) shares exactly the same code-path. This
    wrapper owns only the stdio I/O: it hands the raw line to the
    dispatcher with a stdout-backed ``notify`` and writes whatever
    response comes back.
    """
    resp = await dispatch_raw(raw_line, _make_notify())
    if resp is not None:
        await _write_line(resp)


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
        result = await whatsapp_connect({}, notify=lambda *a, **k: None)
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

    # Reap zombie children leaked by the whatsmeow Go c-shared lib (the same
    # janitor the WS serve daemon runs). The stdio engine loads whatsmeow too
    # — at boot via _auto_reconnect_whatsapp and on every whatsapp sync — so
    # without this a long-lived desktop session slowly accrues `[sh] <defunct>`
    # zombies. Kept OUT of `tasks` because it loops forever: it is cancelled on
    # exit, not awaited in the drain below.
    reaper_task = asyncio.create_task(reap_orphans_loop())

    try:
        async for line in _read_lines(loop):
            task = asyncio.create_task(_handle_request(line))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        # Drain outstanding handlers before exiting.
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        reaper_task.cancel()
        await asyncio.gather(reaper_task, return_exceptions=True)
    logger.info("[rpc] server stopped (stdin closed)")
