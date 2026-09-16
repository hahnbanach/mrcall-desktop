"""Upstream model adapters must retain the pilot's bounds and evidence rules.

Use the actual ChatService/core/policy and guarded LLMClient. Only external
provider responses/HTTP and the synthetic source fixtures are substituted.
"""

import json
from types import SimpleNamespace

import httpx
import pytest

from tests.services import test_procedure_email as email_fixture
from tests.services.test_procedure_email import (
    OWNER,
    drafts,
    finish,
    read,
    run,
)
from zylch.llm.budget import budget_snapshot
from zylch.llm.client import LLMClient
from zylch.llm.openrouter_client import OpenRouterClient

K3 = "moonshotai/kimi-k3"
# Reuse the actual SQLite/ChatService fixture, including resource teardown.
setup = email_fixture.setup


def install_client(monkeypatch, client):
    monkeypatch.setattr("zylch.assistant.core.make_llm_client", lambda: client)


def test_k3_real_wire_keeps_pilot_cap_and_settles(setup, monkeypatch):
    requests = []

    def http(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.path == "/api/v1/chat/completions"
        assert body["max_tokens"] == 1024
        assert body["reasoning"] == {"effort": "max"}
        assert body["provider"]["only"] == ["digitalocean"]
        assert body["provider"]["allow_fallbacks"] is False
        assert budget_snapshot(OWNER)["reserved_usd"] > 0
        first = len(requests) == 1
        return httpx.Response(
            200,
            json={
                "model": K3,
                "id": f"fixture-{len(requests)}",
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 10,
                    "cost": "0.00002",
                    "completion_tokens_details": {"reasoning_tokens": 5},
                },
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "type": "function",
                                    "id": "read" if first else "finish",
                                    "function": {
                                        "name": "capability_read" if first else "procedure_finish",
                                        "arguments": json.dumps(
                                            {"operation": "order.exists"}
                                            if first
                                            else {"status": "order_exists", "include_memory": False}
                                        ),
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        )

    client = LLMClient("openrouter", api_key="fixture", model=K3)
    with httpx.Client(transport=httpx.MockTransport(http)) as transport:
        client._client = OpenRouterClient("fixture", http_client=transport)
        install_client(monkeypatch, client)
        result = run(setup)
    assert len(requests) == 2
    assert result["metadata"]["procedure_status"] == "order_exists"
    assert len(drafts()) == 1
    assert setup.provider.call_count == 1
    assert budget_snapshot(OWNER)["spent_usd"] == pytest.approx(0.00004)
    assert budget_snapshot(OWNER)["reserved_usd"] == 0


def test_k3_proxy_quote_receives_final_pilot_cap(setup, monkeypatch):
    requests = []
    client = LLMClient("proxy", firebase_session=SimpleNamespace(id_token="fixture"), model=K3)

    def quote(request):
        requests.append(request)
        raise RuntimeError("fixture stops before remote quotation")

    client._client.quote = quote
    install_client(monkeypatch, client)
    monkeypatch.setattr(
        "zylch.llm.budget.reserve", lambda *a, **k: pytest.fail("quote must precede reservation")
    )
    run(setup)
    assert len(requests) == 1
    assert requests[0]["max_tokens"] == 1024
    assert requests[0]["thinking"] == {"type": "adaptive"}
    assert requests[0]["output_config"] == {"effort": "max"}
    assert drafts() == []
    setup.provider.assert_not_called()


def test_complete_end_turn_tools_still_require_actual_evidence(setup):
    responses = [read(), finish()]
    for response in responses:
        response.stop_reason = "end_turn"
    setup.messages.side_effect = responses
    result = run(setup)
    assert result["metadata"]["procedure_status"] == "order_exists"
    assert setup.provider.call_count == 1
    assert len(drafts()) == 1


def test_normalized_finish_cannot_fabricate_order_evidence(setup):
    fabricated, unavailable = finish(), finish("unavailable", call_id="fallback")
    fabricated.stop_reason = unavailable.stop_reason = "end_turn"
    setup.messages.side_effect = [fabricated, unavailable]
    result = run(setup)
    assert result["metadata"]["procedure_status"] == "unavailable"
    setup.provider.assert_not_called()
    assert drafts()[0]["body"] == setup.artifact.message("unavailable")


@pytest.mark.parametrize("reason,refusal", [("max_tokens", None), ("end_turn", "refused")])
def test_incomplete_or_refused_turn_cannot_read(setup, reason, refusal):
    response = read()
    response.stop_reason = reason
    response.refusal = refusal
    setup.messages.return_value = response
    result = run(setup)
    assert result["metadata"]["procedure_status"] == "unavailable"
    setup.provider.assert_not_called()
    assert drafts()[0]["body"] == setup.artifact.message("unavailable")
