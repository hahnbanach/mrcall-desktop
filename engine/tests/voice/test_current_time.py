"""Direct read-only clock route and capability enforcement for Live delegations."""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from tests.voice.helpers import delegation
from tests.voice.m2_fixture import KNOWN, NUMBER, configuration
from tests.voice.test_agent_config import save
from tests.voice.test_conversation import until
from zylch.services.voice import current_time
from zylch.services.voice.agent_config import VoiceError, snapshot_for_call
from zylch.services.voice.caller_memory import CallerMemory
from zylch.services.voice.conversation import Conversation, request_text, wants_clock, clock_zone
from zylch.services.voice.current_time import CurrentTime


@pytest.mark.parametrize("month,offset", [(1, 3600), (7, 7200)])
def test_timezone_offset_and_dst(monkeypatch, month, offset):
    instant = datetime(2026, month, 15, 12, 0, tzinfo=timezone.utc)
    clock = Mock()
    clock.now.return_value = instant
    monkeypatch.setattr(current_time, "datetime", clock)
    trace = Mock()
    result = asyncio.run(CurrentTime(trace=trace).execute(timezone="Europe/Rome"))
    assert not result.error
    assert datetime.fromisoformat(result.data["datetime"]) == instant
    assert result.data["utc_offset_seconds"] == offset
    assert trace.record.call_args.kwargs["result"] == result.data


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"timezone": None},
        {"timezone": "/etc/passwd"},
        {"timezone": "../UTC"},
        {"timezone": "Fake/Zone"},
        {"timezone": "UTC", "command": "date"},
        {"timezone": "x" * 129},
    ],
)
def test_invalid_clock_arguments_do_not_echo_input(args):
    result = asyncio.run(CurrentTime().execute(**args))
    assert result.error == "A valid IANA timezone is required" and result.data is None


def make(snapshot):
    sent = []

    async def send(raw):
        sent.append(json.loads(raw))

    return Conversation(snapshot, CallerMemory(snapshot, KNOWN), send, {}), sent


@pytest.mark.parametrize(
    "phrase",
    [
        "Che ore sono a Roma?",
        "No, mi correggo. Voglio sapere l’ora di Roma.",
        "Lascia perdere il tracking. Dimmi la data di oggi a Roma.",
    ],
)
def test_observed_correction_phrases_route_to_rome_clock(phrase):
    question = request_text([{"role": "caller", "text": phrase}])
    assert wants_clock(question)
    assert clock_zone(question) == "Europe/Rome"


def test_capability_snapshot_and_direct_roundtrip(fixture_db, monkeypatch):
    save()
    before = snapshot_for_call(NUMBER)
    save(configuration() | {"tools": ["caller_memory", "get_current_time"]})
    after = snapshot_for_call(NUMBER)
    assert "get_current_time" not in before.config.tools
    assert "get_current_time" in after.config.tools
    for tools in (["get_current_time", "get_current_time"], ["shell"]):
        with pytest.raises(VoiceError):
            save(configuration() | {"tools": tools})

    async def scenario():
        disabled, sent_disabled = make(before)
        disabled.start()
        await disabled.lookup
        disabled.event({"type": "session.input_transcript.delta", "delta": "Che ore sono a Roma?"})
        disabled.event(delegation("no-clock"))
        await until(lambda: disabled.evidence["results_sent"] == 1)
        assert "unavailable" in sent_disabled[-1]["content"]
        await disabled.close()

        enabled, sent = make(after)
        enabled.start()
        await enabled.lookup
        enabled.event({"type": "session.input_transcript.delta", "delta": "Che ore sono a Roma?"})
        enabled.event(delegation("clock"))
        await until(lambda: enabled.evidence["results_sent"] == 1)
        assert sent[-1]["delegation_id"] == "clock"
        assert (
            "Europe/Rome" in sent[-1]["content"] and "Current system-clock" in sent[-1]["content"]
        )
        enabled.event({"type": "session.output_transcript.delta", "delta": "Sono le..."})
        enabled.event({"type": "session.input_transcript.delta", "delta": "E a New York?"})
        enabled.event(delegation("followup"))
        await until(lambda: enabled.evidence["results_sent"] == 2)
        assert "America/New_York" in sent[-1]["content"]
        await enabled.close()

    asyncio.run(scenario())


def test_configured_default_zone_for_fresh_clock(fixture_db):
    save(
        configuration()
        | {
            "tools": ["caller_memory", "get_current_time"],
            "instructions": "Per richieste di ora, fuso predefinito Europe/Rome.",
        }
    )
    conv, sent = make(snapshot_for_call(NUMBER))

    async def scenario():
        conv.start()
        await conv.lookup
        conv.event({"type": "session.input_transcript.delta", "delta": "Che ore sono?"})
        conv.event(delegation("default-zone"))
        await until(lambda: conv.evidence["results_sent"] == 1)
        assert "Europe/Rome" in sent[-1]["content"]
        await conv.close()

    asyncio.run(scenario())
