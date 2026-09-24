"""Official GPT-Live SIP wire contract; no Realtime fallback or paid retries."""

from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager

import httpx
from websockets.asyncio.client import connect

from .smoke_config import SmokeConfig
from .smoke_sip import route_uri

WIRE_LOGGER = logging.Logger("mrcall.voice.wire.disabled", level=logging.CRITICAL + 1)
WIRE_LOGGER.addHandler(logging.NullHandler())
WIRE_LOGGER.propagate = False


def incoming_session(event: dict, expected_to: str) -> tuple[str, bool] | None:
    """Signed metadata is a routing check, never caller identity authorization."""
    if event.get("type") not in {"live.transport.incoming", "live.call.incoming"}:
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        raise ValueError("invalid incoming data")
    if event["type"] == "live.transport.incoming" and data.get("type") != "sip":
        raise ValueError("not a SIP transport")
    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", session_id):
        raise ValueError("invalid session ID")
    headers = data.get("sip_headers", [])
    destinations = []
    for header in headers if isinstance(headers, list) else []:
        if isinstance(header, dict) and str(header.get("name", "")).lower() == "to":
            value = header.get("value", "")
            if isinstance(value, str):
                match = re.search(r"<([^<>]+)>", value)
                destinations.append(match.group(1) if match else value.strip())
    return session_id, len(destinations) == 1 and (
        destinations[0] == expected_to
        or (
            route_uri(expected_to) is not None
            and route_uri(destinations[0]) == route_uri(expected_to)
        )
    )


def carrier_token_hash(event: dict) -> str | None:
    """A one-use carrier correlation nonce; raw SIP headers are never retained."""
    import hashlib

    headers = event.get("data", {}).get("sip_headers", [])
    values = (
        [
            header.get("value")
            for header in headers
            if isinstance(header, dict)
            and str(header.get("name", "")).lower() == "x-mrcall-smoke-attempt"
        ]
        if isinstance(headers, list)
        else []
    )
    if len(values) != 1 or not isinstance(values[0], str):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", values[0]):
        return None
    return hashlib.sha256(values[0].encode()).hexdigest()


class LiveTransport:
    """One bounded control attempt, with opaque exceptions and silent wire logging."""

    def __init__(self, config: SmokeConfig) -> None:
        from openai import OpenAI

        self.config = config
        self.headers = {
            "Authorization": f"Bearer {config.api_key.get_secret_value()}",
            "OpenAI-Project": config.project_id,
        }
        self.http = httpx.AsyncClient(timeout=8, trust_env=False)
        self.verifier = OpenAI(
            api_key=config.api_key.get_secret_value(),
            webhook_secret=config.webhook_secret.get_secret_value(),
            max_retries=0,
        )

    def verify(self, body: bytes, headers: dict) -> dict:
        return self.verifier.webhooks.unwrap(body, headers).model_dump()

    async def control(self, session_id: str, action: str, payload: dict | None = None) -> bool:
        kwargs = {"json": payload} if payload is not None else {}
        response = await self.http.post(
            f"https://api.openai.com/v1/live/sessions/{session_id}/{action}",
            headers=self.headers,
            **kwargs,
        )
        return response.status_code == 200

    async def accept(self, session_id: str, instructions: str | None = None) -> bool:
        return await self.control(
            session_id,
            "accept",
            {
                "session": {
                    "type": "live",
                    "model": "gpt-live-1",
                    "store": False,
                    "instructions": (
                        instructions
                        if instructions is not None
                        else (
                            "This is an isolated telephone test, not a real customer-service agent. "
                            "Greet the caller. For the test fact, delegate to the client and wait "
                            "for its result. Keep listening while it works."
                        )
                    ),
                    "audio": {"output": {"voice": "marin"}},
                    "delegation": {"type": "client"},
                }
            },
        )

    @asynccontextmanager
    async def attach(self, session_id: str):
        # A private logger avoids DEBUG headers/frame dumps even when the CLI root
        # and file handlers are DEBUG. Never pass provider bodies to our logger.
        async with connect(
            f"wss://api.openai.com/v1/live/sessions/{session_id}/attach",
            additional_headers=self.headers,
            logger=WIRE_LOGGER,
            open_timeout=8,
            close_timeout=2,
            max_size=1_048_576,
        ) as ws:
            yield ws

    async def close(self) -> None:
        await self.http.aclose()
        self.verifier.close()


def command(kind: str, content: str, delegation_id: str | None = None) -> str:
    import uuid

    return json.dumps(
        {
            "type": kind,
            "event_id": f"smoke_{uuid.uuid4().hex}",
            "delegation_id": delegation_id,
            "content": content,
        }
    )
