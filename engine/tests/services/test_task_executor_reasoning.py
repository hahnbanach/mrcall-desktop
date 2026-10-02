"""The solve loop replays reasoning within a run and drops it at the next (brief D3, AC 2).

``TaskExecutor`` sends the assistant turn back with its reasoning blocks
unchanged inside one run — the same system (one ``RunClock`` for the run),
tools and message prefix on every request — and a continued solve (the CLI's
"type to continue") starts a new turn: the earlier runs' reasoning goes,
their tool exchange stays. The real executor and the real ``LLMClient`` with
a real ledger; the provider and the tool are scripted.
"""

from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from zylch.llm import client as client_mod
from zylch.llm import request_shape
from zylch.llm.client import LLMClient
from zylch.storage import database
from zylch.storage.models import LlmReservation, LlmUsage

REASONING = {
    "reasoning": {"mandatory": True, "efforts": ["low", "high"], "default_enabled": True},
    "parameters": ["reasoning", "tools"],
    "forced_tool": False,
    "structured_outputs": False,
    "context_length": 1_000_000,
    "expiration_date": None,
}
THINKING = {"type": "thinking", "thinking": "Search the mailbox first.", "signature": "sig-1"}
CALL = {"type": "tool_use", "id": "tu-1", "name": "search_emails", "input": {"query": "order 7"}}
SAID = {"type": "text", "text": "Searching."}
DONE = [{"type": "text", "text": "Order 7 shipped."}]
TOOLS = [{"name": "search_emails", "description": "Search.", "input_schema": {"type": "object"}}]


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
def solve(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.setenv("OWNER_ID", "account")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    database.dispose_engine()
    database.Base.metadata.create_all(
        database.get_engine(), tables=[LlmReservation.__table__, LlmUsage.__table__]
    )
    minutes = iter(range(60))
    monkeypatch.setattr(
        client_mod,
        "current_datetime_line",
        lambda: f"Datetime=2026-10-02T12:{next(minutes):02d}+00:00 (Friday)",
    )
    monkeypatch.setattr(request_shape, "_metadata", lambda model: REASONING)
    monkeypatch.setattr(
        "zylch.services.solve_tools.execute_tool", lambda name, args, store, owner: "1 mail"
    )
    sent, answers = [], []

    def create(**kwargs):
        sent.append(copy.deepcopy(kwargs))
        content, stop = answers.pop(0)
        return _message(content, stop)

    llm = LLMClient("direct", api_key="synthetic", model="claude-sonnet-5-5")
    llm._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    yield llm, sent, answers
    database.dispose_engine()


def run(llm, messages):
    from zylch.services.task_executor import TaskExecutor

    executor = TaskExecutor(llm, "You solve tasks.", messages, None, "account", TOOLS)

    async def drive():
        return [event async for event in executor.run()]

    return asyncio.run(drive())


def test_one_run_replays_its_reasoning_under_one_clock(solve):
    llm, sent, answers = solve
    answers += [([THINKING, SAID, CALL], "tool_use"), (DONE, "end_turn")]
    messages = [{"role": "user", "content": "Solve: where is order 7?"}]
    events = run(llm, messages)
    assert events[-1]["type"] == "done"
    first, second = sent
    assert first["system"] == second["system"]
    assert json.dumps(first["tools"]) == json.dumps(second["tools"])
    assert second["messages"][: len(first["messages"])] == first["messages"]
    assert second["messages"][1] == {"role": "assistant", "content": [THINKING, SAID, CALL]}
    assert messages[1]["content"][0] == THINKING


def test_a_continued_solve_drops_the_earlier_runs_reasoning(solve):
    llm, sent, answers = solve
    answers += [([THINKING, SAID, CALL], "tool_use"), (DONE, "end_turn")]
    messages = [{"role": "user", "content": "Solve: where is order 7?"}]
    run(llm, messages)
    messages.append({"role": "user", "content": "Now draft the reply."})
    answers += [([{"type": "text", "text": "Drafted."}], "end_turn")]
    run(llm, messages)
    third = sent[2]
    blocks = [b for m in third["messages"] if isinstance(m["content"], list) for b in m["content"]]
    assert not [b for b in blocks if b["type"] in ("thinking", "redacted_thinking")]
    assert CALL in blocks and any(b["type"] == "tool_result" for b in blocks)
    assert not [
        b
        for m in messages
        if isinstance(m["content"], list)
        for b in m["content"]
        if b["type"] == "thinking"
    ]
