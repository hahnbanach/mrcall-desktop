"""Server-side Firebase ID-token refresh for headless operation.

A Firebase ID token lives ~1 hour. While the desktop app is connected it
re-pushes a fresh token every ~50 min, so the engine's in-memory session
stays valid. But a ``serve`` daemon running headless (app closed) has no
pusher: once the cached token expires, every MrCall-credits proxy call
401s — and the daemon used to keep hammering for days.

To survive past the hour headless, we persist the Firebase *refresh*
token (encrypted, via OAuthToken provider='firebase') the first time the
renderer pushes it, and exchange it for a fresh ID token through Google's
Secure Token API whenever the cached one is near expiry.

Security note: the refresh token is long-lived (until revoked) and can
mint ID tokens for the user. It is stored encrypted at rest like every
other OAuth credential; the VPS disk is the trust boundary.
"""

from __future__ import annotations

import logging
import time

import httpx

from .session import get_session, set_session
from .verified_session import SessionAdmissionError, verified_claims

logger = logging.getLogger(__name__)

# Refresh this far before the absolute expiry so an in-flight pipeline
# never races the boundary.
_SKEW_MS = 5 * 60 * 1000

_SECURE_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"


def exchange_refresh_token(refresh_token: str, api_key: str) -> dict:
    """Exchange a Firebase refresh token for a fresh ID token.

    Returns ``{id_token, refresh_token, expires_at_ms}``. Raises on any
    transport/HTTP error (caller decides whether that's fatal).
    """
    resp = httpx.post(
        _SECURE_TOKEN_URL,
        params={"key": api_key},
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    expires_in = int(data.get("expires_in") or 3600)
    return {
        "id_token": data["id_token"],
        # Google may rotate the refresh token; keep the old one if it didn't.
        "refresh_token": data.get("refresh_token") or refresh_token,
        "expires_at_ms": int(time.time() * 1000) + expires_in * 1000,
    }


def ensure_fresh_session(owner_id: str) -> bool:
    """Guarantee a non-expired in-memory session for ``owner_id``.

    If the cached session is still comfortably valid, do nothing. Otherwise
    load the stored refresh token and exchange it for a fresh ID token.
    Returns True if a usable (non-expired) session is in place afterwards,
    False if there's nothing to refresh with or the exchange failed.

    Synchronous (blocking httpx + DB) — call it via ``asyncio.to_thread``
    from async contexts.
    """
    sess = get_session()
    now = int(time.time() * 1000)
    verified_expiry = 0
    if sess is not None and sess.uid == owner_id:
        try:
            claims = verified_claims(sess.id_token, requested_uid=owner_id)
            verified_expiry = int(claims["exp"]) * 1000
        except SessionAdmissionError:
            pass
        if now < verified_expiry - _SKEW_MS:
            email = claims.get("email")
            set_session(
                uid=claims["sub"],
                email=email if isinstance(email, str) else None,
                id_token=sess.id_token,
                expires_at_ms=verified_expiry,
            )
            return True

    def existing_is_usable() -> bool:
        return int(time.time() * 1000) < verified_expiry

    from zylch.config import settings
    from zylch.storage.storage import Storage

    try:
        refresh_token = Storage.get_instance().get_firebase_refresh_token(owner_id)
    except Exception:
        logger.warning("[auth] could not read stored refresh token")
        refresh_token = None

    if not refresh_token:
        # No way to refresh — report whether the existing session is still usable.
        return existing_is_usable()

    api_key = settings.firebase_web_api_key
    if not api_key:
        logger.warning("[auth] no FIREBASE_WEB_API_KEY configured — cannot refresh headless")
        return existing_is_usable()

    try:
        fresh = exchange_refresh_token(refresh_token, api_key)
    except Exception:
        logger.warning("[auth] refresh-token exchange failed")
        return existing_is_usable()

    try:
        claims = verified_claims(fresh["id_token"], requested_uid=owner_id)
    except SessionAdmissionError:
        logger.warning("[auth] refreshed Firebase identity refused")
        return existing_is_usable()
    uid = claims["sub"]
    email = claims.get("email")
    set_session(
        uid=uid,
        email=email if isinstance(email, str) else None,
        id_token=fresh["id_token"],
        expires_at_ms=int(claims["exp"]) * 1000,
    )
    if fresh["refresh_token"] != refresh_token:
        try:
            Storage.get_instance().store_firebase_refresh_token(owner_id, fresh["refresh_token"])
        except Exception:
            logger.warning("[auth] could not persist rotated refresh token")
    logger.info(f"[auth] refreshed Firebase session for {owner_id} via stored refresh token")
    return True
