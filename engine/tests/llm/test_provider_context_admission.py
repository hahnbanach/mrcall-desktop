"""Scripted admission regressions; no provider tokenizer or factual-quality claim."""

import json
from copy import deepcopy
from decimal import Decimal

import httpx
import pytest

from zylch.llm import k3_reasoning as k3
from zylch.llm.budget import budget_snapshot
from zylch.llm.budget_pricing import BudgetError
from zylch.llm.budget_pricing import request_bound as direct_bound
from zylch.llm.client import LLMClient
from zylch.llm.openrouter_client import OpenRouterClient, messages_request
from zylch.llm.openrouter_pricing import capped, request_bound
from zylch.llm.roles import catalogue
from zylch.storage import database
from zylch.storage.models import LlmReservation, LlmUsage

MODEL = "z-ai/glm-5.2"
DISABLED_COMPRESSION = [{"id": "context-compression", "enabled": False}]


def retrieved_request(model=MODEL):
    result = json.dumps(
        {"source_id": "fixture-mail", "date": "2026-10-04", "body": "界" * 75000},
        ensure_ascii=False,
    )
    return {
        "model": model,
        "max_tokens": 8192,
        "system": [{"type": "text", "text": "Preserve source dates and uncertainty. è"}],
        "messages": [
            {"role": "user", "content": "What is the current offer?"},
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": name, "name": name, "input": {"query": "offer"}}
                    for name in ("memory_search", "search_local_emails")
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": name, "content": result}
                    for name in ("memory_search", "search_local_emails")
                ],
            },
        ],
        "tools": [
            {
                "name": name,
                "description": "Read permitted evidence.",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            }
            for name in ("memory_search", "search_local_emails")
        ],
    }


def success(model):
    if model == k3.MODEL:
        return httpx.Response(
            200,
            json={
                "model": model,
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "cost": "0.00002"},
                "choices": [
                    {"finish_reason": "stop", "message": {"role": "assistant", "content": "OK"}}
                ],
            },
        )
    return httpx.Response(
        200,
        json={
            "model": model,
            "content": [{"type": "text", "text": "OK"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 10, "cost": "0.00002"},
        },
    )


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "admission.db"))
    monkeypatch.setenv("OWNER_ID", "context-fixture")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    database.dispose_engine()
    database.Base.metadata.create_all(
        database.get_engine(), tables=[LlmReservation.__table__, LlmUsage.__table__]
    )
    yield
    database.dispose_engine()


def guarded_client(model, handler):
    client = LLMClient("openrouter", api_key="synthetic", model=model)
    client._client = OpenRouterClient(
        "synthetic", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    return client


@pytest.mark.parametrize("model", [MODEL, "anthropic/claude-sonnet-5", k3.MODEL])
def test_large_memory_mail_evidence_dispatches_once_intact_with_a_full_hold(ledger, model):
    request = retrieved_request(model)
    before = deepcopy(request)
    calls = []

    def upstream(http_request):
        body = json.loads(http_request.content)
        calls.append(body)
        assert body["model"] == model
        assert body["plugins"] == DISABLED_COMPRESSION
        evidence = request["messages"][2]["content"]
        if model == k3.MODEL:
            assert body["tools"][0]["function"]["parameters"] == request["tools"][0]["input_schema"]
            assert [m["content"] for m in body["messages"] if m["role"] == "tool"] == [
                block["content"] for block in evidence
            ]
            assert body["reasoning"] == {"effort": "max"}
            assert body["provider"]["only"] == ["digitalocean"]
            assert body["provider"]["allow_fallbacks"] is False
        else:
            assert body["tools"][0]["input_schema"] == request["tools"][0]["input_schema"]
            assert body["messages"] == request["messages"]
        assert "Preserve source dates and uncertainty. è" in str(
            body["messages"] if model == k3.MODEL else body["system"]
        )
        input_rate, output_rate = capped(model)
        if model.startswith("anthropic/"):
            input_rate *= 2
        evidence_bytes = sum(len(block["content"].encode()) for block in evidence)
        minimum_money = (
            Decimal(evidence_bytes) * input_rate + body["max_tokens"] * output_rate
        ) / 1000000
        assert budget_snapshot("context-fixture")["reserved_usd"] >= float(minimum_money)
        return success(model)

    client = guarded_client(model, upstream)
    args = {key: value for key, value in request.items() if key != "model"}
    assert client.create_message_sync(**args).content[0].text == "OK"
    assert request == before
    assert len(calls) == 1
    assert budget_snapshot("context-fixture")["reserved_usd"] == 0
    assert budget_snapshot("context-fixture")["spent_usd"] == 0.00002


def test_original_k3_messages_and_translated_chat_both_admit_large_input():
    original = retrieved_request(k3.MODEL)
    assert len(json.dumps(original, ensure_ascii=False).encode()) > 400000
    assert request_bound(original) > 0
    reasoning = {**original, "thinking": {"type": "adaptive"}, "output_config": {"effort": "max"}}
    assert request_bound(reasoning) >= request_bound(original)
    with pytest.raises(BudgetError, match="200000-token context window"):
        direct_bound({**original, "model": "claude-sonnet-5"}, "direct")


def test_expanding_k3_function_arguments_keep_the_larger_translated_hold():
    request = retrieved_request(k3.MODEL)
    request.update(thinking={"type": "adaptive"}, output_config={"effort": "max"})
    request["messages"][1]["content"][0]["input"] = {"query": '\\"' * 100000}
    plain = {k: v for k, v in request.items() if k not in ("thinking", "output_config")}
    assert request_bound(request) > request_bound(plain)
    wire = k3.chat_request(request)
    assert (
        json.loads(wire["messages"][2]["tool_calls"][0]["function"]["arguments"])
        == request["messages"][1]["content"][0]["input"]
    )


@pytest.mark.parametrize("model", [MODEL, k3.MODEL])
@pytest.mark.parametrize("status,released", [(400, True), (413, True), (503, False), (200, False)])
def test_overflow_refusal_and_uncertain_response_preserve_accounting(
    ledger, model, status, released
):
    calls = []

    def upstream(request):
        calls.append(request)
        assert budget_snapshot("context-fixture")["reserved_usd"] > 0
        return httpx.Response(status, json={"error": {"code": 400, "message": "context overflow"}})

    client = guarded_client(model, upstream)
    with pytest.raises(BudgetError):
        client.create_message_sync(
            **{k: v for k, v in retrieved_request(model).items() if k != "model"}
        )
    assert len(calls) == 1
    assert (budget_snapshot("context-fixture")["reserved_usd"] == 0) is released
    assert budget_snapshot("context-fixture")["spent_usd"] == 0


@pytest.mark.parametrize("model", [MODEL, k3.MODEL])
def test_timeout_keeps_hold_without_retry(ledger, model):
    calls = []

    def upstream(request):
        calls.append(request)
        raise httpx.ReadTimeout("scripted uncertainty")

    with pytest.raises(httpx.ReadTimeout):
        guarded_client(model, upstream).create_message_sync(
            messages=[{"role": "user", "content": "Hi"}]
        )
    assert len(calls) == 1
    assert budget_snapshot("context-fixture")["reserved_usd"] > 0


@pytest.mark.parametrize("model", [MODEL, k3.MODEL])
@pytest.mark.parametrize(
    "invalid",
    [
        {"max_tokens": True},
        {"max_tokens": 131073},
        {"extra_body": {"plugins": [{"id": "context-compression"}]}},
        {"tools": [{"type": "web_search_20250305", "name": "search"}]},
        {"messages": [{"role": "user", "content": [{"type": "image", "source": {}}]}]},
    ],
)
def test_invalid_features_and_output_do_not_dispatch(model, invalid):
    adapter = OpenRouterClient(
        "synthetic",
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda _: pytest.fail("invalid request dispatched"))
        ),
    )
    request = {"model": model, "max_tokens": 8192, "messages": [{"role": "user", "content": "Hi"}]}
    if model == k3.MODEL:
        request.update(thinking={"type": "adaptive"}, output_config={"effort": "max"})
    with pytest.raises(BudgetError):
        adapter.create(**{**request, **invalid})


