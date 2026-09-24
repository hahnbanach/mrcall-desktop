"""GPT-6 Responses wire, real agent/tools and durable accounting; no paid calls."""

import asyncio
import json
from unittest.mock import Mock

import httpx
import pytest

from tests.voice.m2_fixture import FOLLOWUP, INTERNAL, KNOWN, NUMBER, OTHER_FACT, PUBLIC
from tests.voice.test_agent_config import save
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
from zylch.services.voice import preparation
from zylch.services.voice.agent_config import snapshot_for_call
from zylch.services.voice.caller_memory import CallerMemory
from zylch.services.voice.conversation import Conversation


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


def test_responses_tool_roundtrip_with_real_memory_and_ledger(fixture_db, monkeypatch, caplog):
    monkeypatch.delenv("ZYLCH_PROFILE_DIR")
    save()
    snap = snapshot_for_call(NUMBER)
    bodies = []

    def wire(request):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["OpenAI-Project"] == "proj_test"
        body = json.loads(request.content)
        bodies.append(body)
        assert body["model"] == MODEL and body["reasoning"] == {"effort": "none"}
        assert body["store"] is False and body["service_tier"] == "default"
        assert body["tools"][0]["name"] == "caller_memory"
        assert "temperature" not in body and "previous_response_id" not in body
        assert (
            INTERNAL not in str(body)
            and OTHER_FACT not in str(body)
            and fixture_db not in str(body)
        )
        return httpx.Response(200, json=reply(tool=len(bodies) == 1))

    client = client_with(wire)
    conv = Conversation(snap, CallerMemory(snap, KNOWN), client, None, {"results_sent": 0})
    answer = asyncio.run(conv.agent.process_message("Look up the stored delivery agreement."))
    assert FOLLOWUP in answer and len(bodies) == 2
    result = next(i for i in bodies[1]["input"] if i.get("type") == "function_call_output")
    assert result["call_id"] == "call_fixture" and "Thursday" in result["output"]
    assert budget_snapshot("fixture-owner")["reserved_usd"] == 0
    assert budget_snapshot("fixture-owner")["spent_usd"] == pytest.approx(0.000784)
    assert "test-key" not in caplog.text and PUBLIC not in caplog.text


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


def isolated_settings(path, *, valid=True):
    uid = path.name
    (path / ".env").write_text(
        f"OWNER_ID={uid}\nVOICE_SMOKE_TEST_PROFILE={uid}\n"
        f"VOICE_ENGINE_ISOLATED_PROFILE={uid if valid else 'wrong'}\n"
        "VOICE_ENGINE_PROVIDER=openai\nVOICE_ENGINE_UNLIMITED=1\n"
        "OPENAI_API_KEY=test-key\nOPENAI_PROJECT_ID=proj_test\nLLM_PROVIDER=mrcall\n"
    )


@pytest.mark.parametrize("mode", ["saved", "wrong", "ambient", "unavailable"])
def test_preparation_is_explicit_no_firebase_or_credit_fallback(
    fixture_db, tmp_path, monkeypatch, mode
):
    save()
    snap = snapshot_for_call(NUMBER)
    isolated_settings(tmp_path, valid=mode != "wrong")
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    if mode == "ambient":
        (tmp_path / ".env").write_text("LLM_PROVIDER=mrcall\n")
        monkeypatch.setenv("VOICE_ENGINE_PROVIDER", "openai")
    refresh = Mock(return_value=False)
    monkeypatch.setattr(preparation, "ensure_fresh_session", refresh)
    factory = Mock(side_effect=AssertionError("fallback"))
    monkeypatch.setattr(preparation, "make_llm_client", factory)
    ready = Mock(side_effect=BudgetError("unavailable") if mode == "unavailable" else None)
    monkeypatch.setattr(OpenAIVoiceClient, "ready", ready)
    if mode == "saved":
        client = asyncio.run(preparation.prepare_client(snap))
        assert client.model == MODEL and client.transport == "openai_voice"
        ready.assert_called_once()
    else:
        with pytest.raises(ValueError):
            asyncio.run(preparation.prepare_client(snap))
    if mode != "ambient":
        refresh.assert_not_called()
    factory.assert_not_called()


def test_unlimited_voice_passes_more_than_ten_tools_and_large_context(
    fixture_db, tmp_path, monkeypatch
):
    save()
    snap = snapshot_for_call(NUMBER)
    isolated_settings(tmp_path)
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    calls = []

    def wire(request):
        calls.append(json.loads(request.content))
        data = reply(tool=len(calls) <= 11)
        if len(calls) <= 11:
            data["output"][0]["call_id"] = f"call_{len(calls)}"
        return httpx.Response(200, json=data)

    conv = Conversation(
        snap, CallerMemory(snap, KNOWN), client_with(wire), None, {}, unlimited=True
    )
    assert conv.agent.unlimited_voice
    answer = asyncio.run(conv.agent.process_message("synthetic context " * 30000))
    assert FOLLOWUP in answer and len(calls) == 12
    assert calls[0]["max_output_tokens"] == 128000


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
