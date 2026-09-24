"""Clock capability, strict permissions and the paid adapter's actual tool loop."""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import httpx
import pytest

from tests.voice.m2_fixture import KNOWN, NUMBER, configuration
from tests.voice.test_agent_config import save
from tests.voice.test_openai_voice import client_with, reply
from zylch.llm.budget import budget_snapshot
from zylch.services.voice import current_time
from zylch.services.voice.agent_config import VoiceError, snapshot_for_call
from zylch.services.voice.caller_memory import CallerMemory
from zylch.services.voice.conversation import Conversation
from zylch.services.voice.current_time import CurrentTime


@pytest.mark.parametrize("month,offset", [(1, 3600), (7, 7200)])
def test_timezone_offset_and_dst(monkeypatch, month, offset):
    instant = datetime(2026, month, 15, 12, 0, tzinfo=timezone.utc)
    clock = Mock()
    clock.now.return_value = instant
    monkeypatch.setattr(current_time, "datetime", clock)
    trace = Mock()
    result = asyncio.run(CurrentTime(trace=trace).execute(timezone="Europe/Rome"))
    data = result.data
    assert not result.error
    assert datetime.fromisoformat(data["datetime"]) == instant
    assert data["utc_offset_seconds"] == offset
    assert data["timezone"] == "Europe/Rome" and data["source"] == "system_clock"
    assert trace.record.call_args.kwargs["result"] == data


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


def test_clock_capability_snapshot_and_disabled_tool(fixture_db, monkeypatch):
    monkeypatch.delenv("ZYLCH_PROFILE_DIR")
    save()
    before = snapshot_for_call(NUMBER)
    save(configuration() | {"tools": ["caller_memory", "get_current_time"]})
    after = snapshot_for_call(NUMBER)
    assert "get_current_time" not in before.config.tools
    assert "get_current_time" in after.config.tools
    for tools in (["get_current_time", "get_current_time"], ["shell"]):
        with pytest.raises(VoiceError):
            save(configuration() | {"tools": tools})
    client = client_with(lambda _: httpx.Response(200, json=reply()))
    conv = Conversation(before, CallerMemory(before, KNOWN), client, None, {})
    result = asyncio.run(conv.agent._call_tool("get_current_time", {"timezone": "UTC"}))
    assert result.error == "Unknown tool: get_current_time"


def test_responses_clock_roundtrip_settles_and_records_data(fixture_db, monkeypatch):
    monkeypatch.delenv("ZYLCH_PROFILE_DIR")
    save(configuration() | {"tools": ["caller_memory", "get_current_time"]})
    snap = snapshot_for_call(NUMBER)
    bodies = []

    def wire(request):
        body = json.loads(request.content)
        bodies.append(body)
        assert {t["name"] for t in body["tools"]} == {"caller_memory", "get_current_time"}
        if len(bodies) == 1:
            data = reply(tool=True)
            data["output"][0].update(name="get_current_time", arguments='{"timezone":"UTC"}')
            return httpx.Response(200, json=data)
        return httpx.Response(200, json=reply())

    trace = Mock()
    conv = Conversation(snap, CallerMemory(snap, KNOWN), client_with(wire), None, {}, trace=trace)
    before = datetime.now(timezone.utc)
    asyncio.run(conv.agent.process_message("Current UTC time?"))
    after = datetime.now(timezone.utc)
    assert len(bodies) == 2
    output = next(i for i in bodies[1]["input"] if i.get("type") == "function_call_output")
    assert "system_clock" in output["output"] and '"timezone": "UTC"' in output["output"]
    recorded = next(
        c.kwargs["result"] for c in trace.record.call_args_list if c.args == ("clock_result",)
    )
    instant = datetime.fromisoformat(recorded["datetime"])
    assert before.replace(microsecond=0) <= instant <= after
    assert budget_snapshot("fixture-owner")["reserved_usd"] == 0
    assert budget_snapshot("fixture-owner")["spent_usd"] > 0
