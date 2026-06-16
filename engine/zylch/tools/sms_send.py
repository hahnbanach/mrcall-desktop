"""Shared SMS send via the MrCall credits proxy (mrcall-agent -> Vonage).

Single SMS code path for the whole engine: both the assistant `SendSMSTool`
and the solve-flow `_send_sms` call `send_sms_via_proxy`. Routes to
`POST {MRCALL_PROXY_URL}/api/desktop/sms/send` with the signed-in user's
Firebase ID token (header `auth:`, no Bearer — same convention as the LLM
proxy). Billed server-side to the unified CALLCREDIT pool; the sender is the
server-side alphanumeric ID, so there is nothing to configure per user.

Sync on purpose (`httpx.post`): the solve dispatch is sync; the async
assistant tool wraps this in a thread executor so it never blocks the loop.
Never raises — every failure becomes a user-facing `SmsSendOutcome.message`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SmsSendOutcome:
    """Result of an SMS send attempt. `message` is always user-facing."""

    ok: bool
    message: str
    message_id: Optional[str] = None
    cost_credits: Optional[int] = None
    segments: Optional[int] = None
    status_code: Optional[int] = None


def send_sms_via_proxy(phone: str, message: str) -> SmsSendOutcome:
    """Send one SMS through the MrCall credits proxy. Never raises."""
    phone = (phone or "").strip()
    message = message or ""
    if not phone or not message:
        return SmsSendOutcome(False, "Missing phone number or message.")

    from zylch.auth.session import get_session

    sess = get_session()
    if sess is None:
        return SmsSendOutcome(False, "SMS needs MrCall sign-in — sign in to MrCall first.")

    import httpx

    from zylch.config import settings

    url = f"{settings.mrcall_proxy_url.rstrip('/')}/api/desktop/sms/send"
    payload = {"phone_number": phone, "message": message}
    # Explicit billing business (profile SMS_BUSINESS_ID). Required for admin /
    # multi-assistant accounts — the server refuses to guess otherwise. Omit
    # the key entirely when unset so a single-business owner still works.
    if settings.sms_business_id:
        payload["business_id"] = settings.sms_business_id
    try:
        resp = httpx.post(
            url,
            headers={"auth": sess.id_token, "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
    except Exception as e:
        logger.error(f"[send_sms] transport error to proxy: {e}")
        return SmsSendOutcome(False, f"SMS failed to send (network error: {e}).")

    sc = resp.status_code
    if sc == 200:
        cost = seg = msg_id = None
        try:
            data = resp.json()
            cost = data.get("cost_credits")
            seg = data.get("segments")
            msg_id = data.get("message_id")
        except Exception:
            pass
        suffix = ""
        if isinstance(cost, int):
            suffix = f" ({cost} credits"
            if isinstance(seg, int) and seg > 1:
                suffix += f", {seg} parts"
            suffix += ")"
        return SmsSendOutcome(
            True,
            f"SMS sent to {phone}{suffix}.",
            message_id=msg_id,
            cost_credits=cost,
            segments=seg,
            status_code=200,
        )
    if sc == 401:
        return SmsSendOutcome(
            False, "MrCall sign-in expired — sign in again to send SMS.", status_code=401
        )
    if sc == 402:
        topup = ""
        try:
            topup = resp.json().get("topup_url", "") or ""
        except Exception:
            pass
        msg = "Out of MrCall credits — top up to send SMS" + (f": {topup}" if topup else ".")
        return SmsSendOutcome(False, msg, status_code=402)
    if sc == 409:
        # sms_sender_not_configured — the business has no SMS_FROM set. Surface
        # the server's guidance verbatim (no "(409)" noise).
        detail = ""
        try:
            detail = resp.json().get("detail") or ""
        except Exception:
            pass
        return SmsSendOutcome(
            False,
            detail
            or "Your SMS sender isn't set up yet — configure your SMS sender "
            "(SMS_FROM) before sending SMS.",
            status_code=409,
        )
    if sc == 429:
        return SmsSendOutcome(
            False, "Too many SMS requests — wait a moment and retry.", status_code=429
        )
    if sc == 500:
        return SmsSendOutcome(
            False, "SMS isn't configured on the MrCall server yet.", status_code=500
        )
    if sc in (404, 502, 503):
        detail = ""
        try:
            body = resp.json()
            detail = body.get("detail") or body.get("error") or ""
        except Exception:
            detail = ""
        return SmsSendOutcome(
            False,
            "SMS service isn't available right now" + (f" ({detail})." if detail else "."),
            status_code=sc,
        )
    detail = ""
    try:
        body = resp.json()
        detail = body.get("detail") or body.get("error") or ""
    except Exception:
        detail = (resp.text or "")[:200]
    logger.warning(f"[send_sms] proxy {sc}: {detail}")
    return SmsSendOutcome(
        False, f"SMS not sent ({sc})" + (f": {detail}." if detail else "."), status_code=sc
    )


__all__ = ["send_sms_via_proxy", "SmsSendOutcome"]
