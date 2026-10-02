"""The pipeline's preflight is free and still surfaces 401 and 402 (brief D3).

It reads, it never infers: Anthropic's model list, OpenRouter's key record,
MrCall's bounded capabilities and credit balance — each against a fake
provider here, never the network — and it admits the model locally, so an
unpriced model stops it as the paid ping's reservation did. What it raises
reaches ``humanize_error`` through the pipeline's ``llm`` stage, as before.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from zylch.llm.bounded_proxy import BoundedProxyClient
from zylch.llm.budget_pricing import BudgetError
from zylch.llm.client import LLMClient
from zylch.llm.openrouter_client import OpenRouterClient
from zylch.services.error_messages import humanize_error


def check(client):
    asyncio.run(client.check_transport())


def direct(status, seen):
    import anthropic
    import httpx2

    def handler(request):
        seen.append((request.method, request.url.path))
        if status != 200:
            return httpx2.Response(
                status, json={"type": "error", "error": {"type": "x", "message": "m"}}
            )
        return httpx2.Response(
            200, json={"data": [], "has_more": False, "first_id": None, "last_id": None}
        )

    client = LLMClient("direct", api_key="synthetic", model="claude-sonnet-5-5")
    client._client = anthropic.Anthropic(
        api_key="synthetic",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    return client


def test_direct_reads_the_model_list_and_never_sends_a_message():
    seen = []
    check(direct(200, seen))
    assert seen == [("GET", "/v1/models")]


def test_direct_surfaces_a_refused_key_as_the_ping_did():
    import anthropic

    seen = []
    with pytest.raises(anthropic.AuthenticationError) as raised:
        check(direct(401, seen))
    assert seen == [("GET", "/v1/models")]
    assert humanize_error(raised.value, "llm")["severity"] == "error"


def router(handler):
    client = LLMClient("openrouter", api_key="synthetic", model="z-ai/glm-5.3-flash")
    client._client = OpenRouterClient(
        "synthetic", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    return client


def test_openrouter_reads_the_key_record_and_surfaces_401_and_402():
    seen = []

    def answer(status, data=None):
        def handler(request):
            seen.append((request.method, request.url.path, request.headers["authorization"]))
            return httpx.Response(status, json={"data": data or {}})

        return handler

    check(router(answer(200, {"limit": None, "limit_remaining": None})))
    assert seen == [("GET", "/api/v1/key", "Bearer synthetic")]
    for status in (401, 402):
        with pytest.raises(BudgetError, match=f"HTTP {status}") as raised:
            check(router(answer(status)))
        assert humanize_error(raised.value, "llm")["kind"] == "llm_budget"
    with pytest.raises(BudgetError, match="no credit left"):
        check(router(answer(200, {"limit": 5, "limit_remaining": 0})))


def credits(answers, seen):
    def handler(request):
        seen.append((request.method, request.url.path))
        status, body = answers[request.url.path]
        return httpx.Response(status, json=body)

    session = SimpleNamespace(id_token="synthetic")
    client = LLMClient("proxy", firebase_session=session, model="claude-sonnet-5-5")
    client._client = BoundedProxyClient(
        "https://synthetic.test",
        session,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return client


CAPABILITIES = "/api/desktop/llm/bounded/capabilities"
BALANCE = "/api/desktop/llm/balance"
SERVED = {"protocol": "mrcall-bounded-v1", "currency": "USD", "models": []}


def test_credits_read_capabilities_and_balance_and_surface_401_and_402():
    seen = []
    check(credits({CAPABILITIES: (200, SERVED), BALANCE: (200, {"balance_credits": 9})}, seen))
    assert seen == [("GET", CAPABILITIES), ("GET", BALANCE)]
    cases = [
        ({CAPABILITIES: (401, {})}, "Sign in again"),
        ({CAPABILITIES: (200, SERVED), BALANCE: (401, {})}, "Sign in again"),
        ({CAPABILITIES: (200, SERVED), BALANCE: (402, {})}, "Top up"),
        ({CAPABILITIES: (200, SERVED), BALANCE: (200, {"balance_credits": 0})}, "Top up"),
    ]
    for answers, hint in cases:
        with pytest.raises(BudgetError, match=hint) as raised:
            check(credits(answers, []))
        detail = humanize_error(raised.value, "llm")
        assert detail["kind"] == "llm_budget" and hint in detail["detail"]


def test_an_unpriced_model_stops_the_check_before_any_read():
    seen = []
    client = direct(200, seen)
    client.model = "claude-unpriced-9"
    with pytest.raises(BudgetError, match="pricing is not configured"):
        check(client)
    assert seen == []
