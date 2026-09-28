"""Fake paid boundary; real runtime, SQLite and async event scheduling."""

import asyncio
import json
from contextlib import asynccontextmanager

from zylch.services.voice.smoke_config import SmokeConfig
from zylch.services.voice.smoke_runtime import SmokeRuntime
from zylch.storage.voice_smoke import SmokeLedger


def config_for(tmp_path, **changes):
    profile = tmp_path / "firebase-test-uid"
    profile.mkdir(exist_ok=True)
    return SmokeConfig(
        **{
            "profile": profile,
            "owner_uid": profile.name,
            "project_id": "proj_test",
            "test_number": "+39000000001",
            "sip_to_uri": "sip:proj_test@sip.example.test",
            "public_endpoint": "https://voice.example.test/openai/live",
            "engine_provider": "anthropic",
            "readiness_reference": "synthetic-test-only",
            "api_key": "fake-review-key",
            "webhook_secret": "whsec_c2lnbmluZy10ZXN0",
            "reservation_microusd": 800_000,
            "voice_per_minute_microusd": 50_000,
            "carrier_per_minute_microusd": 50_000,
            "carrier_setup_microusd": 0,
            **changes,
        }
    )


def incoming(session="sess_test", to="sip:proj_test@sip.example.test", event_id="event_test"):
    return {
        "id": event_id,
        "type": "live.transport.incoming",
        "object": "event",
        "created_at": 1780000000,
        "data": {
            "type": "sip",
            "session_id": session,
            "sip_headers": [{"name": "To", "value": f"<{to}>"}],
        },
    }


def delegation(identifier="delegation_test"):
    return {
        "type": "session.delegation.created",
        "delegation": {"id": identifier, "target": "client"},
    }


class Socket:
    def __init__(self):
        self.events = asyncio.Queue()
        self.sent = []
        self.result_sent = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        value = await self.events.get()
        if value is None:
            raise StopAsyncIteration
        if isinstance(value, Exception):
            raise value
        return json.dumps(value)

    async def send(self, raw):
        self.sent.append(json.loads(raw))
        self.result_sent.set()


class Transport:
    def __init__(self):
        self.socket = Socket()
        self.accept_calls = []
        self.controls = []
        self.accept_error = None
        self.accept_block = None
        self.attach_block = None
        self.entered = asyncio.Event()
        self.hangup_ok = True
        self.reject_ok = True
        self.close_on_hangup = False
        self.ledger = None

    async def accept(self, session):
        # Prove commit-before-dispatch against the actual SQLite connection.
        assert self.ledger.rows()[0]["reserved_microusd"] > 0
        self.accept_calls.append(session)
        if self.accept_block:
            await self.accept_block.wait()
        if self.accept_error:
            raise self.accept_error
        return True

    @asynccontextmanager
    async def attach(self, session):
        if self.attach_block:
            await self.attach_block.wait()
        self.entered.set()
        yield self.socket

    async def control(self, session, action, payload=None):
        self.controls.append((session, action, payload))
        if action == "hangup" and self.close_on_hangup:
            self.socket.events.put_nowait({"type": "session.closed", "usage": {"seconds": 2.0}})
        return self.hangup_ok if action == "hangup" else self.reject_ok


def setup(tmp_path, **changes):
    config = config_for(tmp_path, **changes)
    ledger = SmokeLedger(
        config.profile / "voice-smoke.db",
        config.policy_id,
        config.reservation_microusd,
        config.max_calls,
    )
    transport = Transport()
    transport.ledger = ledger
    runtime = SmokeRuntime(config, ledger, transport)
    runtime.finalization_timeout = 0.01
    return config, ledger, transport, runtime


async def finished(runtime):
    await asyncio.wait_for(asyncio.gather(*tuple(runtime.tasks)), 2)
