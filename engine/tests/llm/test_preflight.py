"""The pipeline's preflight is free and still surfaces 401 and 402 (brief D3).

It reads, it never infers: Anthropic's model list, OpenRouter's key record
and account balance, MrCall's bounded capabilities and credit balance — each against a fake
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
    # The key's record, then the account's balance (IR1 m2): both free reads.
    assert seen == [
        ("GET", "/api/v1/key", "Bearer synthetic"),
        ("GET", "/api/v1/credits", "Bearer synthetic"),
    ]
    for status in (401, 402):
        with pytest.raises(BudgetError, match=f"HTTP {status}") as raised:
            check(router(answer(status)))
        assert humanize_error(raised.value, "llm")["kind"] == "llm_budget"
    with pytest.raises(BudgetError, match="no credit left"):
        check(router(answer(200, {"limit": 5, "limit_remaining": 0})))


def balance(status, data=None):
    """A key with no limit of its own, and ``/credits`` answering ``status``."""
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/api/v1/key":
            return httpx.Response(200, json={"data": {"limit": None, "limit_remaining": None}})
        if status != 200:
            return httpx.Response(status, json={"error": {"code": status, "message": "m"}})
        return httpx.Response(200, json={"data": data})

    return router(handler), seen


def test_openrouter_reads_the_account_balance_and_surfaces_an_exhausted_one():
    """IR1 m2: ``/key`` reflects only the key's own cap; an exhausted account —
    the 402 a paid call gets with ``limit_source: openrouter_credits`` — is read
    from ``/credits`` and raises as a spent key limit does."""
    both = ["/api/v1/key", "/api/v1/credits"]
    for spent in (
        {"total_credits": 10, "total_usage": 10},
        {"total_credits": 10, "total_usage": 12.5},
        {"total_credits": 0, "total_usage": 0},
    ):
        client, seen = balance(200, spent)
        with pytest.raises(BudgetError, match="account has no credit left") as raised:
            check(client)
        assert seen == both
        assert humanize_error(raised.value, "llm")["kind"] == "llm_budget"
    for left in (
        {"total_credits": 10, "total_usage": 9.99},
        {"total_credits": "10", "total_usage": 11},
        {},
        None,
    ):
        client, seen = balance(200, left)
        check(client)
        assert seen == both
    # OpenRouter documents the read for management keys: a key refused it
    # (403) keeps only the key-limit check; any other failure raises.
    client, seen = balance(403)
    check(client)
    assert seen == both
    client, seen = balance(500)
    with pytest.raises(BudgetError, match="HTTP 500"):
        check(client)


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
