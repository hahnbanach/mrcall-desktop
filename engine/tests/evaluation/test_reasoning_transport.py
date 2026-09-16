"""Offline transport tests; synthetic responses never reach an LLM service."""

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from zylch.llm import openrouter_pricing as pricing
from zylch.llm.budget_pricing import BudgetError
from zylch.llm.openrouter_client import OpenRouterClient


@pytest.fixture
def module():
    path = Path(__file__).parents[2] / "scripts/evaluation_reasoning_transport.py"
    spec = importlib.util.spec_from_file_location("evaluation_reasoning_transport", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def request(**extra):
    return {
        "model": "moonshotai/kimi-k3",
        "messages": [{"role": "user", "content": "Synthetic"}],
        "max_tokens": 2048,
        "thinking": {"type": "disabled"},
        **extra,
    }


def response(**extra):
    return httpx.Response(
        200,
        json={
            "model": "moonshotai/kimi-k3",
            "content": [{"type": "text", "text": "SKIP"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5, "cost": "0.00002"},
            **extra,
        },
    )


class FakeHTTP:
    def __init__(self, result=None):
        self.calls = []
        self.result = result if result is not None else response()

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.result


def test_disabled_wire_matches_existing_transport(module):
    old, new = FakeHTTP(), FakeHTTP()
    req = request()
    plain = {k: v for k, v in req.items() if k != "thinking"}
    OpenRouterClient("synthetic", http_client=old).create(**plain)
    module.ReasoningEvaluationClient("synthetic", http_client=new).create(**req)
    assert old.calls == new.calls


@pytest.mark.parametrize("cap", [2048, 4096, 8192])
def test_adaptive_controls_and_full_combined_cap_are_reserved(module, cap):
    req = request(max_tokens=cap, thinking={"type": "adaptive"}, output_config={"effort": "max"})
    plain = {k: v for k, v in req.items() if k not in ("thinking", "output_config")}
    bound = module.bound_with_reasoning(req)
    assert bound > module.BASE_REQUEST_BOUND(plain)
    assert bound >= cap * pricing.RATES[module.MODEL][1]
    http = FakeHTTP()
    module.ReasoningEvaluationClient("synthetic", http_client=http).create(**req)
    body = http.calls[0][1]["json"]
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "max"}
    assert body["max_tokens"] == cap
    assert body["provider"]["allow_fallbacks"] is False
    assert body["provider"]["require_parameters"] is True
    assert body["provider"]["max_price"] == pricing.provider_policy(module.MODEL)["max_price"]


@pytest.mark.parametrize(
    "change",
    [
        {"model": "z-ai/glm-5.2"},
        {"max_tokens": 500},
        {"thinking": None},
        {"thinking": {"type": "enabled", "budget_tokens": 1000}},
        {"thinking": {"type": "adaptive"}},
        {"output_config": {"effort": "max"}},
        {"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}},
        {"thinking": {"type": "adaptive"}, "output_config": {"effort": "max", "extra": 1}},
    ],
)
def test_invalid_controls_fail_before_dispatch(module, change):
    http = FakeHTTP()
    with pytest.raises(BudgetError):
        module.ReasoningEvaluationClient("synthetic", http_client=http).create(**request(**change))
    assert http.calls == []


def test_explicit_pricing_install_restores_and_does_not_nest(module):
    original = pricing.request_bound
    with pytest.raises(BudgetError), module.pricing_override():
        pass
    with module.pricing_override(reviewed_experiment=True):
        assert pricing.request_bound is module.bound_with_reasoning
        assert pricing.request_bound(request()) > 0
        with pytest.raises(BudgetError), module.pricing_override(reviewed_experiment=True):
            pass
    assert pricing.request_bound is original


def test_thinking_provenance_kept_without_repairing_completion(module):
    blocks = [
        {"type": "thinking", "thinking": "Synthetic private reasoning", "signature": "sig"},
        {"type": "redacted_thinking", "data": "opaque"},
        {"type": "tool_use", "id": "t", "name": "task_decision", "input": {}},
    ]
    raw = module.decode_response(response(content=blocks, stop_reason="max_tokens"))
    assert raw.raw_content == blocks
    assert raw.thinking_content == blocks[:2]
    assert len(raw.content) == 1 and raw.content[0].type == "tool_use"
    assert raw.stop_reason == raw.original_stop_reason == "max_tokens"
    assert raw.validation_error is None
    raw = module.decode_response(response(content=blocks, stop_reason="end_turn"))
    assert raw.stop_reason == "end_turn"


@pytest.mark.parametrize(
    "content",
    [
        None,
        [None],
        [{"type": "unknown"}],
        [{"type": "thinking", "thinking": None}],
        [{"type": "redacted_thinking", "data": 1}],
        [{"type": "tool_use", "id": " ", "name": "task", "input": {}}],
    ],
)
def test_malformed_blocks_cannot_be_consumed_but_receipt_can_settle(module, content):
    raw = module.decode_response(response(content=content))
    assert raw.content == [] and raw.validation_error
    assert raw.raw_content == content
    assert pricing.usage_cost(module.MODEL, raw.usage)[0] == 20


@pytest.mark.parametrize("extra", [{"model": "wrong"}, {"usage": None}, {"usage": {"cost": "0.1"}}])
def test_missing_receipt_or_model_mismatch_retain_hold(module, extra):
    with pytest.raises(BudgetError):
        module.decode_response(response(**extra))


def test_decimal_receipt_survives_micro_boundary(module):
    payload = '{"model":"moonshotai/kimi-k3","content":[],"usage":{"input_tokens":1,"output_tokens":1,"cost":0.0220000000000000001},"stop_reason":"end_turn"}'
    raw = module.decode_response(httpx.Response(200, text=payload))
    assert Decimal(raw.usage["cost"]) == Decimal("0.0220000000000000001")
    assert pricing.usage_cost(module.MODEL, raw.usage)[0] == 22001
    json.dumps(vars(raw), default=vars)


def test_thinking_refusal_cannot_be_hidden_by_final_content_filter(module):
    blocks = [
        {"type": "thinking", "thinking": "Synthetic", "refusal": "refused"},
        {"type": "tool_use", "id": "t", "name": "task_decision", "input": {}},
    ]
    raw = module.decode_response(response(content=blocks))
    assert raw.content == [] and raw.validation_error
    assert raw.raw_content == blocks
    assert raw.stop_reason == "end_turn"
    assert pricing.usage_cost(module.MODEL, raw.usage)[0] == 20


def test_top_level_refusal_cannot_bypass_with_tool_use_stop(module):
    blocks = [{"type": "tool_use", "id": "t", "name": "task_decision", "input": {}}]
    raw = module.decode_response(
        response(content=blocks, stop_reason="tool_use", refusal="refused")
    )
    assert raw.content == [] and raw.validation_error
    assert raw.refusal == "refused"
    assert raw.raw_content == blocks
    assert raw.stop_reason == raw.original_stop_reason == "tool_use"
    assert pricing.usage_cost(module.MODEL, raw.usage)[0] == 20


def chat_response(**extra):
    return httpx.Response(
        200,
        json={
            "model": "moonshotai/kimi-k3",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "reasoning": "Private synthetic reasoning",
                        "tool_calls": [
                            {
                                "id": "one",
                                "type": "function",
                                "function": {
                                    "name": "task_decision",
                                    "arguments": '{"task_action":"none"}',
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 15,
                "prompt_tokens_details": {"cached_tokens": 3},
                "completion_tokens_details": {"reasoning_tokens": 10},
                "cost": "0.00003",
            },
            **extra,
        },
    )


def test_chat_translation_preserves_order_schema_and_named_tool(module):
    req = request(
        system=[
            {"type": "text", "text": "First", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "Second"},
        ],
        tools=[
            {
                "name": "task_decision",
                "description": "Synthetic",
                "input_schema": {"type": "object"},
            }
        ],
        tool_choice={"type": "tool", "name": "task_decision"},
        thinking={"type": "adaptive"},
        output_config={"effort": "max"},
    )
    wire = module.chat_request(req)
    assert wire["messages"] == [{"role": "system", "content": "First\n\nSecond"}, *req["messages"]]
    assert wire["tools"][0]["function"]["parameters"] == req["tools"][0]["input_schema"]
    assert wire["tool_choice"] == {"type": "function", "function": {"name": "task_decision"}}
    assert wire["reasoning"] == {"effort": "max"}
    assert "thinking" not in wire and "output_config" not in wire
    assert module.bound_chat_reasoning(req) >= module.bound_with_reasoning(req)


@pytest.mark.parametrize("adaptive", [False, True])
def test_both_chat_arms_use_same_route_and_retain_caps(module, adaptive):
    controls = (
        {"thinking": {"type": "adaptive"}, "output_config": {"effort": "max"}} if adaptive else {}
    )
    http = FakeHTTP(chat_response())
    raw = module.ChatReasoningEvaluationClient("synthetic", http_client=http).create(
        **request(**controls)
    )
    url, args = http.calls[0]
    assert url.endswith("/api/v1/chat/completions")
    assert args["json"]["provider"] == pricing.provider_policy(module.MODEL)
    assert args["json"]["reasoning"] == ({"effort": "max"} if adaptive else {"enabled": False})
    assert raw.usage["output_tokens_details"]["thinking_tokens"] == 10
    assert raw.usage["cache_read_input_tokens"] == 3
    assert raw.stop_reason == "tool_use" and raw.original_stop_reason == "tool_calls"
    assert raw.content[0].input == {"task_action": "none"}
    assert raw.thinking_content == {"reasoning": "Private synthetic reasoning"}
    assert raw.raw_chat_response["choices"][0]["message"]["reasoning"]


@pytest.mark.parametrize(
    "change",
    [
        {"top_p": 0.9},
        {"messages": [{"role": "user", "content": [{"type": "image", "source": {}}]}]},
        {"tool_choice": {"type": "auto"}},
        {"system": [{"type": "text", "text": "x", "unexpected": True}]},
    ],
)
def test_chat_rejects_untranslated_options_before_http(module, change):
    http = FakeHTTP(chat_response())
    with pytest.raises((BudgetError, ValueError)):
        module.ChatReasoningEvaluationClient("synthetic", http_client=http).create(
            **request(**change)
        )
    assert not http.calls


@pytest.mark.parametrize("arguments", ["bad JSON", "[]", '{"x":NaN}', None])
def test_chat_bad_tool_json_settles_receipt_but_never_exposes_action(module, arguments):
    data = chat_response().json()
    data["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = arguments
    raw = module.decode_chat_response(httpx.Response(200, json=data))
    assert raw.validation_error and raw.content == []
    assert pricing.usage_cost(module.MODEL, raw.usage)[0] == 30


@pytest.mark.parametrize(
    "finish,expected",
    [
        ("stop", "end_turn"),
        ("tool_calls", "tool_use"),
        ("length", "max_tokens"),
        ("content_filter", "unsupported_chat_finish"),
        (None, "unsupported_chat_finish"),
    ],
)
def test_chat_stop_mapping_never_repairs_truncation(module, finish, expected):
    data = chat_response().json()
    data["choices"][0]["finish_reason"] = finish
    raw = module.decode_chat_response(httpx.Response(200, json=data))
    assert raw.stop_reason == expected and raw.original_stop_reason == finish


def test_chat_refusal_cost_and_protocol_pricing_install(module):
    data = chat_response().json()
    data["choices"][0]["message"]["refusal"] = "refused"
    raw = module.decode_chat_response(httpx.Response(200, json=data))
    assert raw.content == [] and raw.validation_error and raw.refusal
    assert pricing.usage_cost(module.MODEL, raw.usage)[0] == 30
    with module.pricing_override(reviewed_experiment=True, protocol="chat-completions-v1"):
        assert pricing.request_bound is module.bound_chat_reasoning
        assert (
            pricing.request_bound(request(max_tokens=8192)) >= 8192 * pricing.RATES[module.MODEL][1]
        )


def test_chat_decimal_receipt_is_exact(module):
    data = chat_response().json()
    data["usage"]["cost"] = "EXACT_NUMBER"
    body = json.dumps(data).replace('"EXACT_NUMBER"', "0.0220000000000000001")
    raw = module.decode_chat_response(httpx.Response(200, text=body))
    assert pricing.usage_cost(module.MODEL, raw.usage)[0] == 22001
    assert raw.raw_wire_json == body
