"""GPT-6 Responses wire, real agent/tools and durable accounting; no paid calls."""

import httpx
import pytest

from tests.voice.m2_fixture import FOLLOWUP
from zylch.llm.budget import budget_snapshot
from zylch.llm.client import LLMClient
from zylch.llm.openai_voice import (
    MODEL,
    OpenAIVoiceClient,
    decode_response,
    request_bound,
    usage_cost,
)
from zylch.llm.budget_pricing import BudgetError


def reply(*, tool=False):
    return {
        "model": MODEL,
        "status": "completed",
        "service_tier": "default",
        "output": (
            [
                {
                    "type": "function_call",
                    "status": "completed",
                    "name": "caller_memory",
                    "call_id": "call_fixture",
                    "arguments": '{"query":"delivery"}',
                }
            ]
            if tool
            else [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": FOLLOWUP}],
                }
            ]
        ),
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "input_tokens_details": {"cached_tokens": 10, "cache_write_tokens": 20},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def client_with(handler):
    client = LLMClient("openai_voice", api_key="test-key", openai_project="proj_test")
    client._client = OpenAIVoiceClient(
        "test-key", "proj_test", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    return client


@pytest.mark.parametrize(
    "change",
    [
        {"model": "gpt-4.1"},
        {"status": "incomplete"},
        {"usage": None},
        {"service_tier": "fast"},
        {"output": []},
        {"output": [{"type": "reasoning", "encrypted_content": "opaque"}]},
    ],
)
def test_unknown_incomplete_usage_retains_hold(fixture_db, monkeypatch, change):
    monkeypatch.delenv("ZYLCH_PROFILE_DIR")
    data = reply() | change
    client = client_with(lambda r: httpx.Response(200, json=data))
    with pytest.raises(BudgetError):
        client.create_message_sync(messages=[{"role": "user", "content": "synthetic"}])
    state = budget_snapshot("fixture-owner")
    assert state["reserved_usd"] > 0 and state["spent_usd"] == 0


@pytest.mark.parametrize("status,retained", [(400, False), (401, False), (429, False), (500, True)])
def test_http_no_retry_and_no_secret_body(fixture_db, monkeypatch, status, retained):
    monkeypatch.delenv("ZYLCH_PROFILE_DIR")
    calls = []

    def wire(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "secret echo test-key"})

    with pytest.raises(BudgetError) as error:
        client_with(wire).create_message_sync(messages=[{"role": "user", "content": "synthetic"}])
    assert "test-key" not in str(error.value) and len(calls) == 1
    assert (budget_snapshot("fixture-owner")["reserved_usd"] > 0) is retained


def test_usage_rates_cache_and_provider_window():
    usage = decode_response(reply()).usage
    assert usage_cost(MODEL, usage)[0] == 392
    usage["input_tokens"] = 272001
    assert usage_cost(MODEL, usage)[0] == 1088408
    # No obsolete 200K context or local output ceiling inherited from Anthropic.
    assert (
        request_bound(
            dict(
                model=MODEL, messages=[{"role": "user", "content": "x" * 500000}], max_tokens=128000
            )
        )
        > 4000000
    )
    data = reply()
    data["usage"]["input_tokens_details"]["cached_tokens"] = 101
    with pytest.raises(BudgetError):
        decode_response(data)
    data = reply(tool=True)
    data["output"][0]["name"] = "send_email"
    with pytest.raises(BudgetError):
        decode_response(data)


@pytest.mark.parametrize(
    "details",
    [
        None,
        {},
        {"cached_tokens": 0},
        {"cache_write_tokens": 0},
        {"cached_tokens": 0, "cache_write_tokens": -1},
    ],
)
def test_incomplete_cache_breakdown_retains_hold(fixture_db, monkeypatch, details):
    monkeypatch.delenv("ZYLCH_PROFILE_DIR")
    data = reply()
    data["usage"]["input_tokens_details"] = details
    with pytest.raises(BudgetError):
        client_with(lambda r: httpx.Response(200, json=data)).create_message_sync(
            messages=[{"role": "user", "content": "synthetic"}]
        )
    state = budget_snapshot("fixture-owner")
    assert state["reserved_usd"] > 0 and state["spent_usd"] == 0
