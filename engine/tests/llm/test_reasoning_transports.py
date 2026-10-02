"""Reasoning blocks through parse, admission and replay on the three transports (brief D3, AC 2).

Each test drives a two-request tool loop through the real
``LLMClient.create_message_sync`` and a real ledger, with the provider
scripted: the first answer leads its tool call with reasoning blocks, the
caller appends ``assistant_content`` and the tool result, and the second
request must carry those blocks unchanged, pass admission and reach the
provider in the one shape. The metadata comes through the shape's seam.
"""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from zylch.llm import request_shape
from zylch.llm.bounded_proxy import PROTOCOL, BoundedProxyClient, digest
from zylch.llm.budget import budget_snapshot
from zylch.llm.budget_pricing import BudgetError
from zylch.llm.client import LLMClient
from zylch.llm.openrouter_client import OpenRouterClient
from zylch.storage import database
from zylch.storage.models import LlmBillingAuthorization, LlmReservation, LlmUsage

# Publishes `minimal` beside `low` (as Qwen 3.8 Max does): `low` is sent (IR1 B1).
MANDATORY = {
    "reasoning": {
        "mandatory": True,
        "efforts": ["max", "xhigh", "high", "medium", "low", "minimal"],
        "default_enabled": True,
    },
    "parameters": ["reasoning", "tools", "tool_choice"],
    "forced_tool": False,
    "structured_outputs": False,
    "context_length": 1_000_000,
    "expiration_date": None,
}
TOOL = {"name": "lookup", "description": "Look up.", "input_schema": {"type": "object"}}
THINKING = {"type": "thinking", "thinking": "Look order 7 up first.", "signature": "sig-1"}
REDACTED = {"type": "redacted_thinking", "data": "opaque-bytes"}
CALL = {"type": "tool_use", "id": "call-1", "name": "lookup", "input": {"q": "order 7"}}
FIRST = [THINKING, REDACTED, {"type": "text", "text": "Searching."}, CALL]
FINAL = [{"type": "thinking", "thinking": "Done.", "signature": "sig-2"}]
FINAL += [{"type": "text", "text": "Order 7 shipped."}]
RESULT = {"type": "tool_result", "tool_use_id": "call-1", "content": "shipped"}


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.setenv("OWNER_ID", "account")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    monkeypatch.setattr(request_shape, "_metadata", lambda model: MANDATORY)
    database.dispose_engine()
    database.Base.metadata.create_all(
        database.get_engine(),
        tables=[LlmReservation.__table__, LlmUsage.__table__, LlmBillingAuthorization.__table__],
    )
    yield
    database.dispose_engine()


def loop(client):
    """Two requests of one tool loop; returns the first response and the final one."""
    messages = [{"role": "user", "content": "Where is order 7?"}]
    first = client.create_message_sync(messages=list(messages), tools=[TOOL], max_tokens=400)
    assert first.stop_reason == "tool_use"
    assert [block.type for block in first.content] == ["text", "tool_use"]
    assert first.assistant_content == FIRST
    messages += [
        {"role": "assistant", "content": first.assistant_content},
        {"role": "user", "content": [RESULT]},
    ]
    final = client.create_message_sync(messages=messages, tools=[TOOL], max_tokens=400)
    assert final.assistant_content == FINAL and final.content[0].text == "Order 7 shipped."
    return first, final


def assert_shaped(sent):
    """The second request: the one shape, the replayed turn unchanged."""
    assert not {"temperature", "top_p", "top_k"} & set(sent)
    assert sent["output_config"] == {"effort": "low"}
    assert sent["max_tokens"] == 400 + request_shape.REASONING_HEADROOM
    assert sent["messages"][1] == {"role": "assistant", "content": FIRST}
    assert sent["messages"][2]["content"][0]["tool_use_id"] == "call-1"


