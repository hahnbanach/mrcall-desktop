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
_connect_in_flight: Optional[asyncio.Task] = None
_cancel_event: Optional[threading.Event] = None


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
        connected = bool(client.is_connected())
        jid_obj = client.get_me() if connected else None
        jid = None
        if jid_obj is not None:
            # neonize JID has a .User attribute (phone) and .Server
            jid = (
                getattr(jid_obj, "user", None)
                or getattr(jid_obj, "User", None)
                or str(jid_obj)
            )
        return {
            "connected": connected,
            "has_session": has_session,
            "jid": jid,
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

    with _state_lock:
        if _connect_in_flight is not None and not _connect_in_flight.done():
            return {"ok": False, "reason": "connect already in flight"}

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

    loop = asyncio.get_running_loop()
    qr_published = threading.Event()
    connected_ev = threading.Event()
    _cancel_event = threading.Event()

    jid_holder: Dict[str, Optional[str]] = {"jid": None}

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
            me = client.get_me()
            jid_holder["jid"] = (
                getattr(me, "user", None) or getattr(me, "User", None) or str(me)
                if me is not None
                else None
            )
        except Exception:
            jid_holder["jid"] = None
        connected_ev.set()

    client = WhatsAppClient()
    client.set_qr_callback(_on_qr)
    client.on_connected(_on_connected)

    with _state_lock:
        _active_client = client  # noqa: F841 — assigned to module global below
        globals()["_active_client"] = client

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
                return {"ok": True, "jid": jid_holder["jid"]}
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


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "whatsapp.connect": whatsapp_connect,
    "whatsapp.disconnect": whatsapp_disconnect,
    "whatsapp.status": whatsapp_status,
    "whatsapp.cancel": whatsapp_cancel,
}
