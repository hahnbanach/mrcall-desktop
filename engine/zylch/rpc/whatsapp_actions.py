"""RPC handlers for WhatsApp connection driven by the desktop UI.

WhatsApp uses neonize (whatsmeow Go wrapper). First-time login is a QR
scan from the user's phone; subsequent connects reuse the session
stored at `~/.zylch/profiles/<profile>/whatsapp.db`.

Surface (mirrors `google.calendar.*`):

  whatsapp.connect()
      Spawns a background neonize client, awaits the QR callback,
      emits a `whatsapp.qr_ready` notification with a PNG (base64) the
      renderer can render directly, then awaits the connected event.
      Returns {ok, jid?}. 5-minute ceiling — covers the user opening
      WhatsApp on their phone and scanning.

  whatsapp.disconnect(forget_session=False)
      Disconnects the active socket. With `forget_session=True` also
      removes the local session DB so the next connect requires a new
      QR (used as "Forget device").

  whatsapp.status()
      Returns {connected, has_session, jid?}. Non-destructive — does
      NOT spin up the neonize client, just inspects state.

  whatsapp.cancel()
      Cancels an in-flight `connect` flow.

A single in-memory `_active_client` enforces one connect at a time per
sidecar. Multi-window users share `~/.zylch/whatsapp.db` today (legacy
gap tracked in active-context); the env var `ZYLCH_PROFILE_DIR` makes
the path per-profile when set, which is the desktop case.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import threading
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


# ─── Module state ────────────────────────────────────────────
# A single client + its handlers stay alive for the lifetime of the
# sidecar so a connected session keeps receiving events. The desktop
# only ever has ONE WhatsApp connection per profile.
_state_lock = threading.Lock()
_active_client: Optional[Any] = None  # WhatsAppClient
_active_sync: Optional[Any] = None  # WhatsAppSyncService — kept alive so
# the on_message handler (registered on the live neonize client) keeps
# storing new messages for as long as the sidecar runs.
_connect_in_flight: Optional[asyncio.Task] = None
_cancel_event: Optional[threading.Event] = None


def _resolve_owner_id() -> str:
    """Owner ID for the active profile.

    Delegates to the canonical resolver in cli/utils — same value
    everything else in the engine uses (process_pipeline, tasks_list,
    settings_*, …). Critically: `WhatsAppSyncService` writes rows
    under this owner_id, so list_threads / list_messages MUST query
    with the same value or messages stored by `zylch update` (CLI
    path) won't show up in the desktop tab and vice versa.
    """
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


def _format_me(me) -> Dict[str, Optional[str]]:
    """Pull a clean (display_name, phone) pair out of neonize's `me`.

    The neonize `me` is a Go struct with nested ``JID`` and ``LID``
    sub-objects (each with ``User`` = phone, ``Server``, etc.) plus
    ``PushName`` and ``BussinessName`` (the typo is upstream). The
    default ``str(me)`` prints the full struct repr — useless to
    surface to the user. This helper drills into the right fields and
    returns them as plain strings.
    """
    if me is None:
        return {"display_name": None, "phone": None}

    # Phone from JID.User. The attribute exists in both PascalCase
    # ('User') and lowercase ('user') across neonize versions.
    inner_jid = getattr(me, "JID", None) or getattr(me, "Jid", None) or getattr(me, "jid", None)
    phone = None
    if inner_jid is not None:
        phone = getattr(inner_jid, "User", None) or getattr(inner_jid, "user", None)

    # BusinessName has a typo upstream (BussinessName); also accept
    # PushName as a secondary, then no name at all.
    name = (
        getattr(me, "BussinessName", None)
        or getattr(me, "BusinessName", None)
        or getattr(me, "PushName", None)
        or None
    )
    # Sanitize empty strings so the renderer can do simple `if name`.
    return {
        "display_name": (name.strip() if isinstance(name, str) and name.strip() else None),
        "phone": (str(phone).strip() if phone else None),
    }


def _wa_db_path() -> str:
    """Mirror `WhatsAppClient._default_wa_db()` to peek at session
    presence without instantiating the client (which loads the Go
    runtime)."""
    profile_dir = os.environ.get("ZYLCH_PROFILE_DIR")
    if profile_dir:
        return os.path.join(profile_dir, "whatsapp.db")
    return os.path.expanduser("~/.zylch/whatsapp.db")


def _qr_to_png_b64(data_qr: bytes) -> Optional[str]:
    """Render the neonize QR payload as a PNG and return its base64
    body. Falls back to the raw payload string when the QR library is
    unavailable — the renderer detects which form it got.
    """
    try:
        import segno  # type: ignore
    except ImportError:
        logger.warning("[rpc:whatsapp] segno not available, cannot render PNG QR")
        return None
    try:
        buf = io.BytesIO()
        segno.make_qr(data_qr).save(buf, kind="png", scale=6, border=2)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:
        logger.warning(f"[rpc:whatsapp] PNG QR render failed: {e}")
        return None


async def whatsapp_status(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """whatsapp.status() -> {connected, has_session, jid?}

    Cheap call — does not import neonize, just looks at module state
    and the on-disk session file. Renderer mounts this on every Settings
    visit; loading the Go runtime here would freeze the UI.
    """
    has_session = os.path.exists(_wa_db_path())
    with _state_lock:
        client = _active_client
    if client is None:
        return {"connected": False, "has_session": has_session}
    try:
        # ``is_connected`` is True as soon as the WS socket to the WA
        # server is up — including the QR-emitting phase when the local
        # session is dead and neonize is asking the user to re-pair.
        # In that state we are NOT actually able to read or send
        # messages, so the renderer must NOT treat us as live. Only
        # ``is_logged_in`` proves a usable session.
        socket_up = bool(client.is_connected())
        logged_in = bool(client.is_logged_in()) if socket_up else False
        connected = socket_up and logged_in
        me = client.get_me() if connected else None
        formatted = _format_me(me)
        return {
            "connected": connected,
            "has_session": has_session,
            "phone": formatted["phone"],
            "display_name": formatted["display_name"],
        }
    except Exception as e:
        logger.warning(f"[rpc:whatsapp.status] readback failed: {e}")
        return {"connected": False, "has_session": has_session}


async def whatsapp_connect(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """whatsapp.connect() -> {ok: bool, jid?: str, reason?: str}

    Spawns a neonize client, registers QR + connected callbacks,
    publishes a `whatsapp.qr_ready` notification on the first QR payload
    (base64 PNG when segno is available, raw text payload otherwise),
    and awaits the connected event. Soft timeout 5 minutes.
    """
    global _connect_in_flight, _cancel_event

    # If a previous connect is still running (typically the boot-time
    # auto-reconnect, which can sit in QR-emission limbo for up to 5
    # minutes when the session is dead), cancel it and proceed. The
    # caller — usually the user clicking "Reconnect" — explicitly
    # asked for a fresh attempt; a flat "already in flight" error
    # leaves them stuck. Best-effort: we wait briefly for the cancel
    # to land but never block the new connect on it.
    with _state_lock:
        prior_task = _connect_in_flight
        prior_cancel = _cancel_event

    if prior_task is not None and not prior_task.done():
        logger.info(
            "[rpc:whatsapp.connect] cancelling prior in-flight connect to honour new request"
        )
        if prior_cancel is not None:
            prior_cancel.set()
        try:
            await asyncio.wait_for(asyncio.shield(prior_task), timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            pass
        with _state_lock:
            globals()["_connect_in_flight"] = None
            globals()["_cancel_event"] = None
            # _active_client is cleared by the prior task's finally
            # block; if for some reason it isn't, the new client below
            # will overwrite it anyway.

    # Lazy import — neonize loads a Go shared library; do NOT pay this
    # cost at sidecar boot.
    try:
        from zylch.whatsapp.client import WhatsAppClient
    except (ImportError, OSError) as e:
        logger.error(f"[rpc:whatsapp.connect] neonize unavailable: {e}")
        msg = str(e)
        # libmagic is the most common stumble on macOS — surface a
        # specific hint instead of bubbling the bare ctypes error so
        # the user knows the exact recovery step.
        if "libmagic" in msg.lower():
            import sys as _sys

            if _sys.platform == "darwin":
                hint = (
                    "Install libmagic with Homebrew: `brew install libmagic`, "
                    "then restart MrCall Desktop."
                )
            elif _sys.platform.startswith("linux"):
                hint = (
                    "Install libmagic via your package manager: "
                    "`sudo apt install libmagic1` (Debian/Ubuntu) or "
                    "`sudo dnf install file-libs` (Fedora), then restart."
                )
            else:
                hint = "Install libmagic for your platform, then restart MrCall Desktop."
            return {"ok": False, "reason": f"libmagic missing. {hint}"}
        return {"ok": False, "reason": f"WhatsApp not available: {msg}"}

    # Sync service mirrors what `process_pipeline.py` does in the CLI
    # path: stores history events + live messages into whatsapp_messages.
    # Without this, the renderer's thread/message lists stay empty even
    # though the socket is connected.
    try:
        from zylch.whatsapp.sync import WhatsAppSyncService
        from zylch.storage import Storage

        owner_id = _resolve_owner_id()
        sync_svc = WhatsAppSyncService(Storage.get_instance(), owner_id)
    except Exception as e:
        logger.error(f"[rpc:whatsapp.connect] sync service init failed: {e}")
        return {"ok": False, "reason": f"sync init failed: {e}"}

    loop = asyncio.get_running_loop()
    qr_published = threading.Event()
    connected_ev = threading.Event()
    history_done_ev = threading.Event()
    _cancel_event = threading.Event()

    me_holder: Dict[str, Optional[str]] = {"phone": None, "display_name": None}

    def _on_qr(client, data_qr: bytes) -> None:
        # Called by neonize on every QR refresh (every 20s). Publish the
        # FIRST one only — the renderer handles re-display itself.
        if qr_published.is_set():
            return
        qr_published.set()
        png_b64 = _qr_to_png_b64(data_qr)
        # Fallback to raw text payload for the renderer to render
        # client-side if PNG generation failed.
        try:
            text_payload = (
                data_qr.decode("utf-8") if isinstance(data_qr, (bytes, bytearray)) else str(data_qr)
            )
        except Exception:
            text_payload = None
        loop.call_soon_threadsafe(
            notify,
            "whatsapp.qr_ready",
            {"png_base64": png_b64, "qr_text": text_payload},
        )

    def _on_connected() -> None:
        try:
            formatted = _format_me(client.get_me())
            me_holder["phone"] = formatted["phone"]
            me_holder["display_name"] = formatted["display_name"]
        except Exception:
            me_holder["phone"] = None
            me_holder["display_name"] = None
        connected_ev.set()

    def _emit_threads_changed() -> None:
        """Tell the renderer that the thread list / open chat is stale.

        Without this, `whatsapp.list_threads` runs ONCE when the
        renderer's `connected` state flips and is never refreshed —
        every message neonize delivers afterwards (history batch on
        re-connect or live MessageEv) goes invisible until the user
        clicks Refresh. The renderer subscribes to this notification,
        debounces, and re-fetches threads + the active chat. Emission
        is throttled at the engine for the history-sync burst case;
        the renderer also debounces, so duplicates are cheap.
        """
        try:
            loop.call_soon_threadsafe(
                notify,
                "whatsapp.threads.changed",
                {},
            )
        except Exception as e:
            logger.debug(f"[rpc:whatsapp.connect] notify threads.changed: {e}")

    def _on_history(event) -> None:
        try:
            sync_svc.handle_history_sync(event)
        except Exception as e:
            logger.warning(f"[rpc:whatsapp.connect] history handler: {e}")
        finally:
            history_done_ev.set()
            # One notification per HistorySyncEv batch — the worker just
            # stored hundreds of rows in one go; the renderer needs to
            # re-fetch the list once.
            _emit_threads_changed()

    def _on_message(event) -> bool:
        try:
            stored = bool(sync_svc.handle_message(event))
            if stored:
                _emit_threads_changed()
            return stored
        except Exception as e:
            logger.warning(f"[rpc:whatsapp.connect] message handler: {e}")
            return False

    client = WhatsAppClient()
    client.set_qr_callback(_on_qr)
    client.on_connected(_on_connected)
    client.on_history_sync(_on_history)
    client.on_message(_on_message)

    # Give the sync service the live client so its message handler can
    # download voice-note bytes at event time (URLs expire server-side).
    # Must be set BEFORE connect() opens the socket / first MessageEv.
    sync_svc.wa_client = client

    with _state_lock:
        globals()["_active_client"] = client
        globals()["_active_sync"] = sync_svc

    # Run the blocking neonize connect in a thread; we await an event.
    client.connect(blocking=False)

    async def _await_connected() -> Dict[str, Any]:
        # Poll the connected_ev / cancel_event in the executor. 5-minute
        # soft cap; bail early if the renderer cancels.
        timeout_s = 5 * 60
        elapsed = 0.0
        step = 0.25
        while elapsed < timeout_s:
            if _cancel_event and _cancel_event.is_set():
                try:
                    client.disconnect()
                except Exception:
                    pass
                with _state_lock:
                    globals()["_active_client"] = None
                return {"ok": False, "reason": "cancelled"}
            if connected_ev.is_set():
                # Give the history sync up to 30s to finish — usually
                # arrives within a few seconds of CONNECTED on first
                # link, often skipped for re-connect (already synced).
                hist_elapsed = 0.0
                while hist_elapsed < 30.0:
                    if history_done_ev.is_set():
                        break
                    await asyncio.sleep(step)
                    hist_elapsed += step
                # Materialize WhatsAppContact rows from messages we
                # just stored so the renderer's thread list shows
                # names, not raw JIDs.
                try:
                    sync_svc.sync_contacts(client)
                except Exception as e:
                    logger.warning(f"[rpc:whatsapp.connect] sync_contacts: {e}")
                # Group titles too — without this the WhatsApp tab shows
                # the *last sender's* name as the group title (cosmetic
                # bug surfaced 2026-05-06).
                try:
                    sync_svc.sync_groups(client)
                except Exception as e:
                    logger.warning(f"[rpc:whatsapp.connect] sync_groups: {e}")
                # LID contact resolution: WA's privacy mode returns chats
                # and senders as ``@lid`` pseudonyms; without this the
                # WhatsApp tab would show numeric LIDs as if they were
                # phone numbers, even though the real phone+name is sitting
                # in neonize's own session DB.
                try:
                    sync_svc.sync_lid_contacts(client)
                except Exception as e:
                    logger.warning(f"[rpc:whatsapp.connect] sync_lid_contacts: {e}")
                return {
                    "ok": True,
                    "phone": me_holder["phone"],
                    "display_name": me_holder["display_name"],
                }
            await asyncio.sleep(step)
            elapsed += step
        # Timeout — leave the client in place; the user can retry later
        # via "Connect" again or disconnect explicitly.
        try:
            client.disconnect()
        except Exception:
            pass
        with _state_lock:
            globals()["_active_client"] = None
        return {"ok": False, "reason": "timeout"}

    task = asyncio.create_task(_await_connected())
    with _state_lock:
        _connect_in_flight = task
        globals()["_connect_in_flight"] = task

    try:
        return await task
    finally:
        with _state_lock:
            globals()["_connect_in_flight"] = None
            globals()["_cancel_event"] = None


async def whatsapp_list_threads(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """whatsapp.list_threads(limit=200, offset=0) -> {threads: [...]}.

    One row per ``chat_jid`` with the latest message preview, sorted
    newest first. Joins WhatsAppContact when available so the renderer
    can show the contact name instead of the raw JID.
    """
    from sqlalchemy import desc, func

    from zylch.services.whatsapp_search import build_thread_rows
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage

    limit = int(params.get("limit", 200))
    offset = int(params.get("offset", 0))
    owner_id = _resolve_owner_id()
    if not owner_id:
        return {"threads": [], "total_messages": 0, "owner_id": ""}

    try:
        with get_session() as session:
            # Aggregate per chat: count + latest timestamp. Skip rows
            # without a real conversation target — empty chat_jid (junk
            # rows from old buggy stores) and any of WhatsApp's
            # broadcast pseudo-chats (`status@broadcast`,
            # `meta@broadcast`, …) which would render as useless rows.
            agg = (
                session.query(
                    WhatsAppMessage.chat_jid,
                    func.max(WhatsAppMessage.timestamp).label("last_ts"),
                    func.count(WhatsAppMessage.id).label("msg_count"),
                )
                .filter(
                    WhatsAppMessage.owner_id == owner_id,
                    WhatsAppMessage.chat_jid.isnot(None),
                    WhatsAppMessage.chat_jid != "",
                    ~WhatsAppMessage.chat_jid.like("%@broadcast"),
                    ~WhatsAppMessage.chat_jid.like("%@newsletter"),
                )
                .group_by(WhatsAppMessage.chat_jid)
                .order_by(desc("last_ts"))
                .offset(offset)
                .limit(limit)
                .all()
            )
            logger.debug(f"[rpc:whatsapp.list_threads] owner_id={owner_id} -> {len(agg)} threads")
            # Always count total messages for this owner so the renderer
            # can render "X messages stored, 0 visible threads" inline —
            # turns a silent empty list into something actionable.
            total_messages = int(
                session.query(func.count(WhatsAppMessage.id))
                .filter(WhatsAppMessage.owner_id == owner_id)
                .scalar()
                or 0
            )
            if not agg:
                # When everything got filtered, surface a per-server
                # breakdown so the renderer can show "all 36 are
                # status broadcasts" vs "30 broadcasts + 6 chats" —
                # the latter would mean the filter is wrong.
                breakdown_rows = (
                    session.query(
                        WhatsAppMessage.chat_jid,
                        func.count(WhatsAppMessage.id).label("c"),
                    )
                    .filter(WhatsAppMessage.owner_id == owner_id)
                    .group_by(WhatsAppMessage.chat_jid)
                    .all()
                )
                # Bucket by the server portion of the JID — that's what
                # actually distinguishes broadcast/status from real
                # chats. user@s.whatsapp.net = direct, jid@g.us = group,
                # status@broadcast = status updates, …@newsletter = channels.
                bucket: Dict[str, int] = {}
                for row in breakdown_rows:
                    jid = row.chat_jid or ""
                    server = jid.rsplit("@", 1)[1] if "@" in jid else "(no jid)"
                    bucket[server] = bucket.get(server, 0) + int(row.c or 0)
                logger.debug(
                    f"[rpc:whatsapp.list_threads] no threads but "
                    f"{total_messages} messages exist; breakdown={bucket}"
                )
                return {
                    "threads": [],
                    "total_messages": total_messages,
                    "owner_id": owner_id,
                    "breakdown_by_server": bucket,
                }

            # Build display rows through the shared helper so the plain
            # listing and search results render identically (name fallback
            # chain, LID/group phone handling, preview). `agg` already
            # ordered the jids newest-first + paginated.
            jids = [r.chat_jid for r in agg]
            threads = build_thread_rows(session, owner_id, jids)
            return {
                "threads": threads,
                "total_messages": total_messages,
                "owner_id": owner_id,
            }
    except Exception as e:
        logger.error(f"[rpc:whatsapp.list_threads] {e}")
        return {"threads": [], "total_messages": 0, "error": str(e)}


async def whatsapp_list_messages(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """whatsapp.list_messages(chat_jid, limit=200, offset=0) -> {messages}.

    Oldest-first within the page so the renderer can render top-to-bottom
    without reversing.
    """
    from zylch.storage.database import get_session
    from zylch.storage.models import WhatsAppMessage

    chat_jid = (params.get("chat_jid") or "").strip()
    if not chat_jid:
        return {"messages": []}
    limit = int(params.get("limit", 200))
    offset = int(params.get("offset", 0))
    owner_id = _resolve_owner_id()
    if not owner_id:
        return {"messages": []}

    try:
        with get_session() as session:
            rows = (
                session.query(WhatsAppMessage)
                .filter(
                    WhatsAppMessage.owner_id == owner_id,
                    WhatsAppMessage.chat_jid == chat_jid,
                )
                .order_by(WhatsAppMessage.timestamp.asc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return {
                "messages": [
                    {
                        "id": r.id,
                        "message_id": r.message_id,
                        "chat_jid": r.chat_jid,
                        "sender_jid": r.sender_jid,
                        "sender_name": r.sender_name,
                        "text": r.text,
                        "media_type": r.media_type,
                        "transcription": r.transcription,
                        "is_from_me": bool(r.is_from_me),
                        "is_group": bool(r.is_group),
                        "timestamp": (r.timestamp.isoformat() if r.timestamp is not None else None),
                    }
                    for r in rows
                ]
            }
    except Exception as e:
        logger.error(f"[rpc:whatsapp.list_messages] {e}")
        return {"messages": [], "error": str(e)}


async def whatsapp_disconnect(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """whatsapp.disconnect(forget_session=False) -> {ok}"""
    forget = bool(params.get("forget_session", False))
    with _state_lock:
        client = _active_client
    if client is not None:
        try:
            client.disconnect()
        except Exception as e:
            logger.warning(f"[rpc:whatsapp.disconnect] {e}")
    with _state_lock:
        globals()["_active_client"] = None
        globals()["_active_sync"] = None
    if forget:
        path = _wa_db_path()
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as e:
            logger.warning(f"[rpc:whatsapp.disconnect] could not remove {path}: {e}")
            return {"ok": True, "forgot": False, "error": str(e)}
        return {"ok": True, "forgot": True}
    return {"ok": True, "forgot": False}


async def whatsapp_cancel(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """whatsapp.cancel() -> {cancelled}"""
    with _state_lock:
        ev = _cancel_event
    if ev is None:
        return {"cancelled": False}
    ev.set()
    return {"cancelled": True}


async def whatsapp_search_messages(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """whatsapp.search_messages(query, limit=200) -> {threads, query}.

    Free-text search across the local store. Matches message text /
    transcription / sender name AND contact name / phone, returns the
    matching chats newest-first in the SAME shape as ``list_threads`` (so
    the renderer reuses the thread-row component) with a per-row
    ``match_snippet`` of the matching message. Reads SQLite only — no live
    socket required.
    """
    from zylch.services.whatsapp_search import build_thread_rows, search_thread_jids
    from zylch.storage.database import get_session

    query = (params.get("query") or "").strip()
    limit = int(params.get("limit", 200))
    owner_id = _resolve_owner_id()
    if not owner_id or not query:
        return {"threads": [], "query": query}

    try:
        with get_session() as session:
            jids, snippet_by_jid = search_thread_jids(session, owner_id, query, limit)
            threads = build_thread_rows(session, owner_id, jids, snippet_by_jid=snippet_by_jid)
            logger.debug(
                f"[rpc:whatsapp.search_messages] query={query!r} -> {len(threads)} threads"
            )
            return {"threads": threads, "query": query}
    except Exception as e:
        logger.error(f"[rpc:whatsapp.search_messages] {e}")
        return {"threads": [], "query": query, "error": str(e)}


async def whatsapp_send_message(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """whatsapp.send_message(chat_jid, text) -> {ok, message?, error?}.

    Sends a text message to an existing chat over the LIVE connection
    (the persistent ``_active_client`` the connect flow keeps alive) —
    deliberately NOT a throwaway client like the LLM ``send_whatsapp``
    tool, since two neonize clients on the same session DB clash. The
    blocking neonize FFI send runs in a thread executor so the JSON-RPC
    event loop stays responsive.

    On success the just-sent message is persisted (keyed on the real
    ``SendResponse.ID`` so the live-socket echo dedups) and returned in
    ``list_messages`` row shape so the renderer can append it without a
    full reload.
    """
    from datetime import datetime, timezone

    chat_jid = (params.get("chat_jid") or "").strip()
    text = params.get("text")
    text = text.strip() if isinstance(text, str) else ""
    if not chat_jid:
        return {"ok": False, "error": "chat_jid required"}
    if not text:
        return {"ok": False, "error": "message text is empty"}

    with _state_lock:
        client = _active_client
        sync = _active_sync

    if client is None:
        return {"ok": False, "error": "WhatsApp not connected"}
    try:
        usable = bool(client.is_connected()) and bool(client.is_logged_in())
    except Exception:
        usable = False
    if not usable:
        return {"ok": False, "error": "WhatsApp not connected"}

    # Build the recipient JID from the stored chat_jid, preserving the
    # server so direct (@s.whatsapp.net), group (@g.us) and privacy-LID
    # (@lid) chats all address correctly. build_jid defaults the server
    # to s.whatsapp.net, which would be wrong for groups/LIDs.
    user, sep, server = chat_jid.partition("@")
    if not user or not sep or not server:
        return {"ok": False, "error": f"invalid chat_jid: {chat_jid}"}

    try:
        from neonize.utils import build_jid

        to_jid = build_jid(user, server)
    except Exception as e:
        logger.error(f"[rpc:whatsapp.send_message] build_jid({chat_jid}) failed: {e}")
        return {"ok": False, "error": f"could not address chat: {e}"}

    loop = asyncio.get_running_loop()

    def _do_send():
        # WhatsAppClient.send_message returns the SendResponse on success
        # or None on failure (it catches + logs the neonize exception).
        return client.send_message(to_jid, text)

    try:
        resp = await loop.run_in_executor(None, _do_send)
    except Exception as e:
        logger.error(f"[rpc:whatsapp.send_message] send raised: {e}")
        return {"ok": False, "error": f"send failed: {e}"}

    if not resp:
        # Detail is in zylch.log via WhatsAppClient.send_message.
        return {"ok": False, "error": "send failed — see logs"}

    msg_id = str(getattr(resp, "ID", "") or "")
    ts = datetime.now(timezone.utc)

    # Persist so the message survives a thread reload. _active_sync is set
    # by the connect flow; fall back to a transient sync service (no
    # neonize cost) if for some reason it isn't.
    try:
        store = sync
        if store is None:
            from zylch.storage import Storage
            from zylch.whatsapp.sync import WhatsAppSyncService

            store = WhatsAppSyncService(Storage.get_instance(), _resolve_owner_id())
        if msg_id:
            store.store_outgoing(chat_jid=chat_jid, text=text, msg_id=msg_id, timestamp=ts)
    except Exception as e:
        logger.warning(f"[rpc:whatsapp.send_message] persist failed: {e}")

    return {
        "ok": True,
        "message": {
            "id": msg_id or f"out-{ts.timestamp()}",
            "message_id": msg_id,
            "chat_jid": chat_jid,
            "sender_jid": "me",
            "sender_name": None,
            "text": text,
            "media_type": None,
            "transcription": None,
            "is_from_me": True,
            "is_group": chat_jid.endswith("@g.us"),
            "timestamp": ts.isoformat(),
        },
    }


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "whatsapp.connect": whatsapp_connect,
    "whatsapp.disconnect": whatsapp_disconnect,
    "whatsapp.status": whatsapp_status,
    "whatsapp.cancel": whatsapp_cancel,
    "whatsapp.list_threads": whatsapp_list_threads,
    "whatsapp.list_messages": whatsapp_list_messages,
    "whatsapp.search_messages": whatsapp_search_messages,
    "whatsapp.send_message": whatsapp_send_message,
}