def test_direct_replays_reasoning_with_the_drop_block_binding(ledger):
    from anthropic.types import Message

    calls, answers = [], [(FIRST, "tool_use"), (FINAL, "end_turn")]

    def create(**kwargs):
        calls.append(copy.deepcopy(kwargs))
        content, stop = answers.pop(0)
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

    client = LLMClient("direct", api_key="synthetic", model="claude-sonnet-5-5")
    client._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    loop(client)
    sent = calls[1]
    assert_shaped(sent)
    assert sent["thinking"] == {
        "type": "adaptive",
        "block_binding": {"prefix_mismatch_behavior": "drop_block"},
    }
    assert sent["extra_headers"] == {"anthropic-beta": "thinking-binding-controls-2026-08-01"}
    assert budget_snapshot("account")["reserved_usd"] == 0


def test_openrouter_replays_reasoning_and_adds_no_thinking_of_its_own(ledger):
    bodies, answers = [], [(FIRST, "tool_use"), (FINAL, "end_turn")]

    def upstream(request):
        bodies.append(json.loads(request.content))
        content, stop = answers.pop(0)
        return httpx.Response(
            200,
            json={
                "id": "gen",
                "model": "qwen/qwen3.8-max-0902",
                "content": content,
                "stop_reason": stop,
                "usage": {"input_tokens": 100, "output_tokens": 20, "cost": "0.0001"},
            },
        )

    client = LLMClient("openrouter", api_key="synthetic", model="qwen/qwen3.8-max-0902")
    client._client = OpenRouterClient(
        "synthetic", http_client=httpx.Client(transport=httpx.MockTransport(upstream))
    )
    loop(client)
    assert_shaped(bodies[1])
    assert bodies[1]["thinking"] == {"type": "adaptive"}
    assert bodies[1]["provider"]["require_parameters"] is True
    assert budget_snapshot("account")["spent_usd"] == 0.0002


def test_openrouter_still_refuses_an_unknown_block(ledger):
    def upstream(request):
        return httpx.Response(
            200,
            json={
                "model": "qwen/qwen3.8-max-0902",
                "content": [{"type": "image", "source": {}}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1, "cost": "0.00001"},
            },
        )

    client = LLMClient("openrouter", api_key="synthetic", model="qwen/qwen3.8-max-0902")
    client._client = OpenRouterClient(
        "synthetic", http_client=httpx.Client(transport=httpx.MockTransport(upstream))
    )
    with pytest.raises(BudgetError, match="unsupported content"):
        client.create_message_sync(messages=[{"role": "user", "content": "x"}])


def test_credits_quote_execute_and_replay_carry_reasoning(ledger):
    quoted, answers = [], [(FIRST, "tool_use"), (FINAL, "end_turn")]

    def handler(http_request):
        body = json.loads(http_request.content)
        if http_request.url.path.endswith("/quote"):
            quoted.append(body["request"])
            quote = dict(
                protocol=PROTOCOL,
                currency="USD",
                account_id="account",
                business_id="business",
                payload_hash=digest(body["request"]),
                tariff_version="test-tariff",
                model=body["request"]["model"],
                credit_value_micro_usd=11000,
                markup_factor="1.5",
                max_credits=2,
                max_debit_micro_usd=22000,
            )
            quote["quote_hash"] = digest(quote)
            return httpx.Response(200, json=quote)
        receipt = {
            **body["quote"],
            "request_id": body["request_id"],
            "authorized_max_debit_micro_usd": body["max_debit_micro_usd"],
            "credits": 1,
            "debit_micro_usd": 11000,
        }
        content, stop = answers.pop(0)
        message = {
            "model": body["request"]["model"],
            "content": content,
            "stop_reason": stop,
            "usage": {"input_tokens": 10, "output_tokens": 1},
        }
        return httpx.Response(
            200, json={"state": "settled", "receipt": receipt, "message": message}
        )

    session = SimpleNamespace(id_token="synthetic")
    client = LLMClient("proxy", firebase_session=session, model="claude-sonnet-5-5")
    client._client = BoundedProxyClient(
        "https://synthetic.test",
        session,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    loop(client)
    assert_shaped(quoted[1])
    assert quoted[1]["thinking"] == {"type": "adaptive"}
    assert budget_snapshot("account")["spent_usd"] == 0.022
