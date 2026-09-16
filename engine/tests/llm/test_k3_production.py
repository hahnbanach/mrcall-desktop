"""Production K3 dispatch, accounting and history; no paid calls."""

import json
from copy import deepcopy

import httpx
import pytest
from zylch.llm import k3_reasoning as k3
from zylch.llm.budget import budget_snapshot
from zylch.llm.budget_pricing import BudgetError
from zylch.llm.client import LLMClient
from zylch.llm.k3_history import translate_messages
from zylch.llm.openrouter_client import OpenRouterClient
from zylch.llm.openrouter_pricing import request_bound
from zylch.storage import database
from zylch.storage.models import LlmReservation, LlmUsage


def req(**kwargs):
    return dict(
        model=k3.MODEL,
        messages=[{"role": "user", "content": "fixture"}],
        max_tokens=8192,
        thinking={"type": "adaptive"},
        output_config={"effort": "max"},
        **kwargs,
    )


def response(**kwargs):
    return httpx.Response(
        200,
        json=dict(
            model=k3.MODEL,
            id="fixture",
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 10,
                "cost": "0.00002",
                "completion_tokens_details": {"reasoning_tokens": 5},
            },
            choices=[
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "SKIP", "reasoning": "private"},
                }
            ],
            **kwargs,
        ),
    )


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.setenv("OWNER_ID", "fixture")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    database.dispose_engine()
    database.Base.metadata.create_all(
        database.get_engine(), tables=[LlmReservation.__table__, LlmUsage.__table__]
    )
    yield
    database.dispose_engine()


def test_real_client_promotes_before_hold_and_settles(ledger):
    def http(r):
        b = json.loads(r.content)
        assert budget_snapshot("fixture")["reserved_usd"] > 0.108
        assert b["max_tokens"] == 8192 and b["reasoning"] == {"effort": "max"}
        assert b["provider"]["only"] == ["digitalocean"]
        assert b["provider"]["allow_fallbacks"] is False
        assert r.url.path == "/api/v1/chat/completions"
        return response()

    c = LLMClient("openrouter", api_key="fixture", model=k3.MODEL)
    c._client = OpenRouterClient(
        "fixture", http_client=httpx.Client(transport=httpx.MockTransport(http))
    )
    result = c.create_message_sync(
        messages=[{"role": "user", "content": "fixture"}], max_tokens=512
    )
    assert result.content[0].text == "SKIP"
    assert budget_snapshot("fixture")["spent_usd"] == 0.00002
    assert budget_snapshot("fixture")["reserved_usd"] == 0


@pytest.mark.parametrize(
    "bad",
    [
        {"temperature": 0},
        {"output_config": {"effort": "low"}},
        {"max_tokens": 8193},
        {"thinking": {"type": "enabled"}},
        {"metadata": {"foo": "bar"}},
    ],
)
def test_invalid_before_dispatch(bad):
    r = req()
    r.update(bad)
    with pytest.raises(BudgetError):
        request_bound(r)


def test_wire_byte_bound_and_system_order():
    r = req(
        system=[
            {"type": "text", "text": "one", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "two"},
        ]
    )
    b = k3.chat_request(r)
    assert b["messages"][0]["content"] == "one\n\ntwo"
    plain = {k: v for k, v in r.items() if k not in ("thinking", "output_config")}
    assert request_bound(r) >= request_bound(plain)


@pytest.mark.parametrize(
    "choice,expected",
    [
        ({"type": "auto"}, "auto"),
        ({"type": "any"}, "required"),
        ({"type": "none"}, "none"),
        ({"type": "tool", "name": "f"}, {"type": "function", "function": {"name": "f"}}),
    ],
)
def test_choices(choice, expected):
    r = req(tools=[{"name": "f", "input_schema": {"type": "object"}}], tool_choice=choice)
    assert k3.chat_request(r)["tool_choice"] == expected


def test_history_order_and_error_semantics():
    call = {"type": "tool_use", "id": "c1", "name": "f", "input": {"cache_control": "user value"}}
    messages = [
        {"role": "assistant", "content": [{"type": "text", "text": "before"}, call]},
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "c1", "is_error": True, "content": "failed"},
                {"type": "text", "text": "after"},
            ],
        },
    ]
    original = deepcopy(messages)
    out = translate_messages(messages)
    assert messages == original
    assert [m["role"] for m in out] == ["assistant", "tool", "user"]
    assert json.loads(out[0]["tool_calls"][0]["function"]["arguments"]) == call["input"]
    assert json.loads(out[1]["content"]) == {"is_error": True, "content": "failed"}
    assert out[2]["content"][0]["text"] == "after"
    assert len(translate_messages([messages[0], messages[0]])) == 2