@pytest.mark.parametrize("model", [MODEL, k3.MODEL])
def test_snapshot_context_output_limit_is_live_and_does_not_estimate_input(price_snapshot, model):
    request = {"model": model, "max_tokens": 8192, "messages": [{"role": "user", "content": "Hi"}]}
    if model == k3.MODEL:
        request.update(thinking={"type": "adaptive"}, output_config={"effort": "max"})
    assert request_bound(request) > 0
    changed = deepcopy(price_snapshot)
    changed["models"][model]["metadata"]["context_length"] = 8192
    catalogue.set_layers(changed, build=False)
    with pytest.raises(BudgetError, match="output-token limit leaves no room"):
        request_bound(request)
    changed["models"][model]["metadata"]["context_length"] = None
    catalogue.set_layers(changed, build=False)
    assert request_bound(request) > 0
    if model == MODEL:
        assert request_bound({**request, "max_tokens": 131072}) > 0


def test_messages_reasoning_system_schema_and_multibyte_survive_without_compression():
    request = retrieved_request()
    request["messages"][1]["content"].insert(
        0, {"type": "thinking", "thinking": "Reasoning è", "signature": "sig"}
    )
    request.update(thinking={"type": "adaptive"}, output_config={"effort": "high"})
    original = deepcopy(request)
    assert request_bound(request) > 0
    wire = messages_request(request)
    assert wire["messages"] == request["messages"]
    assert wire["system"] == request["system"]
    assert wire["tools"] == request["tools"]
    assert wire["thinking"] == request["thinking"]
    assert wire["output_config"] == request["output_config"]
    assert wire["plugins"] == DISABLED_COMPRESSION
    assert request == original


def test_router_admission_does_not_require_an_unrelated_direct_model(price_snapshot):
    router_only = deepcopy(price_snapshot)
    router_only["direct"] = {}
    catalogue.set_layers(router_only, build=False)
    assert request_bound(retrieved_request()) > 0


def test_small_context_endpoint_explicitly_disables_default_compression(price_snapshot):
    changed = deepcopy(price_snapshot)
    changed["models"][MODEL]["metadata"]["context_length"] = 8192
    catalogue.set_layers(changed, build=False)
    seen = []

    def upstream(request):
        seen.append(json.loads(request.content))
        return success(MODEL)

    adapter = OpenRouterClient(
        "synthetic", http_client=httpx.Client(transport=httpx.MockTransport(upstream))
    )
    adapter.create(model=MODEL, messages=[{"role": "user", "content": "Hi"}], max_tokens=64)
    assert len(seen) == 1
    assert seen[0]["plugins"] == DISABLED_COMPRESSION
    assert seen[0]["messages"] == [{"role": "user", "content": "Hi"}]


def test_priced_model_without_metadata_keeps_finite_output_fallback(monkeypatch):
    from zylch.llm.openrouter_pricing import RATES

    model = "fixture/catalogue-missing"
    monkeypatch.setitem(RATES, model, (Decimal("0.5"), Decimal("1")))
    request = {"model": model, "messages": [{"role": "user", "content": "Hi"}]}
    assert catalogue.metadata(model) is None
    assert request_bound({**request, "max_tokens": 131072}) > 0
    with pytest.raises(BudgetError, match="supported output-token limit"):
        request_bound({**request, "max_tokens": 131073})
