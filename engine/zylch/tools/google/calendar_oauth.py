"""Google Calendar OAuth2 flow with PKCE for the desktop sidecar.

A separate concern from MrCall OAuth: the renderer is already signed in
to Firebase (which gives it the user's identity + StarChat access) and
this flow only adds the *delegated* permission to read the user's
Google Calendar. Tokens are scoped to the active Firebase UID and
stored in the existing OAuthToken table with provider='google_calendar'.

PKCE is required: Google enforces it for installed-app / public OAuth
clients, and the desktop binary can't keep a client_secret confidential.

Listening port: 19275 (different from the legacy MrCall PKCE flow on
:19274 — they may both be active during development without colliding).

Flow shape:

  1. `start_calendar_oauth_flow()` synthesises a code_verifier +
     code_challenge + state nonce, spins up a one-shot loopback HTTP
     server on :19275, returns the full Google authorize URL.
  2. The renderer opens the URL in the user's default browser via
     Electron's `shell.openExternal`.
  3. The user consents on accounts.google.com; Google redirects to
     `http://127.0.0.1:19275/oauth2/google/callback?code=...&state=...`.
  4. The local server captures the code, the flow exchanges it for
     access + refresh tokens at `oauth2.googleapis.com/token`, fetches
     the userinfo endpoint to discover which Gmail account consented,
     and persists everything via Storage.save_provider_credentials.

The flow has a single concurrent execution model: re-entry while a
flow is in flight cancels the prior one (port :19275 is the
authoritative singleton).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from zylch.config import settings

logger = logging.getLogger(__name__)

# Port chosen to not collide with MrCall PKCE :19274 — both can run
# during dev without stepping on each other. 127.0.0.1 only; never bind
# to all interfaces.
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 19275
CALLBACK_PATH = "/oauth2/google/callback"
REDIRECT_URI = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}{CALLBACK_PATH}"

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# Read-only is enough for the "see my events" desktop feature. Add
# `https://www.googleapis.com/auth/calendar.events` later when we want
# to write events back; the user re-consents through the same flow.
DEFAULT_SCOPES = " ".join(
    [
        "openid",
        "email",
        "https://www.googleapis.com/auth/calendar.readonly",
    ]
)

# Calendar ID the desktop reads from. Google's API treats `"primary"`
# as the alias for the user's main calendar (the one tied to their
# Google account email — exactly the calendar the user just consented
# with via the OAuth flow above). Future code that wants to enumerate
# secondary calendars should hit `/calendar/v3/users/me/calendarList`
# explicitly; everything else should use this constant.
DEFAULT_CALENDAR_ID = "primary"


def _generate_pkce() -> Tuple[str, str]:
    """Return (code_verifier, code_challenge) using the S256 method."""
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


class _CallbackHandler(BaseHTTPRequestHandler):
    # Each flow attaches its own future onto the handler class so the
    # GET below can resolve it. Class-level so the BaseHTTPRequestHandler
    # subclass can reach it without a custom __init__ (HTTPServer
    # instantiates handlers per-request).
    _waiting_future: "Optional[asyncio.Future[Dict[str, Any]]]" = None
    _waiting_loop: Optional[asyncio.AbstractEventLoop] = None
    _expected_state: Optional[str] = None

    def do_GET(self) -> None:  # noqa: N802 — http.server convention
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        params = parse_qs(parsed.query)
        result: Dict[str, Any] = {}
        body: str
        if "error" in params:
            result = {"error": params["error"][0]}
            body = (
                "<html><body><h2>Google Calendar — authorization denied</h2>"
                "<p>You can close this window and return to MrCall Desktop.</p>"
                "</body></html>"
            )
        elif "code" in params:
            received_state = params.get("state", [""])[0]
            if (
                _CallbackHandler._expected_state
                and received_state != _CallbackHandler._expected_state
            ):
                result = {"error": "state_mismatch"}
                body = (
                    "<html><body><h2>State mismatch</h2>"
                    "<p>The authorization response did not match the request "
                    "(possible CSRF). Try again from MrCall Desktop.</p>"
                    "</body></html>"
                )
            else:
                result = {"code": params["code"][0], "state": received_state}
                body = (
                    "<html><body><h2>Google Calendar connected</h2>"
                    "<p>You can close this window and return to MrCall Desktop.</p>"
                    "</body></html>"
                )
        else:
            result = {"error": "no_code"}
            body = (
                "<html><body><h2>Error</h2><p>No authorization code "
                "received.</p></body></html>"
            )

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body.encode())

        fut = _CallbackHandler._waiting_future
        loop = _CallbackHandler._waiting_loop
        if fut is not None and loop is not None and not fut.done():
            # Resolve on the asyncio loop's thread — the HTTP server runs
            # in its own thread, so we cross threads via call_soon_threadsafe.
            loop.call_soon_threadsafe(fut.set_result, result)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        logger.debug("[google-cal-oauth] callback server: " + (format % args))


class _OAuthFlow:
    """One in-flight Google Calendar OAuth attempt."""

    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self.code_verifier, self.code_challenge = _generate_pkce()
        self.state = secrets.token_urlsafe(24)
        self._future: Optional[asyncio.Future[Dict[str, Any]]] = None
        self._server: Optional[HTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None

    def auth_url(self) -> str:
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": DEFAULT_SCOPES,
            "state": self.state,
            "code_challenge": self.code_challenge,
            "code_challenge_method": "S256",
            # `prompt=consent` forces Google to issue a refresh_token
            # every time — without it, returning users get only an
            # access_token and our offline access disappears after 60
            # min. `access_type=offline` is the actual request, prompt
            # is the refresh_token guarantee.
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    def start(self, loop: asyncio.AbstractEventLoop) -> "asyncio.Future[Dict[str, Any]]":
        if self._future is not None:
            raise RuntimeError("flow already started")
        self._future = loop.create_future()
        _CallbackHandler._waiting_future = self._future
        _CallbackHandler._waiting_loop = loop
        _CallbackHandler._expected_state = self.state
        self._server = HTTPServer((CALLBACK_HOST, CALLBACK_PORT), _CallbackHandler)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever, name="google-cal-oauth-cb", daemon=True
        )
        self._server_thread.start()
        return self._future

    def stop(self) -> None:
        # Order matters: shutdown() blocks until serve_forever returns,
        # so it has to come before server_close() (which would otherwise
        # error from the still-running serve thread).
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception as e:
                logger.warning(f"[google-cal-oauth] server shutdown failed: {e}")
        _CallbackHandler._waiting_future = None
        _CallbackHandler._waiting_loop = None
        _CallbackHandler._expected_state = None

    async def exchange_code(self, code: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self.client_id,
                    # Google explicitly does NOT require client_secret
                    # for native/desktop installed-app PKCE flows.
                    "redirect_uri": REDIRECT_URI,
                    "grant_type": "authorization_code",
                    "code_verifier": self.code_verifier,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def fetch_userinfo(self, access_token: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return resp.json()


# Module-level singleton of the active flow. We accept exactly one in
# flight at a time — re-entrant calls to `start_calendar_oauth_flow`
# stop the previous one first so :19275 can be re-bound cleanly.
_active_flow: Optional[_OAuthFlow] = None
_active_lock = threading.Lock()


def get_google_client_id() -> Optional[str]:
    """Pull the OAuth client ID from settings (env / .env).

    Read on every call so a Settings update takes effect without a
    sidecar restart. Falls back to the build-time default the Electron
    main process injects via GOOGLE_CALENDAR_CLIENT_ID_DEFAULT (the
    same Desktop OAuth client used for "Continue with Google" sign-in)
    so packaged installs can connect Calendar without any manual
    configuration. Returns None if both are unset.
    """
    cid = (settings.google_calendar_client_id or "").strip()
    if cid:
        return cid
    default_cid = (settings.google_calendar_client_id_default or "").strip()
    return default_cid or None


async def run_calendar_oauth_flow(*, owner_id: str) -> Dict[str, Any]:
    """Run the full Calendar OAuth flow and persist the tokens.

    Args:
        owner_id: Firebase UID — credentials are scoped to it via
            OAuthToken.owner_id.

    Returns:
        {"ok": True, "email": "<gmail>", "scope": "<scope str>"}

    Raises:
        RuntimeError: when GOOGLE_CALENDAR_CLIENT_ID is missing.
        TimeoutError: when the user doesn't complete consent in 5 min.
        httpx.HTTPStatusError: on Google API errors.
    """
    client_id = get_google_client_id()
    if not client_id:
        raise RuntimeError(
            "GOOGLE_CALENDAR_CLIENT_ID is not configured. "
            "Set it in Settings or in your profile .env."
        )

    global _active_flow
    with _active_lock:
        if _active_flow is not None:
            logger.info("[google-cal-oauth] cancelling previous in-flight flow")
            try:
                _active_flow.stop()
            except Exception:
                pass
        flow = _OAuthFlow(client_id=client_id)
        _active_flow = flow

    loop = asyncio.get_event_loop()
    future = flow.start(loop)

    try:
        # Emit the URL to the caller via the return value of a notify-
        # equivalent — but our handler signature returns the URL through
        # a side channel. Keeping it inside this function means the RPC
        # layer announces the URL in a notification BEFORE awaiting the
        # callback. We expose this via an attribute so the RPC handler
        # can read it.
        flow_auth_url = flow.auth_url()
        flow.auth_url_str = flow_auth_url  # type: ignore[attr-defined]

        # Wait for the loopback callback (5-minute ceiling — enough for
        # consent + 2FA, short enough that an abandoned flow times out
        # rather than holding :19275 indefinitely).
        result = await asyncio.wait_for(future, timeout=300)
    finally:
        try:
            flow.stop()
        except Exception:
            pass
        with _active_lock:
            if _active_flow is flow:
                _active_flow = None

    if "error" in result:
        raise RuntimeError(f"google_oauth_error: {result['error']}")

    code = result["code"]
    tokens = await flow.exchange_code(code)
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token", "")
    if not access_token:
        raise RuntimeError("Google did not return an access_token")

    # Userinfo tells us *which* Google account the user just consented
    # with — we store the email so the UI can label "Calendar (alice@…)".
    userinfo = await flow.fetch_userinfo(access_token)
    google_email = userinfo.get("email", "")

    # Persist via the existing encrypted Storage (Fernet at-rest). We
    # match the column shape used by the legacy MrCall flow so future
    # token-refresh code can be shared.
    from zylch.storage import Storage

    creds: Dict[str, Any] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "scope": tokens.get("scope", DEFAULT_SCOPES),
        "expires_in": tokens.get("expires_in", 3600),
        "token_type": tokens.get("token_type", "Bearer"),
        "email": google_email,
        "id_token": tokens.get("id_token", ""),
    }
    Storage.get_instance().save_provider_credentials(
        owner_id, "google_calendar", creds
    )
    logger.info(
        f"[google-cal-oauth] tokens stored owner_id={owner_id} email={google_email!r}"
    )

    return {"ok": True, "email": google_email, "scope": creds["scope"]}


def cancel_active_flow() -> bool:
    """Cancel any in-flight flow. Returns True iff one was cancelled."""
    global _active_flow
    with _active_lock:
        if _active_flow is None:
            return False
        try:
            _active_flow.stop()
        finally:
            _active_flow = None
    return True


def is_calendar_connected(owner_id: str) -> bool:
    """Check whether stored Calendar credentials exist for owner_id."""
    try:
        from zylch.storage import Storage

        creds = Storage.get_instance().get_provider_credentials(owner_id, "google_calendar")
        return bool(creds and creds.get("access_token"))
    except Exception:
        return False


def disconnect_calendar(owner_id: str) -> bool:
    """Remove stored Calendar credentials. Returns True iff anything was deleted."""
    try:
        from zylch.storage import Storage

        Storage.get_instance().delete_provider_credentials(owner_id, "google_calendar")
        return True
    except Exception as e:
        logger.warning(f"[google-cal-oauth] disconnect failed: {e}")
        return False