@pytest.mark.parametrize("finish", ["stop", "length", "tool_calls"])
def test_decode_usage_and_stop(finish):
    data = response().json()
    data["choices"][0]["finish_reason"] = finish
    raw = k3.decode_chat_response(httpx.Response(200, json=data))
    assert raw.original_stop_reason == finish
    assert (
        raw.stop_reason
        == {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}[finish]
    )
    assert raw.usage["output_tokens_details"]["thinking_tokens"] == 5
    assert raw.thinking_content == {"reasoning": "private"}


@pytest.mark.parametrize(
    "invalid",
    [
        {"refusal": "no"},
        {
            "tool_calls": [
                {"type": "function", "id": "x", "function": {"name": "f", "arguments": "[]"}}
            ]
        },
    ],
)
def test_invalid_final_keeps_receipt_unconsumable(invalid):
    data = response().json()
    data["choices"][0]["finish_reason"] = "tool_calls"
    data["choices"][0]["message"].update(invalid)
    raw = k3.decode_chat_response(httpx.Response(200, json=data))
    assert raw.usage["cost"] == "0.00002"
    assert raw.content == [] and raw.validation_error and raw.stop_reason == "invalid_response"


def test_exact_cost_boundary():
    text = response().text.replace('"0.00002"', "0.0220000000000000001")
    raw = k3.decode_chat_response(httpx.Response(200, text=text))
    assert raw.usage["cost"] == "0.0220000000000000001"


def test_proxy_quote_sees_final_reasoning_cap_before_reserve(monkeypatch):
    from types import SimpleNamespace

    captured = []

    class QuoteReached(Exception):
        pass

    c = LLMClient("proxy", firebase_session=SimpleNamespace(id_token="fixture"), model=k3.MODEL)

    def quote(request):
        captured.append(deepcopy(request))
        raise QuoteReached()

    c._client.quote = quote
    monkeypatch.setattr(
        "zylch.llm.budget.reserve", lambda *a, **k: pytest.fail("quote must run first")
    )
    with pytest.raises(QuoteReached):
        c.create_message_sync(messages=[{"role": "user", "content": "fixture"}], max_tokens=512)
    assert captured[0]["max_tokens"] == 8192
    assert captured[0]["thinking"] == {"type": "adaptive"}
    assert captured[0]["output_config"] == {"effort": "max"}


def test_unknown_history_rejected_before_quote(monkeypatch):
    from types import SimpleNamespace

    c = LLMClient("proxy", firebase_session=SimpleNamespace(id_token="fixture"), model=k3.MODEL)
    c._client.quote = lambda *a: pytest.fail("unsupported history reached quote")
    with pytest.raises(BudgetError):
        c.create_message_sync(
            messages=[{"role": "user", "content": [{"type": "image", "source": {}}]}]
        )


@pytest.mark.parametrize("finish", ["length", "content_filter", "unknown"])
def test_partial_tool_calls_never_escape_as_actions(finish):
    data = response().json()
    data["choices"][0]["finish_reason"] = finish
    data["choices"][0]["message"]["tool_calls"] = [
        {"type": "function", "id": "call", "function": {"name": "send", "arguments": "{}"}}
    ]
    raw = k3.decode_chat_response(httpx.Response(200, json=data))
    assert raw.content == []
    assert raw.usage["cost"] == "0.00002"


@pytest.mark.parametrize(
    "controls", [{"output_config": {"effort": "low"}}, {"thinking": {"type": "disabled"}}]
)
def test_explicit_controls_not_silently_overwritten(monkeypatch, controls):
    from types import SimpleNamespace

    client = LLMClient(
        "proxy", firebase_session=SimpleNamespace(id_token="fixture"), model=k3.MODEL
    )
    client._client.quote = lambda *a: pytest.fail("invalid controls reached quote")
    with pytest.raises(BudgetError):
        client.create_message_sync(messages=[{"role": "user", "content": "fixture"}], **controls)
