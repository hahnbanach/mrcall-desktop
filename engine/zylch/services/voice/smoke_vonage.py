"""M1 inbound-only Vonage NCCO: signed callbacks, fixed SIP destination, no dial API."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
import time

import jwt
from aiohttp import web

logger = logging.getLogger(__name__)


def verify_callback(body: bytes, authorization: str, config) -> dict:
    """Pin HS256, account, raw-body hash and a short freshness window."""
    if not authorization.startswith("Bearer "):
        raise ValueError("missing callback signature")
    claims = jwt.decode(
        authorization.removeprefix("Bearer "),
        config.vonage_signature_secret.get_secret_value(),
        algorithms=["HS256"],
        issuer="Vonage",
        leeway=30,
        options={"require": ["iat", "iss", "api_key", "payload_hash"]},
    )
    issued = claims["iat"]
    if type(issued) is not int or not -30 <= time.time() - issued <= 300:
        raise ValueError("stale callback")
    if claims["api_key"] != config.vonage_api_key.get_secret_value():
        raise ValueError("wrong callback account")
    if claims.get("application_id", config.vonage_application_id) != config.vonage_application_id:
        raise ValueError("wrong callback application")
    digest = claims["payload_hash"]
    if not isinstance(digest, str) or not hmac.compare_digest(
        digest, hashlib.sha256(body).hexdigest()
    ):
        raise ValueError("callback body mismatch")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("invalid callback body")
    return payload


def add_vonage_routes(app: web.Application, runtime) -> None:
    """Register only with explicit profile-file carrier credentials."""
    config = runtime.config
    if config.vonage_application_id is None:
        return

    async def callback(request: web.Request) -> web.Response:
        try:
            async with asyncio.timeout(5):
                body = await request.read()
            payload = verify_callback(body, request.headers.get("Authorization", ""), config)
        except (ValueError, jwt.PyJWTError, TypeError):
            logger.debug("[voice-smoke] Vonage signature refused")
            return web.Response(status=401)
        except TimeoutError:
            return web.Response(status=408)
        if request.path == "/vonage/event":
            # No caller data retained; this is not authoritative billing evidence.
            return web.Response(status=204)
        if payload.get("to") not in (config.test_number, config.test_number.removeprefix("+")):
            return web.Response(status=403)
        carrier_id = payload.get("uuid")
        if not isinstance(carrier_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,100}", carrier_id):
            return web.Response(status=422)
        token = secrets.token_urlsafe(32)
        try:
            available = runtime.ledger.reserve_carrier(
                carrier_id,
                hashlib.sha256(token.encode()).hexdigest(),
                allowed=not runtime.stopping and runtime.call is None,
            )
        except Exception:
            return web.Response(status=503)
        logger.debug("[voice-smoke] Vonage answer available=%s", available)
        if not available:
            return web.json_response([])
        # Never accept caller-provided destinations or forward caller metadata.
        uri = f"sip:{config.project_id}@sip.api.openai.com;transport=tls;media=srtp"
        return web.json_response(
            [
                {
                    "action": "connect",
                    "timeout": 15,
                    "limit": config.duration_seconds,
                    "endpoint": [
                        {"type": "sip", "uri": uri, "headers": {"Mrcall-Smoke-Attempt": token}}
                    ],
                }
            ]
        )

    app.router.add_post("/vonage/answer", callback)
    app.router.add_post("/vonage/event", callback)
