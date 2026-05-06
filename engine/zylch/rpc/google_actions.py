"""RPC handlers for Google integrations driven by the desktop UI.

Phase 4 ships the Calendar OAuth surface:

  google.calendar.connect()
      Kicks off the PKCE OAuth flow (loopback server on :19275),
      emits a `google.calendar.auth_url_ready` notification with the
      consent URL the renderer should open in the user's browser, and
      awaits the callback (5-minute ceiling). On success persists the
      tokens via Storage.save_provider_credentials and returns the
      connected Gmail address. Requires an active Firebase session —
      the credentials are stored under owner_id = firebase_uid.

  google.calendar.disconnect()
      Removes the stored Calendar credentials for the active session.

  google.calendar.status()
      Returns {connected: bool, email?: str} without exposing tokens.

  google.calendar.cancel()
      Cancels any in-flight `connect` flow (the user closed the
      browser without consenting and wants to retry).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict

from zylch.auth import NoActiveSession, get_session, require_session
from zylch.tools.google.calendar_oauth import (
    cancel_active_flow,
    disconnect_calendar,
    is_calendar_connected,
    run_calendar_oauth_flow,
)

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


class _NotSignedInError(Exception):
    """Mapped to JSON-RPC application error -32010."""

    code = -32010


async def google_calendar_connect(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """google.calendar.connect() -> {ok, email, scope}

    Awaits up to 5 minutes for the user to complete consent in their
    browser. The renderer learns the consent URL via the
    `google.calendar.auth_url_ready` notification emitted shortly after
    this call begins (we publish it before awaiting the callback so the
    renderer can call shell.openExternal without racing).
    """
    try:
        session = require_session()
    except NoActiveSession as e:
        raise _NotSignedInError(str(e)) from e

    # Run the flow in the background so we can publish the auth URL
    # before awaiting the callback. The handler awaits the same Future
    # afterwards — there's no extra latency, just a clean way to expose
    # the URL exactly once.
    task = asyncio.create_task(run_calendar_oauth_flow(owner_id=session.uid))

    # Wait briefly for the flow object to be initialized so we can read
    # its auth_url_str attribute. The flow object sets the attribute
    # before awaiting the callback (see calendar_oauth.run_calendar_oauth_flow).
    from zylch.tools.google import calendar_oauth as _co

    auth_url_published = False
    for _ in range(50):  # up to ~500ms
        flow = _co._active_flow  # type: ignore[attr-defined]
        url = getattr(flow, "auth_url_str", None) if flow is not None else None
        if url:
            notify("google.calendar.auth_url_ready", {"auth_url": url})
            auth_url_published = True
            break
        await asyncio.sleep(0.01)

    if not auth_url_published:
        # The flow never reached the point where it sets auth_url_str —
        # likely a misconfiguration error (missing client_id). Cancel,
        # then surface whatever the task raised.
        logger.warning(
            "[rpc:google.calendar.connect] auth_url not produced; "
            "letting the task surface its error"
        )

    # Now await the actual completion. Errors propagate to the dispatcher.
    return await task


async def google_calendar_disconnect(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """google.calendar.disconnect() -> {ok}"""
    try:
        session = require_session()
    except NoActiveSession as e:
        raise _NotSignedInError(str(e)) from e
    ok = disconnect_calendar(session.uid)
    return {"ok": ok}


async def google_calendar_status(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """google.calendar.status() -> {connected, signed_in, email?}

    Soft-fails when there is no Firebase session: the renderer mounts
    `ConnectGoogleCalendar` from Settings before the auth handover has
    finished pushing the token to the sidecar, so raising here would
    spam stderr with a stack trace for every mount in the auth-pending
    window. "Not signed in" is a valid status answer — return it.
    """
    session = get_session()
    if session is None:
        return {"connected": False, "signed_in": False}
    connected = is_calendar_connected(session.uid)
    if not connected:
        return {"connected": False, "signed_in": True}

    # Read back the stored email for display only — never the token.
    from zylch.storage import Storage

    try:
        creds = Storage.get_instance().get_provider_credentials(
            session.uid, "google_calendar"
        )
        email = creds.get("email") if isinstance(creds, dict) else None
    except Exception as e:
        logger.warning(f"[rpc:google.calendar.status] readback failed: {e}")
        email = None
    return {"connected": True, "signed_in": True, "email": email}


async def google_calendar_cancel(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """google.calendar.cancel() -> {cancelled}"""
    cancelled = cancel_active_flow()
    return {"cancelled": cancelled}


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "google.calendar.connect": google_calendar_connect,
    "google.calendar.disconnect": google_calendar_disconnect,
    "google.calendar.status": google_calendar_status,
    "google.calendar.cancel": google_calendar_cancel,
}
