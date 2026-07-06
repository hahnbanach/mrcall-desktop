"""RPC handlers for the desktop SMS-sender (SMS_FROM) Settings field.

  - sms.get_sender()        -> GET  /api/desktop/sms/sender  -> {sender, business_id}
  - sms.set_sender(sender)  -> PUT  /api/desktop/sms/sender  -> {sender, business_id}

Both forward the signed-in user's Firebase ID token to mrcall-agent in the
bare ``auth:`` header (same convention as ``account.balance``); mrcall-agent
reads/writes the per-business StarChat variable SMS_FROM. The payload is
returned to the renderer verbatim, or ``{"error": "auth_expired"}`` on a 401
so the renderer can refresh the token and retry.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable, Dict

import httpx

from zylch.auth.session import require_session
from zylch.config import settings

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


def _sender_url() -> str:
    return f"{settings.mrcall_proxy_url.rstrip('/')}/api/desktop/sms/sender"


def _billing_business_id() -> str:
    """The explicit billing business (profile ``SMS_BUSINESS_ID``).

    Read from ``os.environ`` — NOT the frozen ``settings`` singleton, which
    snapshots the ``.env`` at daemon start — so a ``settings.update`` (which
    hot-reloads ``os.environ`` via ``settings_io.update_env``) is picked up
    WITHOUT a daemon restart. Same convention as ``tools/sms_send.py``.

    Required for admin / multi-assistant accounts (support@ is a reseller
    token that sees EVERY business, so mrcall-agent's ``resolve_business_id``
    refuses to guess and returns 400 ``business_id_required``); a single-
    business owner works with it unset (empty → omitted → server uses the
    sole visible business).
    """
    return os.environ.get("SMS_BUSINESS_ID", "").strip()


async def sms_get_sender(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """sms.get_sender() -> {sender, business_id} | {error: 'auth_expired'}."""
    sess = require_session()
    url = _sender_url()
    business_id = _billing_business_id()
    params_q = {"business_id": business_id} if business_id else None
    logger.debug(
        f"[rpc:sms.get_sender] GET {url} business_id={business_id or '(unset)'} "
        f"token_len={len(sess.id_token)}"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(url, headers={"auth": sess.id_token}, params=params_q)
    except httpx.HTTPError as exc:
        logger.warning(f"[rpc:sms.get_sender] transport error: {exc}")
        raise
    if r.status_code == 401:
        return {"error": "auth_expired"}
    r.raise_for_status()
    return r.json()


async def sms_set_sender(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """sms.set_sender(sender) -> {sender, business_id} | {error: 'auth_expired'}."""
    sender = (params or {}).get("sender")
    if not isinstance(sender, str) or not sender.strip():
        raise ValueError("sender is required and must be a non-empty string")
    sender = sender.strip()[:11]

    sess = require_session()
    url = _sender_url()
    business_id = _billing_business_id()
    body: Dict[str, Any] = {"sender": sender}
    if business_id:
        body["business_id"] = business_id
    logger.debug(
        f"[rpc:sms.set_sender] PUT {url} sender_len={len(sender)} "
        f"business_id={business_id or '(unset)'} token_len={len(sess.id_token)}"
    )
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.put(url, headers={"auth": sess.id_token}, json=body)
    except httpx.HTTPError as exc:
        logger.warning(f"[rpc:sms.set_sender] transport error: {exc}")
        raise
    if r.status_code == 401:
        return {"error": "auth_expired"}
    r.raise_for_status()
    logger.info(f"[rpc:sms.set_sender] set -> {sender!r}")
    return r.json()


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "sms.get_sender": sms_get_sender,
    "sms.set_sender": sms_set_sender,
}
