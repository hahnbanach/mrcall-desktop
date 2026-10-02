"""One chat turn keeps one prefix across its tool loop (brief D3, AC 2).

Anthropic binds each reasoning block to the conversation before it, and the
prompt cache reads only an unchanged prefix. So every request of one turn's
tool loop sends a byte-identical ``system``, ``tools`` and message prefix —
compared without ``cache_control`` markers, which move to the newest message
on every request and which the API ignores. Three things hold it: the turn's
clock (``RunClock``: one datetime line even when the minute rolls over
mid-loop), the volatile context stored in the user turn it was sent with, and
the assistant turn replayed with its reasoning blocks unchanged. At the next
user turn the earlier turns' reasoning goes; their tool exchange stays.

The real agent, the real ``LLMClient`` and a real ledger; the provider is
scripted.
"""

from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from zylch.assistant import core
from zylch.llm import client as client_mod
from zylch.llm import request_shape
from zylch.llm.client import LLMClient
from zylch.storage import database
from zylch.storage.models import LlmReservation, LlmUsage
from zylch.tools.base import Tool, ToolResult, ToolStatus

REASONING = {
    "reasoning": {"mandatory": True, "efforts": ["max", "high", "low"], "default_enabled": None},
    "parameters": ["reasoning", "tools", "tool_choice"],
    "forced_tool": False,
    "structured_outputs": False,
    "context_length": 1_000_000,
    "expiration_date": None,
}
THINKING = {"type": "thinking", "thinking": "Look order 7 up first.", "signature": "sig-1"}
CALL = {"type": "tool_use", "id": "tu-1", "name": "lookup_order", "input": {"order": 7}}
LOOKING = {"type": "text", "text": "Looking."}


class _Lookup(Tool):
    def __init__(self):
        super().__init__(name="lookup_order", description="Look an order up.")

    async def execute(self, **_kwargs) -> ToolResult:
        return ToolResult(status=ToolStatus.SUCCESS, data={"order": 7, "state": "shipped"})

    def get_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {"type": "object"},
        }


def _message(content, stop):
    from anthropic.types import Message

    return Message.model_validate(
        {
            "id": "msg",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "content": content,
            "stop_reason": stop,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        }
    )


@pytest.fixture
def chat(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.setenv("OWNER_ID", "account")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    database.dispose_engine()
    database.Base.metadata.create_all(
        database.get_engine(), tables=[LlmReservation.__table__, LlmUsage.__table__]
    )
    # Every read of the clock is a new minute: only a run clock keeps one line.
    minutes = iter(range(60))
    monkeypatch.setattr(
        client_mod,
        "current_datetime_line",
        lambda: f"Datetime=2026-10-02T12:{next(minutes):02d}+00:00 (Friday)",
    )
    monkeypatch.setattr(request_shape, "_metadata", lambda model: REASONING)
    monkeypatch.setattr(core, "get_personal_data_section", lambda owner_id=None: "")
    monkeypatch.setattr(core, "get_channel_status_block", lambda: "CHANNELS: email ok")
    sent, answers = [], []

    def create(**kwargs):
        sent.append(copy.deepcopy(kwargs))
        content, stop = answers.pop(0)
        return _message(content, stop)

    llm = LLMClient("direct", api_key="synthetic", model="claude-sonnet-5-5")
    llm._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    agent = core.ZylchAIAgent(tools=[_Lookup()], client=llm)
    yield agent, sent, answers
    database.dispose_engine()


def without_markers(value):
    if isinstance(value, dict):
        return {k: without_markers(v) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list):
        return [without_markers(v) for v in value]
    return value


def wire(value) -> str:
    return json.dumps(without_markers(value), ensure_ascii=False)


def turn(agent, text):
    return asyncio.run(agent.process_message(text, context={"user_id": "account"}))


def test_the_requests_of_one_tool_loop_share_one_prefix(chat):
    agent, sent, answers = chat
    answers += [([THINKING, LOOKING, CALL], "tool_use"), ([LOOKING], "end_turn")]
    assert turn(agent, "Where is order 7?") == "Looking."
    first, second = sent
    assert wire(first["system"]) == wire(second["system"])
    assert "Datetime=2026-10-02T12:" in first["system"][-1]["text"]
    assert wire(first["tools"]) == wire(second["tools"])
    prefix = first["messages"]
    assert [wire(m) for m in second["messages"][: len(prefix)]] == [wire(m) for m in prefix]
    # The volatile context is part of the turn it was sent with, on both requests.
    asked = second["messages"][0]["content"]
    assert asked[0] == {"type": "text", "text": "Where is order 7?"}
    assert "CURRENT DATE/TIME" in asked[1]["text"] and "CHANNELS: email ok" in asked[1]["text"]
    # The assistant turn comes back with its reasoning, unchanged and first.
    assert second["messages"][len(prefix)] == {
        "role": "assistant",
        "content": [THINKING, LOOKING, CALL],
    }
    assert second["messages"][-1]["content"][0]["tool_use_id"] == "tu-1"


def test_a_new_turn_drops_the_earlier_turns_reasoning_and_keeps_their_tools(chat):
    agent, sent, answers = chat
    answers += [([THINKING, LOOKING, CALL], "tool_use"), ([LOOKING], "end_turn")]
    turn(agent, "Where is order 7?")
    answers += [([{"type": "text", "text": "You're welcome."}], "end_turn")]
    turn(agent, "Thanks.")
    third = sent[2]
    blocks = [b for m in third["messages"] if isinstance(m["content"], list) for b in m["content"]]
    assert not [b for b in blocks if b.get("type") in ("thinking", "redacted_thinking")]
    assert CALL in blocks and any(b.get("type") == "tool_result" for b in blocks)
    assert third["messages"][-1]["content"][0] == {"type": "text", "text": "Thanks."}
    # The history the agent keeps carries none either.
    kept = [
        b
        for m in agent.conversation_history
        if isinstance(m["content"], list)
        for b in m["content"]
    ]
    assert not [b for b in kept if b.get("type") == "thinking"]
