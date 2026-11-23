from __future__ import annotations

import base64
import hashlib
import math
import os
import secrets
import threading
import time
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

PROVIDER = "google_gmail"
PENDING_PROVIDER = "google_gmail_pending"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
FULL_SCOPE = "https://mail.google.com/"
API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:19275/oauth2/google/gmail/callback"
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_LOCK = threading.Lock()


class GmailError(RuntimeError):
    code = -32030

    def __init__(self, reason: str, http_status: int | None = None):
        self.reason = reason
        self.http_status = http_status
        self.non_dispatch = False
        super().__init__(reason if http_status is None else f"{reason} (HTTP {http_status})")


def _lock(owner_id: str) -> threading.RLock:
    with _LOCKS_LOCK:
        return _LOCKS.setdefault(owner_id, threading.RLock())


def _store():
    from zylch.storage import Storage

    return Storage.get_instance()


def _profile_owner() -> str:
    from zylch.auth import get_session
    from zylch.cli.profiles import get_active_profile

    active = get_active_profile()
    session = get_session()
    if active and "@" not in active:
        if session is not None and session.uid != active:
            raise GmailError("gmail_profile_mismatch")
        return active
    if session is not None:
        return session.uid
    raise GmailError("gmail_profile_unavailable")


def _configured_owner(owner: str) -> str:
    configured = os.environ.get("EMAIL_ADDRESS", "").strip().lower()
    normalized = owner.strip().lower() if isinstance(owner, str) else ""
    if not normalized or "@" not in normalized or (configured and configured != normalized):
        raise GmailError("gmail_mailbox_mismatch")
    return normalized


def _client_settings() -> tuple[str, str]:
    from zylch.tools.google.calendar_oauth import get_google_client_id, get_google_client_secret

    client_id = os.environ.get("GOOGLE_GMAIL_CLIENT_ID") or get_google_client_id()
    secret = os.environ.get("GOOGLE_GMAIL_CLIENT_SECRET")
    if secret is None:
        secret = get_google_client_secret()
    if not isinstance(client_id, str) or not client_id.strip():
        raise GmailError("gmail_oauth_client_not_configured")
    return client_id.strip(), secret or ""


def _allowed_redirects() -> list[str]:
    import json

    raw = os.environ.get("GOOGLE_GMAIL_REDIRECT_URIS")
    try:
        values = json.loads(raw) if raw else [DEFAULT_REDIRECT_URI]
    except (TypeError, ValueError):
        raise GmailError("gmail_oauth_redirect_configuration_invalid") from None
    if not isinstance(values, list) or not values or any(not isinstance(v, str) for v in values):
        raise GmailError("gmail_oauth_redirect_configuration_invalid")
    for value in values:
        parsed = urlsplit(value)
        if (
            not parsed.hostname or parsed.username or parsed.password or parsed.fragment
            or parsed.query or any(c in value for c in "\r\n")
            or (parsed.scheme != "https" and not (
                parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            ))
        ):
            raise GmailError("gmail_oauth_redirect_configuration_invalid")
    return values


def _scope_ok(value: Any) -> bool:
    return isinstance(value, str) and bool({GMAIL_SCOPE, FULL_SCOPE} & set(value.split()))


def _json_request(client: httpx.Client, method: str, url: str, **kwargs) -> dict[str, Any]:
    try:
        response = client.request(method, url, follow_redirects=False, **kwargs)
    except httpx.HTTPError:
        raise GmailError("gmail_provider_unavailable") from None
    if not 200 <= response.status_code < 300:
        reason = "gmail_authorization_required" if response.status_code in {401, 403} else "gmail_provider_error"
        raise GmailError(reason, response.status_code)
    try:
        result = response.json()
    except (ValueError, UnicodeError):
        raise GmailError("gmail_provider_response_invalid") from None
    if not isinstance(result, dict):
        raise GmailError("gmail_provider_response_invalid")
    return result


