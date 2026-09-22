"""Dashboard-compatible outbound call submission; no retry or answer inference."""

import logging
import re
from urllib.parse import quote

logger = logging.getLogger(__name__)


def normalize_destination(phone_number: str) -> str:
    """Require an international number, retaining national leading zeros."""
    if not isinstance(phone_number, str):
        raise ValueError("Provide an international phone number with country code")
    value = phone_number.strip()
    if not re.fullmatch(r"\+?[0-9 ()-]+", value):
        raise ValueError("Provide one international phone number without extensions")
    number = re.sub(r"[ ()+-]", "", value)
    if not re.fullmatch(r"[1-9][0-9]{7,14}", number):
        raise ValueError("Include the country code, e.g. +390289040671")
    if re.match(r"39(?:199|806|807|840|841|847|848|901|902|905)", number):
        raise ValueError("This destination prefix is blocked by the MrCall dashboard")
    return number


async def submit_outbound_call(client, phone_number: str, business_id: str) -> dict:
    """Submit exactly once. HTTP acceptance proves submission, never an answer."""
    number = normalize_destination(phone_number)
    if not isinstance(business_id, str) or not business_id.strip():
        raise ValueError("Select the calling MrCall assistant first")
    business_id = business_id.strip()
    endpoint = (
        f"/mrcall/v1/{quote(client.realm, safe='')}/atom/" f"{quote(business_id, safe='')}/outbound"
    )
    logger.debug("[initiate_call] submit business_id=%s destination=%s", business_id, number)
    response = await client.client.post(endpoint, json={"toNumber": number})
    response.raise_for_status()
    if not 200 <= response.status_code < 300:
        raise ValueError("MrCall did not accept the call request")
    payload = None
    if response.content:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
    if isinstance(payload, dict) and (
        payload.get("success") is False
        or payload.get("status") in ("error", "failed", "rejected")
        or payload.get("error")
    ):
        raise ValueError("MrCall reported a failed call submission")
    logger.debug("[initiate_call] result=submitted http_status=%s", response.status_code)
    return {
        "phone_number": "+" + number,
        "business_id": business_id,
        "status": "submitted",
        "http_status": response.status_code,
        "provider_response": payload,
    }
