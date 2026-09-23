"""Bounded GPT-Live SIP smoke path for an isolated test number.

Audio stays on the carrier-to-OpenAI SIP leg.  This module only verifies the
signed OpenAI webhook, accepts one Live session, observes its sideband and
returns a fixed non-customer test fact for client delegation.  It is not wired
into the regular daemon and cannot make outbound calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Callable, Mapping, Protocol

import httpx
import websockets

logger = logging.getLogger(__name__)

_API_BASE = "https://api.openai.com/v1"
_LIVE_MODEL = "gpt-live-1"
_MIN_OPENAI_VERSION = (3, 19, 0)
_MAX_CALLS = 6
_MAX_DURATION_SECONDS = 180
_MAX_TOTAL_RESERVATION_USD = 5.0
_FIXED_TEST_FACT = "The isolated test case is ready for the demonstration."


class SmokeConfigurationError(ValueError):
    """The deliberately narrow M1 environment has not been configured."""


class _Connect(Protocol):
    def __call__(self, uri: str, *, additional_headers: Mapping[str, str]): ...


def _version_tuple(raw: str) -> tuple[int, int, int]:
    """Return the numeric prefix of a package version without loose matching."""
    pieces = raw.split(".")
    try:
        return tuple(int(piece) for piece in pieces[:3])  # type: ignore[return-value]
    except ValueError as exc:
        raise SmokeConfigurationError("installed openai SDK has an invalid version") from exc


def validate_smoke_environment(profile: str, env: Mapping[str, str] | None = None) -> None:
    """Fail closed until an operator deliberately enables an isolated test."""
    env = os.environ if env is None else env
    if env.get("VOICE_SMOKE_ENABLED") != "1":
        raise SmokeConfigurationError("set VOICE_SMOKE_ENABLED=1 for an isolated test only")
    if env.get("VOICE_SMOKE_TEST_PROFILE") != profile:
        raise SmokeConfigurationError(
            "VOICE_SMOKE_TEST_PROFILE must exactly name the selected isolated profile"
        )
    missing = [name for name in ("OPENAI_API_KEY", "OPENAI_WEBHOOK_SECRET") if not env.get(name)]
    if missing:
        raise SmokeConfigurationError(f"missing required secret reference(s): {', '.join(missing)}")
    try:
        installed = _version_tuple(version("openai"))
    except PackageNotFoundError as exc:
        raise SmokeConfigurationError("openai SDK is not installed") from exc
    if installed < _MIN_OPENAI_VERSION:
        required = ".".join(str(part) for part in _MIN_OPENAI_VERSION)
        raise SmokeConfigurationError(f"openai SDK must be >= {required}")


@dataclass(frozen=True)
class LiveSipSmokeConfig:
    """Only non-secret M1 controls; all cost limits are intentionally hard."""

    api_key: str
    webhook_secret: str
    duration_seconds: int = _MAX_DURATION_SECONDS
    per_call_reservation_usd: float = _MAX_TOTAL_RESERVATION_USD / _MAX_CALLS
    fixed_result_delay_seconds: float = 1.0

    @classmethod
    def from_environment(
        cls, profile: str, env: Mapping[str, str] | None = None
    ) -> "LiveSipSmokeConfig":
        env = os.environ if env is None else env
        validate_smoke_environment(profile, env)
        duration = int(env.get("VOICE_SMOKE_DURATION_SECONDS", str(_MAX_DURATION_SECONDS)))
        if duration <= 0 or duration > _MAX_DURATION_SECONDS:
            raise SmokeConfigurationError(
                f"VOICE_SMOKE_DURATION_SECONDS must be between 1 and {_MAX_DURATION_SECONDS}"
            )
        try:
            reservation = float(env["VOICE_SMOKE_PER_CALL_RESERVATION_USD"])
        except KeyError as exc:
            raise SmokeConfigurationError(
                "VOICE_SMOKE_PER_CALL_RESERVATION_USD is required before admission"
            ) from exc
        except ValueError as exc:
            raise SmokeConfigurationError(
                "VOICE_SMOKE_PER_CALL_RESERVATION_USD must be numeric"
            ) from exc
        if reservation <= 0 or reservation > _MAX_TOTAL_RESERVATION_USD:
            raise SmokeConfigurationError(
                f"VOICE_SMOKE_PER_CALL_RESERVATION_USD must be > 0 and <= {_MAX_TOTAL_RESERVATION_USD}"
            )
        return cls(
            api_key=env["OPENAI_API_KEY"],
            webhook_secret=env["OPENAI_WEBHOOK_SECRET"],
            duration_seconds=duration,
            per_call_reservation_usd=reservation,
        )


class LiveSipSmoke:
    """One-call admission controller with a signed webhook and Live sideband."""

    def __init__(
        self,
        config: LiveSipSmokeConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
        connect: _Connect = websockets.connect,
        verify_event: Callable[[bytes, Mapping[str, str]], Mapping[str, Any]] | None = None,
    ) -> None:
        self.config = config
        self._http = http_client
        self._connect = connect
        self._verify_event = verify_event or self._verify_with_openai_sdk
        self._lock = asyncio.Lock()
        self._active_session_id: str | None = None
        self._seen_event_ids: set[str] = set()
        self._seen_delegation_ids: set[str] = set()
        self.event_shapes: list[dict[str, Any]] = []
        self._accepted_calls = 0
        self._reserved_usd = 0.0
        self._sideband_tasks: set[asyncio.Task[None]] = set()

    @property
    def active(self) -> bool:
        return self._active_session_id is not None

    def _verify_with_openai_sdk(self, body: bytes, headers: Mapping[str, str]) -> Mapping[str, Any]:
        """Use the official verifier; never parse an unauthenticated payload."""
        from openai import OpenAI

        event = OpenAI(webhook_secret=self.config.webhook_secret).webhooks.unwrap(body, headers)
        return event.model_dump()

    async def accept_webhook(self, body: bytes, headers: Mapping[str, str]) -> HTTPStatus:
        """Verify, deduplicate and admit only one signed Live SIP call."""
        try:
            event = self._verify_event(body, headers)
        except Exception as exc:
            logger.warning("[voice-smoke] rejected invalid OpenAI webhook: %s", type(exc).__name__)
            return HTTPStatus.BAD_REQUEST

        if event.get("type") != "live.transport.incoming":
            return HTTPStatus.NO_CONTENT
        data = event.get("data")
        if not isinstance(data, Mapping) or data.get("type") != "sip":
            return HTTPStatus.UNPROCESSABLE_ENTITY
        session_id = data.get("session_id")
        event_id = event.get("id")
        if (
            not isinstance(session_id, str)
            or not session_id
            or not isinstance(event_id, str)
            or not event_id
        ):
            return HTTPStatus.UNPROCESSABLE_ENTITY

        async with self._lock:
            if event_id in self._seen_event_ids:
                return HTTPStatus.OK
            would_exceed_allowance = (
                self._reserved_usd + self.config.per_call_reservation_usd
                > _MAX_TOTAL_RESERVATION_USD
            )
            if (
                self._active_session_id is not None
                or self._accepted_calls >= _MAX_CALLS
                or would_exceed_allowance
            ):
                await self._reject(session_id, 486)
                self._seen_event_ids.add(event_id)
                return HTTPStatus.OK
            accepted = await self._accept(session_id)
            if not accepted:
                return HTTPStatus.BAD_GATEWAY
            self._seen_event_ids.add(event_id)
            self._active_session_id = session_id
            self._accepted_calls += 1
            self._reserved_usd += self.config.per_call_reservation_usd
            task = asyncio.create_task(self._run_sideband(session_id))
            self._sideband_tasks.add(task)
            task.add_done_callback(self._sideband_tasks.discard)
        return HTTPStatus.OK

    async def _post(self, path: str, payload: Mapping[str, Any] | None = None) -> bool:
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        owns_client = self._http is None
        client = self._http or httpx.AsyncClient(timeout=10)
        try:
            response = await client.post(f"{_API_BASE}{path}", headers=headers, json=payload)
            if response.is_success:
                return True
            logger.warning(
                "[voice-smoke] OpenAI control request failed status=%s", response.status_code
            )
            return False
        except httpx.HTTPError as exc:
            logger.warning("[voice-smoke] OpenAI control request failed: %s", type(exc).__name__)
            return False
        finally:
            if owns_client:
                await client.aclose()

    async def _accept(self, session_id: str) -> bool:
        payload = {
            "session": {
                "type": "live",
                "model": _LIVE_MODEL,
                "instructions": "You are conducting an isolated test call. Delegate for the test fact.",
                "audio": {"output": {"voice": "marin"}},
                "delegation": {"type": "client"},
            }
        }
        return await self._post(f"/live/sessions/{session_id}/accept", payload)

    async def _reject(self, session_id: str, status_code: int) -> None:
        await self._post(f"/live/sessions/{session_id}/reject", {"status_code": status_code})

    async def _hangup(self, session_id: str) -> None:
        if not await self._post(f"/live/sessions/{session_id}/hangup"):
            logger.warning("[voice-smoke] call closure is uncertain")

    async def _run_sideband(self, session_id: str) -> None:
        uri = f"wss://api.openai.com/v1/live/sessions/{session_id}/attach"
        try:
            async with self._connect(
                uri, additional_headers={"Authorization": f"Bearer {self.config.api_key}"}
            ) as ws:
                await asyncio.wait_for(
                    self._consume_events(ws), timeout=self.config.duration_seconds
                )
        except TimeoutError:
            logger.info("[voice-smoke] duration watchdog fired")
            await self._hangup(session_id)
        except Exception as exc:
            logger.warning("[voice-smoke] sideband closed: %s", type(exc).__name__)
            await self._hangup(session_id)
        finally:
            async with self._lock:
                if self._active_session_id == session_id:
                    self._active_session_id = None

    async def _consume_events(self, ws: Any) -> None:
        async for raw in ws:
            event = json.loads(raw)
            event_type = event.get("type")
            # Event type only: transcripts, headers and identifiers are not logged.
            logger.debug("[voice-smoke] received event type=%s", event_type)
            shape = {"type": event_type}
            if event_type == "session.closed":
                shape["final_usage_present"] = isinstance(event.get("usage"), Mapping)
            self.event_shapes.append(shape)
            if event_type == "session.delegation.created":
                delegation = event.get("delegation") or {}
                delegation_id = delegation.get("id")
                if (
                    delegation.get("target") == "client"
                    and isinstance(delegation_id, str)
                    and delegation_id not in self._seen_delegation_ids
                ):
                    self._seen_delegation_ids.add(delegation_id)
                    await asyncio.sleep(self.config.fixed_result_delay_seconds)
                    await ws.send(
                        json.dumps(
                            {
                                "type": "session.commentary.append",
                                "event_id": f"voice-smoke-{uuid.uuid4()}",
                                "delegation_id": delegation_id,
                                "content": _FIXED_TEST_FACT,
                            }
                        )
                    )
            if event_type == "session.closed":
                return

    async def shutdown(self) -> None:
        """End an admitted test call before stopping its isolated smoke process."""
        async with self._lock:
            session_id = self._active_session_id
            self._active_session_id = None
            tasks = tuple(self._sideband_tasks)
        if session_id:
            await self._hangup(session_id)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def run_smoke_server(host: str, port: int, profile: str) -> None:
    """Run a local signed-webhook server for an explicitly enabled test only."""
    config = LiveSipSmokeConfig.from_environment(profile)
    smoke = LiveSipSmoke(config)
    loop = asyncio.new_event_loop()

    def _run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=_run_loop, daemon=True, name="voice-smoke-loop")
    thread.start()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/openai/live":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            future = asyncio.run_coroutine_threadsafe(
                smoke.accept_webhook(body, dict(self.headers.items())), loop
            )
            try:
                status = future.result(timeout=15)
            except Exception:
                logger.exception("[voice-smoke] webhook handler failed")
                status = HTTPStatus.INTERNAL_SERVER_ERROR
            self.send_response(status)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    logger.info("[voice-smoke] listening on %s:%s/openai/live", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        asyncio.run_coroutine_threadsafe(smoke.shutdown(), loop).result(timeout=15)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
