"""M3 signed ingress, real call lifecycle and two configuration snapshots."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests.voice.helpers import Transport, delegation, finished, incoming, config_for, Socket
from tests.voice.m2_fixture import KNOWN, NUMBER, configuration
from tests.voice.test_agent_config import save
from tests.voice.test_conversation import make_conversation, response, until
from tests.voice.test_vonage import CARRIER, signed
from zylch.services.voice import engine_runtime
from zylch.services.voice.live_sip_smoke import create_app
from zylch.storage.voice_smoke import SmokeLedger


class VoiceTransport(Transport):
    def __init__(self):
        super().__init__()
        self.instructions = []

    async def accept(self, session, instructions=None):
        self.instructions.append(instructions)
        return await super().accept(session)


def setup_runtime(tmp_path, monkeypatch, client, **config_changes):
    config = config_for(tmp_path, test_number=NUMBER, **CARRIER, **config_changes)
    ledger = SmokeLedger(
        config.profile / "voice-smoke.db",
        config.policy_id,
        config.reservation_microusd,
        config.max_calls,
    )
    transport = VoiceTransport()
    transport.ledger = ledger
    runtime = engine_runtime.EngineVoiceRuntime(config, ledger, transport)
    runtime.finalization_timeout = 0.01
    prepare = AsyncMock(return_value=client)
    monkeypatch.setattr(engine_runtime, "prepare_client", prepare)
    return config, ledger, transport, runtime, prepare


async def admit(http, config, caller=KNOWN, carrier="carrier-1", session="session-1"):
    body = json.dumps({"to": NUMBER, "from": caller, "uuid": carrier}).encode()
    result = await http.post("/vonage/answer", data=body, headers=signed(body))
    assert result.status == 200
    ncco = await result.json()
    if not ncco:
        return None
    token = ncco[0]["endpoint"][0]["headers"]["Mrcall-Smoke-Attempt"]
    event = incoming(session, to=config.sip_to_uri)
    event["data"]["sip_headers"] += [
        {"name": "X-Mrcall-Smoke-Attempt", "value": token},
        {"name": "From", "value": "sip:+393330000002@attacker.invalid"},
    ]
    result = await http.post("/openai/live", json=event)
    assert result.status == 200
    return ncco


def test_full_lifecycle_snapshot_and_followup(fixture_db, tmp_path, monkeypatch):
    _, client, _ = make_conversation(
        monkeypatch, [response("stored filters"), response("Thursday")]
    )
    config, ledger, transport, runtime, prepare = setup_runtime(tmp_path, monkeypatch, client)

    async def scenario():
        async with TestClient(
            TestServer(create_app(runtime, lambda body, _: json.loads(body)))
        ) as http:
            await admit(http, config, caller=KNOWN.removeprefix("+"))
            await transport.entered.wait()
            first = runtime.call
            assert first.conversation.memory.caller_number == KNOWN
            await first.conversation.lookup
            assert first.conversation.context["recognition"] == "matched"
            assert len(first.conversation.context["facts"]) == 2
            assert "Greet immediately" in transport.instructions[0]
            save(configuration() | {"instructions": "NEXT CALL ONLY"})
            assert "NEXT CALL ONLY" not in first.conversation.agent.customer_service_instructions
            transport.socket.events.put_nowait(
                {"type": "session.input_transcript.delta", "delta": "filters"}
            )
            transport.socket.events.put_nowait(delegation("first"))
            await until(lambda: first.evidence["results_sent"] == 1)
            transport.socket.events.put_nowait(
                {"type": "session.output_transcript.delta", "delta": "stored filters"}
            )
            transport.socket.events.put_nowait(
                {"type": "session.input_transcript.delta", "delta": "delivery?"}
            )
            transport.socket.events.put_nowait(delegation("followup"))
            await until(lambda: first.evidence["results_sent"] == 2)
            transport.socket.events.put_nowait({"type": "session.closed", "usage": {"seconds": 3}})
            await finished(runtime)
            assert ledger.rows()[0]["state"] == "closed"
            assert KNOWN not in str(ledger.rows())
            assert "filters" not in str(ledger.rows())
            transport.socket, transport.entered = Socket(), asyncio.Event()
            await admit(http, config, carrier="carrier-2", session="session-2")
            await transport.entered.wait()
            assert "NEXT CALL ONLY" in transport.instructions[1]
            assert runtime.call.conversation.agent.get_history() == []
            transport.socket.events.put_nowait({"type": "session.closed", "usage": {"seconds": 1}})
            await finished(runtime)
            assert prepare.await_count == 2
            assert await admit(http, config, carrier="carrier-3", session="session-3") is None
            assert len(ledger.rows()) == 2
            assert not await runtime.available()
        ledger.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["disabled", "credentials", "budget", "count", "unprepared"])
def test_no_paid_admission_on_failed_readiness(fixture_db, tmp_path, monkeypatch, failure):
    _, client, _ = make_conversation(monkeypatch, [response()])
    config, ledger, transport, runtime, prepare = setup_runtime(tmp_path, monkeypatch, client)
    if failure == "disabled":
        save(configuration() | {"enabled": False})
    elif failure == "credentials":
        prepare.side_effect = ValueError("secret-bearing upstream error")
    elif failure == "budget":
        save(configuration() | {"limits": {"budget_microusd": 1}})
    elif failure == "count":
        save(configuration() | {"limits": {"max_calls": 1}})
        ledger.admit("earlier", allowed=True)
        ledger.finish("earlier", "closed")

    async def scenario():
        async with TestClient(
            TestServer(create_app(runtime, lambda body, _: json.loads(body)))
        ) as http:
            if failure == "unprepared":
                event = incoming(to=config.sip_to_uri)
                result = await http.post("/openai/live", json=event)
                assert result.status == 200
                await finished(runtime)
            else:
                assert await admit(http, config) is None
            assert not transport.accept_calls
            assert client._client.messages.create.call_count == 0
        ledger.close()

    asyncio.run(scenario())


def test_watchdog_cancels_memory_and_keeps_ledger(fixture_db, tmp_path, monkeypatch):
    _, client, _ = make_conversation(monkeypatch, [response()])
    save(configuration() | {"limits": {"duration_seconds": 1}})
    config, ledger, transport, runtime, _ = setup_runtime(tmp_path, monkeypatch, client)

    async def scenario():
        async with TestClient(
            TestServer(create_app(runtime, lambda body, _: json.loads(body)))
        ) as http:
            await admit(http, config)
            await transport.entered.wait()
            call = runtime.call
            await finished(runtime)
            assert call.conversation.closed
            assert ledger.rows()[0]["state"] == "stopped"
            assert json.loads(ledger.rows()[0]["evidence"])["closure_trigger"] == "duration_limit"
        ledger.close()

    asyncio.run(scenario())