def _validate_credentials(credentials: Any, owner: str) -> dict[str, Any]:
    if not isinstance(credentials, dict) or not credentials:
        raise GmailError("gmail_authorization_required")
    if str(credentials.get("email", "")).strip().lower() != owner:
        raise GmailError("gmail_mailbox_mismatch")
    if not _scope_ok(credentials.get("scope")):
        raise GmailError("gmail_scope_missing")
    if not isinstance(credentials.get("access_token"), str) or not credentials["access_token"]:
        raise GmailError("gmail_authorization_required")
    return credentials


class GmailAuth:
    def __init__(self, owner: str, *, credential_owner: str | None = None, store=None, http_client=None):
        self.owner = _configured_owner(owner)
        self.credential_owner = credential_owner or _profile_owner()
        self.store = store if store is not None else _store()
        self.client = http_client if http_client is not None else httpx.Client(timeout=30, follow_redirects=False)
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def access_token(self) -> str:
        with _lock(self.credential_owner):
            creds = _validate_credentials(
                self.store.get_provider_credentials(self.credential_owner, PROVIDER), self.owner
            )
            try:
                expires_at = float(creds.get("expires_at", 0))
                if not math.isfinite(expires_at):
                    raise ValueError()
            except (TypeError, ValueError):
                raise GmailError("gmail_token_expiry_invalid") from None
            if expires_at > time.time() + 60:
                return creds["access_token"]
            refresh = creds.get("refresh_token")
            if not isinstance(refresh, str) or not refresh:
                raise GmailError("gmail_authorization_required")
            client_id, secret = _client_settings()
            if creds.get("client_id") != client_id:
                raise GmailError("gmail_oauth_client_mismatch")
            data = {"grant_type": "refresh_token", "refresh_token": refresh, "client_id": client_id}
            if secret:
                data["client_secret"] = secret
            token = _json_request(self.client, "POST", TOKEN_URL, data=data)
            scope = token.get("scope", creds["scope"])
            if not _scope_ok(scope):
                raise GmailError("gmail_scope_missing")
            updated = dict(creds, scope=scope, access_token=_access_token(token), expires_at=_expiry(token))
            if token.get("refresh_token"):
                updated["refresh_token"] = token["refresh_token"]
            self.store.save_provider_credentials(self.credential_owner, PROVIDER, updated)
            return updated["access_token"]

    def verify(self) -> dict[str, Any]:
        profile = _json_request(self.client, "GET", API_ROOT + "/profile", headers={
            "Authorization": "Bearer " + self.access_token(),
        })
        if str(profile.get("emailAddress", "")).strip().lower() != self.owner:
            raise GmailError("gmail_mailbox_mismatch")
        return {"email": self.owner, "scope": GMAIL_SCOPE}


def _access_token(token: dict[str, Any]) -> str:
    value = token.get("access_token")
    token_type = token.get("token_type", "Bearer")
    if not isinstance(value, str) or not value or not isinstance(token_type, str) or token_type.lower() != "bearer":
        raise GmailError("gmail_token_response_invalid")
    return value


def _expiry(token: dict[str, Any]) -> float:
    try:
        seconds = float(token["expires_in"])
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise GmailError("gmail_token_expiry_invalid") from None
    return time.time() + seconds


def begin(owner: str, *, redirect_uri: str | None = None, credential_owner: str | None = None, store=None) -> dict[str, Any]:
    owner = _configured_owner(owner)
    uid = credential_owner or _profile_owner()
    store = store if store is not None else _store()
    client_id, _secret = _client_settings()
    allowed = _allowed_redirects()
    redirect = redirect_uri or allowed[0]
    if redirect not in allowed:
        raise GmailError("gmail_oauth_redirect_not_allowed")
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    with _lock(uid):
        store.save_provider_credentials(uid, PENDING_PROVIDER, {
            "email": owner, "state": state, "code_verifier": verifier, "redirect_uri": redirect,
            "client_id": client_id, "expires_at": time.time() + 600,
        })
    query = {
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code",
        "scope": "openid email " + GMAIL_SCOPE, "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent",
        "login_hint": owner,
    }
    return {"auth_url": AUTH_URL + "?" + urlencode(query), "state": state, "redirect_uri": redirect, "expires_in": 600}


