"""RPC handlers for Firebase account session management.

Methods, all serving the in-memory FirebaseSession singleton:

  account.set_firebase_token(uid, email, id_token, expires_at_ms)
      Push a fresh ID token from the renderer into the engine. Called
      after Firebase signin and on every proactive refresh (~50 min).

  account.sign_out()
      Clear the cached session. Called when the user explicitly signs
      out from the desktop UI.

  account.who_am_i()
      Return {uid, email, expires_at_ms, signed_in} without exposing
      the token itself. Used by the renderer to verify that the engine
      received its push, and by surfaces that need to render the active
      account label.

  account.balance()
      GET the user's MrCall credit balance from the proxy
      (`mrcall-agent`'s GET /api/desktop/llm/balance). Mirrors the
      server response shape so the renderer can render it directly.

The renderer already holds the token; never echo it back over the wire.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

import httpx

from zylch.auth import clear_session, get_session, require_session, set_session
from zylch.config import settings

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


async def account_set_firebase_token(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """account.set_firebase_token(uid, id_token, expires_at_ms, email?) -> {ok}

    `expires_at_ms` is the absolute Unix-ms timestamp at which Firebase
    will reject the token (the renderer reads this from
    user.getIdTokenResult().expirationTime).
    """
    uid = params.get("uid")
    email = params.get("email")
    id_token = params.get("id_token")
    expires_at_ms = params.get("expires_at_ms")

    if not isinstance(uid, str) or not uid:
        raise ValueError("uid is required")
    if not isinstance(id_token, str) or not id_token:
        raise ValueError("id_token is required")
    if not isinstance(expires_at_ms, int) or expires_at_ms <= 0:
        # JSON-RPC params come from JS; integers may arrive as float when
        # large. Accept floats coerced to int but reject anything else.
        if isinstance(expires_at_ms, float) and expires_at_ms > 0:
            expires_at_ms = int(expires_at_ms)
        else:
            raise ValueError("expires_at_ms must be a positive integer (Unix ms)")
    if email is not None and not isinstance(email, str):
        raise ValueError("email, when provided, must be a string")

    set_session(uid=uid, email=email, id_token=id_token, expires_at_ms=expires_at_ms)

    # Persist the refresh token (encrypted) so a headless daemon can mint
    # fresh ID tokens past the ~1h ID-token lifetime. Optional — older
    # clients don't send it (the session still works while connected). The
    # dispatcher already redacts `refresh_token` from RPC param logging.
    refresh_token = params.get("refresh_token")
    if isinstance(refresh_token, str) and refresh_token:
        try:
            from zylch.storage.storage import Storage

            Storage.get_instance().store_firebase_refresh_token(uid, refresh_token)
        except Exception as e:
            logger.warning(f"[rpc:account.set_firebase_token] refresh-token store failed: {e}")

    logger.debug(
        f"[rpc:account.set_firebase_token] uid={uid} "
        f"email={email!r} expires_at_ms={expires_at_ms} "
        f"refresh_token={'present' if refresh_token else 'absent'}"
    )
    return {"ok": True}


async def account_sign_out(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """account.sign_out() -> {ok}"""
    clear_session()
    logger.debug("[rpc:account.sign_out] cleared")
    return {"ok": True}


async def account_who_am_i(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """account.who_am_i() -> {signed_in, uid?, email?, expires_at_ms?}

    Never echoes the id_token back to the renderer. The renderer is the
    source of truth for the token; this is for "did the engine see my
    push" and for rendering the active account label.
    """
    s = get_session()
    if s is None:
        return {"signed_in": False}
    return {
        "signed_in": True,
        "uid": s.uid,
        "email": s.email,
        "expires_at_ms": s.expires_at_ms,
    }


async def account_balance(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """account.balance() -> {balance_credits, balance_micro_usd, ...}

    Forwards to mrcall-agent's GET /api/desktop/llm/balance using the
    cached Firebase ID token. Server is the source of truth for the
    response shape; we surface it back to the renderer verbatim so a
    server-side schema change doesn't require an engine release.

    Common return shape (from the design doc §11):
        {
          "balance_credits": int,
          "balance_micro_usd": int,
          "balance_usd": float,
          "granularity_micro_usd": int,
          "estimate_messages_remaining": int
        }

    Errors:
        - NoActiveSession (-32010) if the user is not signed in.
        - Returns {"error": "auth_expired"} on 401 (the renderer should
          force a Firebase token refresh and re-call).
        - Otherwise, raises so the dispatcher returns a JSON-RPC error
          to the renderer.
    """
    sess = require_session()
    url = f"{settings.mrcall_proxy_url.rstrip('/')}/api/desktop/llm/balance"
    logger.debug(f"[rpc:account.balance] GET {url} token_len={len(sess.id_token)}")
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(url, headers={"auth": sess.id_token})
    except httpx.HTTPError as exc:
        logger.warning(f"[rpc:account.balance] transport error: {exc}")
        raise

    if r.status_code == 401:
        logger.info("[rpc:account.balance] 401 — Firebase token rejected")
        return {"error": "auth_expired"}
    r.raise_for_status()
    payload = r.json()
    logger.debug(
        f"[rpc:account.balance] ok keys={list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}"
    )
    return payload


async def auth_refresh(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """auth.refresh(id_token) -> {ok, uid, expires_at_ms}.

    Verify a fresh Firebase ID token server-side and replace the cached
    session. WebSocket clients call this before their old token expires
    (the WS server enforces expiry and closes 4401 otherwise). Harmless
    over stdio.

    Unlike `account.set_firebase_token`, this VERIFIES the token (RS256
    against Google's certs) rather than trusting the caller — the
    cross-machine WS backend has no trusted parent process to vouch for
    it. `expires_at_ms` is derived from the token's own `exp`, not from a
    client-supplied value.
    """
    from zylch.rpc.firebase_auth import FirebaseAuthError, verify_firebase_id_token

    id_token = params.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise ValueError("id_token is required")

    try:
        claims = verify_firebase_id_token(id_token)
    except FirebaseAuthError as e:
        err = ValueError(f"token verification failed: {e}")
        err.code = getattr(e, "code", -32011)  # type: ignore[attr-defined]
        raise err

    uid = claims["sub"]
    email = claims.get("email")
    expires_at_ms = int(claims["exp"]) * 1000
    set_session(
        uid=uid,
        email=email if isinstance(email, str) else None,
        id_token=id_token,
        expires_at_ms=expires_at_ms,
    )

    # Persist the refresh token (encrypted) so this profile's headless serve
    # daemon can mint fresh ID tokens once the WS client disconnects — the
    # remote (WS) counterpart of the same storage in set_firebase_token. The
    # dispatcher already redacts `refresh_token` from RPC param logging.
    refresh_token = params.get("refresh_token")
    if isinstance(refresh_token, str) and refresh_token:
        try:
            from zylch.storage.storage import Storage

            Storage.get_instance().store_firebase_refresh_token(uid, refresh_token)
        except Exception as e:
            logger.warning(f"[rpc:auth.refresh] refresh-token store failed: {e}")

    logger.debug(
        f"[rpc:auth.refresh] uid={uid} expires_at_ms={expires_at_ms} "
        f"refresh_token={'present' if refresh_token else 'absent'}"
    )
    return {"ok": True, "uid": uid, "expires_at_ms": expires_at_ms}


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "account.set_firebase_token": account_set_firebase_token,
    "account.sign_out": account_sign_out,
    "account.who_am_i": account_who_am_i,
    "account.balance": account_balance,
    "auth.refresh": auth_refresh,
}
