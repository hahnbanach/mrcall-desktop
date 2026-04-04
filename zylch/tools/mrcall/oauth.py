"""MrCall OAuth2 CLI flow.

Implements authorization code flow with PKCE for CLI:
1. Start temporary local HTTP server for callback
2. Open browser to MrCall consent page
3. Receive authorization code
4. Exchange for access + refresh tokens
5. Store encrypted in SQLite via Storage
"""

import base64
import hashlib
import logging
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from zylch.config import settings

logger = logging.getLogger(__name__)

CALLBACK_PORT = 19274
CALLBACK_PATH = "/auth/mrcall/callback"
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}"

# Scopes Zylch needs from MrCall
DEFAULT_SCOPES = "business:read contacts:read sessions:read"


def _generate_pkce() -> Tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge."""
    verifier = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


def _build_authorize_url(state: str, code_challenge: str) -> str:
    """Build the MrCall OAuth consent URL."""
    base = settings.mrcall_dashboard_url.rstrip("/")
    params = {
        "response_type": "code",
        "client_id": settings.mrcall_client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": DEFAULT_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{base}/oauth/authorize?{urlencode(params)}"


def _exchange_code(code: str, code_verifier: str) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    url = f"{settings.mrcall_base_url.rstrip('/')}/oauth/token"
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": settings.mrcall_client_id,
        "client_secret": settings.mrcall_client_secret,
        "code_verifier": code_verifier,
    }

    logger.debug(f"[mrcall-oauth] exchanging code at {url}")
    resp = httpx.post(url, json=payload, verify=settings.starchat_verify_ssl, timeout=30)
    resp.raise_for_status()
    return resp.json()


def refresh_mrcall_token(refresh_token: str) -> dict:
    """Refresh an expired MrCall access token."""
    url = f"{settings.mrcall_base_url.rstrip('/')}/oauth/token/refresh"
    payload = {
        "refresh_token": refresh_token,
        "client_id": settings.mrcall_client_id,
        "client_secret": settings.mrcall_client_secret,
    }

    logger.debug("[mrcall-oauth] refreshing token")
    resp = httpx.post(url, json=payload, verify=settings.starchat_verify_ssl, timeout=30)
    resp.raise_for_status()
    return resp.json()


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler that captures the OAuth callback."""

    auth_code: Optional[str] = None
    auth_state: Optional[str] = None
    auth_error: Optional[str] = None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)

        if "error" in params:
            _OAuthCallbackHandler.auth_error = params["error"][0]
            body = "<html><body><h2>Authorization denied</h2><p>You can close this window.</p></body></html>"
        elif "code" in params:
            _OAuthCallbackHandler.auth_code = params["code"][0]
            _OAuthCallbackHandler.auth_state = params.get("state", [""])[0]
            body = "<html><body><h2>MrCall connected!</h2><p>You can close this window and return to Zylch.</p></body></html>"
        else:
            _OAuthCallbackHandler.auth_error = "no_code"
            body = "<html><body><h2>Error</h2><p>No authorization code received.</p></body></html>"

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, format, *args):
        """Suppress default HTTP server logging."""
        logger.debug(f"[mrcall-oauth] callback server: {format % args}")


def run_oauth_flow(owner_id: str) -> Optional[dict]:
    """Run the full MrCall OAuth2 CLI flow.

    Opens browser for consent, waits for callback,
    exchanges code for tokens, stores in SQLite.

    Returns:
        Token dict on success, None on failure.
    """
    if not settings.mrcall_client_id:
        logger.error("[mrcall-oauth] MRCALL_CLIENT_ID not configured")
        return None

    # Generate PKCE + state
    state = secrets.token_urlsafe(16)
    code_verifier, code_challenge = _generate_pkce()

    # Reset handler state
    _OAuthCallbackHandler.auth_code = None
    _OAuthCallbackHandler.auth_state = None
    _OAuthCallbackHandler.auth_error = None

    # Start local callback server
    server = HTTPServer(("127.0.0.1", CALLBACK_PORT), _OAuthCallbackHandler)
    server_thread = threading.Thread(target=server.handle_request, daemon=True)
    server_thread.start()

    # Open browser
    auth_url = _build_authorize_url(state, code_challenge)
    logger.info("[mrcall-oauth] opening browser for consent")
    webbrowser.open(auth_url)

    # Wait for callback (up to 120s)
    server_thread.join(timeout=120)
    server.server_close()

    # Check result
    if _OAuthCallbackHandler.auth_error:
        logger.error(f"[mrcall-oauth] auth error: {_OAuthCallbackHandler.auth_error}")
        return None

    code = _OAuthCallbackHandler.auth_code
    if not code:
        logger.error("[mrcall-oauth] no authorization code received (timeout?)")
        return None

    # Verify state
    if _OAuthCallbackHandler.auth_state != state:
        logger.error("[mrcall-oauth] state mismatch — possible CSRF")
        return None

    # Exchange code for tokens
    try:
        tokens = _exchange_code(code, code_verifier)
    except httpx.HTTPStatusError as e:
        logger.error(f"[mrcall-oauth] token exchange failed: {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"[mrcall-oauth] token exchange error: {e}")
        return None

    # Store tokens
    try:
        from zylch.storage import Storage

        creds = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token", ""),
            "target_owner": tokens.get("target_owner", ""),
            "scope": tokens.get("scope", DEFAULT_SCOPES),
            "expires_in": tokens.get("expires_in", 3600),
            "realm": settings.mrcall_realm,
        }
        storage = Storage.get_instance()
        storage.save_provider_credentials(owner_id, "mrcall", creds)
        logger.info("[mrcall-oauth] tokens stored successfully")
    except Exception as e:
        logger.error(f"[mrcall-oauth] failed to store tokens: {e}")
        return tokens  # Return tokens even if storage fails

    return tokens


def check_mrcall_connected(owner_id: str) -> bool:
    """Check if MrCall OAuth tokens exist for this owner."""
    try:
        from zylch.api.token_storage import get_mrcall_credentials

        creds = get_mrcall_credentials(owner_id)
        return bool(creds and creds.get("access_token"))
    except Exception:
        return False