def complete(owner: str, code: str, state: str, *, credential_owner: str | None = None, store=None, http_client=None) -> dict[str, Any]:
    owner = _configured_owner(owner)
    uid = credential_owner or _profile_owner()
    store = store if store is not None else _store()
    if not isinstance(code, str) or not code or not isinstance(state, str) or not state:
        raise GmailError("gmail_oauth_callback_invalid")
    with _lock(uid):
        pending = store.get_provider_credentials(uid, PENDING_PROVIDER)
        if not isinstance(pending, dict) or not secrets.compare_digest(str(pending.get("state", "")), state):
            raise GmailError("gmail_oauth_state_mismatch")
        try:
            expiry = float(pending.get("expires_at", 0))
        except (ValueError, TypeError):
            raise GmailError("gmail_oauth_expired") from None
        if not math.isfinite(expiry) or expiry <= time.time():
            raise GmailError("gmail_oauth_expired")
        if pending.get("email") != owner:
            raise GmailError("gmail_mailbox_mismatch")
        if pending.get("redirect_uri") not in _allowed_redirects():
            raise GmailError("gmail_oauth_redirect_not_allowed")
        client_id, secret = _client_settings()
        if pending.get("client_id") != client_id:
            raise GmailError("gmail_oauth_client_mismatch")
        verifier = pending.get("code_verifier")
        if not isinstance(verifier, str) or not verifier:
            raise GmailError("gmail_oauth_callback_invalid")
        store.delete_provider_credentials(uid, PENDING_PROVIDER)
        client = http_client if http_client is not None else httpx.Client(timeout=30, follow_redirects=False)
        try:
            data = {"grant_type": "authorization_code", "code": code, "client_id": client_id,
                    "redirect_uri": pending["redirect_uri"], "code_verifier": verifier}
            if secret:
                data["client_secret"] = secret
            token = _json_request(client, "POST", TOKEN_URL, data=data)
            access = _access_token(token)
            if not _scope_ok(token.get("scope")):
                raise GmailError("gmail_scope_missing")
            profile = _json_request(client, "GET", API_ROOT + "/profile", headers={"Authorization": "Bearer " + access})
            if str(profile.get("emailAddress", "")).strip().lower() != owner:
                raise GmailError("gmail_mailbox_mismatch")
            refresh = token.get("refresh_token")
            if not isinstance(refresh, str) or not refresh:
                raise GmailError("gmail_refresh_token_missing")
            credentials = {"email": owner, "access_token": access, "refresh_token": refresh,
                           "scope": token["scope"], "expires_at": _expiry(token), "client_id": client_id}
            store.save_provider_credentials(uid, PROVIDER, credentials)
            return {"ok": True, "email": owner, "scope": token["scope"]}
        finally:
            if http_client is None:
                client.close()


def status(owner: str, *, credential_owner: str | None = None, store=None) -> dict[str, Any]:
    owner = _configured_owner(owner)
    uid = credential_owner or _profile_owner()
    store = store if store is not None else _store()
    try:
        _validate_credentials(store.get_provider_credentials(uid, PROVIDER), owner)
    except GmailError as exc:
        return {"connected": False, "reason": exc.reason}
    return {"connected": True, "email": owner, "scope": GMAIL_SCOPE}


def disconnect(owner: str, *, credential_owner: str | None = None, store=None) -> dict[str, Any]:
    _configured_owner(owner)
    uid = credential_owner or _profile_owner()
    store = store if store is not None else _store()
    with _lock(uid):
        store.delete_provider_credentials(uid, PENDING_PROVIDER)
        store.delete_provider_credentials(uid, PROVIDER)
    return {"ok": True}
