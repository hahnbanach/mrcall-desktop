"""A prompt already known to exceed the budget is never dispatched.

Per-result bounds do not bound a turn: each tool-loop step appends its
results to the conversation, so several steps of legitimate results can
still assemble a prompt over the window. The old loop found that out from
the upstream 400. Now the assembled prompt — system, tool schemas,
messages — is estimated before every call, and an estimate over budget
raises `LLMPromptTooLargeError` with the numbers instead of sending.

The estimator is calibrated on the incident, not on prose: 1,368,597
characters of JSON tool results were counted upstream at 485,835 tokens.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from zylch.assistant import budget, core
from zylch.llm.exceptions import LLMPromptTooLargeError


class _Client:
    transport = "test"

    def __init__(self):
        self.calls = []

    async def create_message(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="ok")],
            usage={"input_tokens": 1, "output_tokens": 1},
        )


def _agent(monkeypatch, history):
    monkeypatch.setattr(core, "get_personal_data_section", lambda owner_id=None: "")
    monkeypatch.setattr(core, "get_channel_status_block", lambda: "")
    agent = core.ZylchAIAgent.__new__(core.ZylchAIAgent)
    agent.client = _Client()
    agent.tools = []
    agent.tool_map = {}
    agent.model_selector = SimpleNamespace(select_model=lambda *a, **k: "test-model")
    agent.max_tokens = 4096
    agent.triggered_instructions = []
    agent.conversation_history = list(history)
    agent.message_count = 0
    agent.last_usage = {}
    agent.last_truncations = []
    return agent


def test_estimator_is_calibrated_on_the_incident():
    # 2026-09-07 16:30 UTC, turn 2d27ab60: 1,368,597 chars → 485,835 tokens.
    estimate = budget.estimate_tokens("x" * 1_368_597)
    assert estimate >= 400_000, "the estimate must not undercount dense JSON"


def test_over_budget_prompt_is_refused_before_any_call(monkeypatch):
    over = budget.PROMPT_TOKEN_BUDGET * budget.CHARS_PER_TOKEN + 10
    agent = _agent(monkeypatch, [{"role": "user", "content": "y" * over}])

    with pytest.raises(LLMPromptTooLargeError) as raised:
        asyncio.run(agent.process_message("what do we know?", context={"user_id": "o"}))

    assert agent.client.calls == []
    assert raised.value.estimated_tokens > budget.PROMPT_TOKEN_BUDGET
    assert raised.value.budget_tokens == budget.PROMPT_TOKEN_BUDGET
    assert f"{raised.value.estimated_tokens:,}" in str(raised.value)


def test_a_prompt_within_budget_is_sent_once(monkeypatch):
    agent = _agent(monkeypatch, [])

    answer = asyncio.run(agent.process_message("hello", context={"user_id": "o"}))

    assert answer == "ok"
    assert len(agent.client.calls) == 1
