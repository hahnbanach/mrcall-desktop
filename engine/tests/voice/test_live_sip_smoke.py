"""Offline checks for the deliberately bounded M1 GPT-Live SIP smoke path."""

from __future__ import annotations

import asyncio
import json

import httpx

from zylch.services.voice.live_sip_smoke import LiveSipSmoke, LiveSipSmokeConfig


def _event(event_id: str = "evt-1", session_id: str = "sess-1") -> dict:
    return {
        "id": event_id,
        "type": "live.transport.incoming",
        "data": {"type": "sip", "session_id": session_id},
    }


def _smoke(requests: list[httpx.Request], config: LiveSipSmokeConfig | None = None) -> LiveSipSmoke:
    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LiveSipSmoke(
        config or LiveSipSmokeConfig(api_key="test-key", webhook_secret="test-secret"),
        http_client=client,
        verify_event=lambda _body, _headers: _event(),
    )


def test_signed_sip_event_accepts_one_call_and_uses_live_client_delegation():
    requests: list[httpx.Request] = []
    smoke = _smoke(requests)

    async def scenario():
        blocker = asyncio.Event()

        async def hold_sideband(_session_id: str) -> None:
            await blocker.wait()

        smoke._run_sideband = hold_sideband  # type: ignore[method-assign]  # noqa: SLF001
        status = await smoke.accept_webhook(b"signed", {"webhook-signature": "valid"})
        assert smoke.active
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()
        return status

    status = asyncio.run(scenario())

    assert status == 200
    assert requests[0].url.path == "/v1/live/sessions/sess-1/accept"
    payload = json.loads(requests[0].content)
    assert payload["session"]["model"] == "gpt-live-1"
    assert payload["session"]["delegation"] == {"type": "client"}


def test_duplicate_delivery_does_not_accept_or_start_another_call():
    requests: list[httpx.Request] = []
    smoke = _smoke(requests)

    asyncio.run(smoke.accept_webhook(b"first", {}))
    asyncio.run(smoke.accept_webhook(b"duplicate", {}))

    assert len(requests) == 1


def test_failed_accept_is_not_deduplicated_so_the_same_delivery_can_retry():
    attempts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500 if attempts == 1 else 200)

    smoke = LiveSipSmoke(
        LiveSipSmokeConfig(api_key="test-key", webhook_secret="test-secret"),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        verify_event=lambda _body, _headers: _event(),
    )

    async def scenario():
        async def hold_sideband(_session_id: str) -> None:
            await asyncio.Event().wait()

        smoke._run_sideband = hold_sideband  # type: ignore[method-assign]  # noqa: SLF001
        first = await smoke.accept_webhook(b"first", {})
        second = await smoke.accept_webhook(b"retry", {})
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()
        return first, second

    assert asyncio.run(scenario()) == (502, 200)
    assert attempts == 2


def test_second_call_is_refused_while_first_is_active():
    requests: list[httpx.Request] = []
    smoke = _smoke(requests)
    events = iter([_event("evt-1", "sess-1"), _event("evt-2", "sess-2")])
    smoke._verify_event = lambda _body, _headers: next(events)  # noqa: SLF001

    async def scenario():
        blocker = asyncio.Event()

        async def hold_sideband(_session_id: str) -> None:
            await blocker.wait()

        smoke._run_sideband = hold_sideband  # type: ignore[method-assign]  # noqa: SLF001
        await smoke.accept_webhook(b"first", {})
        await smoke.accept_webhook(b"second", {})
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()

    asyncio.run(scenario())

    assert [request.url.path for request in requests] == [
        "/v1/live/sessions/sess-1/accept",
        "/v1/live/sessions/sess-2/reject",
    ]


def test_six_lifetime_admissions_are_reserved_and_the_seventh_is_refused():
    requests: list[httpx.Request] = []
    smoke = _smoke(
        requests,
        LiveSipSmokeConfig(
            api_key="test-key", webhook_secret="test-secret", per_call_reservation_usd=0.80
        ),
    )

    async def scenario():
        async def hold_sideband(_session_id: str) -> None:
            await asyncio.Event().wait()

        smoke._run_sideband = hold_sideband  # type: ignore[method-assign]  # noqa: SLF001
        for number in range(7):
            smoke._verify_event = lambda _body, _headers, n=number: _event(  # noqa: SLF001
                f"evt-{n}", f"sess-{n}"
            )
            await smoke.accept_webhook(b"signed", {})
            smoke._active_session_id = None  # noqa: SLF001
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()

    asyncio.run(scenario())
    assert requests[-1].url.path == "/v1/live/sessions/sess-6/reject"


def test_watchdog_hangs_up_and_releases_the_admission():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    smoke = LiveSipSmoke(
        LiveSipSmokeConfig(api_key="test-key", webhook_secret="test-secret", duration_seconds=0.01),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    smoke._active_session_id = "sess-watchdog"  # noqa: SLF001

    class Connection:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return False

    async def never(_ws):
        await asyncio.Event().wait()

    smoke._connect = lambda *_args, **_kwargs: Connection()  # noqa: SLF001
    smoke._consume_events = never  # type: ignore[method-assign]  # noqa: SLF001
    asyncio.run(smoke._run_sideband("sess-watchdog"))  # noqa: SLF001

    assert not smoke.active
    assert requests[-1].url.path == "/v1/live/sessions/sess-watchdog/hangup"


def test_client_delegation_receives_the_fixed_fact_without_transcript_logging():
    requests: list[httpx.Request] = []
    smoke = _smoke(requests)

    class Socket:
        def __init__(self):
            self.sent: list[dict] = []
            self._events = iter(
                [
                    json.dumps(
                        {
                            "type": "session.delegation.created",
                            "delegation": {"id": "delegation-1", "target": "client"},
                        }
                    ),
                    json.dumps({"type": "session.closed"}),
                ]
            )

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._events)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

        async def send(self, raw: str):
            self.sent.append(json.loads(raw))

    socket = Socket()
    asyncio.run(smoke._consume_events(socket))  # noqa: SLF001

    assert len(socket.sent) == 1
    assert socket.sent[0]["type"] == "session.commentary.append"
    assert socket.sent[0]["delegation_id"] == "delegation-1"
    assert socket.sent[0]["content"] == "The isolated test case is ready for the demonstration."
    assert socket.sent[0]["event_id"].startswith("voice-smoke-")
    assert smoke.event_shapes == [
        {"type": "session.delegation.created"},
        {"type": "session.closed", "final_usage_present": False},
    ]
