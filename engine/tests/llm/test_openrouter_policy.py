import json

import httpx
import pytest

from zylch.llm.budget_pricing import BudgetError
from zylch.llm.model_policy import profile_value, resolve_model, resolve_provider
from zylch.llm.openrouter_client import OpenRouterClient
from zylch.llm.openrouter_pricing import MODEL, request_bound, usage_cost


def request():
    return {"model": MODEL, "messages": [{"role": "user", "content": "hello"}], "max_tokens": 64}


def test_saved_profile_wins_ambient_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient")
    (tmp_path / ".env").write_text("LLM_PROVIDER=openrouter\nOPENROUTER_API_KEY=profile\n")
    assert resolve_provider() == "openrouter"
    assert profile_value("ANTHROPIC_API_KEY") == ""
    assert profile_value("OPENROUTER_API_KEY") == "profile"


def test_preserve_explicit_models_and_legacy_routing():
    values = {"ANTHROPIC_API_KEY": "key", "ANTHROPIC_MODEL": "claude-opus-5"}
    assert resolve_provider(values) == "anthropic"
    assert resolve_model(values=values) == "claude-opus-5"
    values.update(LLM_MODEL_PRESET="economy", MODEL_MEMORY_MERGE="claude-sonnet-5")
    assert resolve_model(values=values) == "claude-haiku-4-5"
    assert resolve_model("MODEL_MEMORY_MERGE", values=values) == "claude-sonnet-5"
    assert resolve_model(values={}) == "claude-haiku-4-5"
    assert resolve_provider({"LLM_PROVIDER": "mrcall", "ANTHROPIC_API_KEY": "key"}) == "mrcall"


def test_http_controls_and_no_ambient_credentials(monkeypatch):
    seen = []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")

    def handler(req):
        seen.append(req)
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 2, "cost": 0.00002},
            },
        )

    client = OpenRouterClient(
        "chosen", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    r = request()
    r["system"] = [{"type": "text", "text": "system", "cache_control": {"type": "ephemeral"}}]
    response = client.create(**r)
    assert response.content[0].text == "ok"
    body = json.loads(seen[0].content)
    assert body["provider"]["max_price"] == {"prompt": "0.966", "completion": "3.036", "request": "0"}
    assert body["provider"]["allow_fallbacks"] is False
    assert body["provider"]["require_parameters"] is True
    assert body["thinking"] == {"type": "disabled"}
    assert "cache_control" not in body["system"][0]
    assert seen[0].headers["authorization"] == "Bearer chosen"
    assert "x-api-key" not in seen[0].headers
    assert usage_cost(MODEL, response.usage)[0] == 20


def test_failure_is_one_attempt():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(429)

    client = OpenRouterClient(
        "key", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(BudgetError):
        client.create(**request())
    assert len(seen) == 1


@pytest.mark.parametrize(
    "override",
    [
        {"model": "unknown"},
        {"extra_body": {"provider": {}}},
        {"thinking": {"type": "enabled"}},
        {"service_tier": "priority"},
        {"max_tokens": True},
    ],
)
def test_unbounded_features_refused(override):
    with pytest.raises(BudgetError):
        request_bound({**request(), **override})


@pytest.mark.parametrize(
    "usage",
    [
        {},
        {"cost": None},
        {"cost": True},
        {"cost": -1},
        {"cost": "NaN"},
        {"cost": 0.1, "input_tokens": 1},
    ],
)
def test_unknown_charge_retains_hold(usage):
    with pytest.raises(BudgetError):
        usage_cost(MODEL, usage)


def test_fractional_cost_rounds_up():
    assert usage_cost(MODEL, {"cost": ".0000001", "input_tokens": 1, "output_tokens": 0})[0] == 1
    assert request_bound(request()) > 64 * 3.036


def test_cache_stripping_preserves_tool_data():
    from zylch.llm.openrouter_client import _without_cache

    source = request()
    source["messages"][0]["content"] = [
        {
            "type": "tool_use",
            "id": "t",
            "name": "f",
            "input": {"cache_control": "user data"},
            "cache_control": {"type": "ephemeral"},
        }
    ]
    source["tools"] = [
        {
            "name": "f",
            "input_schema": {"properties": {"cache_control": {"type": "string"}}},
            "cache_control": {"type": "ephemeral"},
        }
    ]
    result = _without_cache(source)
    assert result["messages"][0]["content"][0]["input"] == {"cache_control": "user data"}
    assert "cache_control" not in result["messages"][0]["content"][0]
    assert "cache_control" in result["tools"][0]["input_schema"]["properties"]
    assert "cache_control" not in result["tools"][0]
    assert "cache_control" in source["tools"][0]


def test_real_factory_saved_explicit_provider_and_live_model(tmp_path, monkeypatch):
    from zylch.llm.client import make_llm_client

    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    path = tmp_path / ".env"
    base = "ANTHROPIC_API_KEY=fake-anthropic\nOPENROUTER_API_KEY=fake-router\n"
    path.write_text(base + "LLM_PROVIDER=openrouter\n")
    first = make_llm_client()
    assert first.transport == "openrouter"
    assert first.model == MODEL
    assert first._client._key == "fake-router"
    path.write_text(base + "LLM_PROVIDER=anthropic\nLLM_MODEL_PRESET=balanced\n")
    second = make_llm_client()
    assert second.transport == "direct"
    assert second.model == "claude-sonnet-5"
    assert second._client.api_key == "fake-anthropic"
    second._client.close()
    path.write_text(base + "LLM_PROVIDER=mrcall\n")
    monkeypatch.setattr("zylch.auth.get_session", lambda: None)
    with pytest.raises(RuntimeError, match="Sign in"):
        make_llm_client()


def test_real_factory_missing_selected_key_never_falls_back(tmp_path, monkeypatch):
    from zylch.llm.client import make_llm_client

    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "ambient-must-not-be-used")
    (tmp_path / ".env").write_text("LLM_PROVIDER=openrouter\nANTHROPIC_API_KEY=fake-other\n")
    with pytest.raises(RuntimeError, match="selected openrouter"):
        make_llm_client()


def test_routed_model_presets_and_saved_values_override_ambient(tmp_path, monkeypatch):
    from zylch.llm import routed_model

    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("MODEL_MEMORY_MERGE", "claude-opus-5")
    path = tmp_path / ".env"
    path.write_text("LLM_PROVIDER=anthropic\nLLM_MODEL_PRESET=economy\n")
    assert routed_model("MODEL_MEMORY_MERGE") == "claude-haiku-4-5"
    path.write_text("MODEL_MEMORY_MERGE=claude-sonnet-5\n")
    assert routed_model("MODEL_MEMORY_MERGE") == "claude-sonnet-5"
