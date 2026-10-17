"""Disposable company stores and scripted Stripe HTTP beneath the native RPC path."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from tests.assignments.conftest import env as company_env
from tests.qonto.conftest import env
from zylch.rpc.dispatch import dispatch_raw
from zylch.stripe import connection, provider

KEY = "rk_test_DisposableSecretOnly"


@pytest.fixture(autouse=True)
def cleanup_test_data():
    yield


@pytest.fixture
def stripe_env(company_env, monkeypatch, tmp_path):
    from zylch import runtime
    from zylch.cli.profiles import get_active_profile_dir
    from zylch.llm import budget, client
    from pathlib import Path

    home = tmp_path / "private-home"
    home.mkdir(mode=0o700)
    directory = Path(get_active_profile_dir())
    directory.chmod(0o700)
    monkeypatch.setenv("ZYLCH_HOME", str(home))
    monkeypatch.setattr(runtime, "_serving", False)
    connection._challenges.clear()
    calls = []

    def refuse_paid(*args, **kwargs):
        calls.append("paid")
        raise AssertionError("Stripe RPC must not call an LLM or reserve budget")

    monkeypatch.setattr(budget, "reserve", refuse_paid)
    monkeypatch.setattr(client.LLMClient, "create_message", refuse_paid)
    monkeypatch.setattr(client.LLMClient, "create_message_sync", refuse_paid)

    async def arpc(name, **params):
        return await dispatch_raw(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": name, "params": params}),
            lambda *_: None,
        )

    def rpc(name, **params):
        return asyncio.run(arpc(name, **params))

    value = SimpleNamespace(company=company_env, directory=directory, home=home, rpc=rpc, arpc=arpc)
    yield value
    assert calls == []
    connection._challenges.clear()


@pytest.fixture
def stripe_http(stripe_env, monkeypatch):
    class Script:
        def __init__(self):
            self.requests = []
            self.callback = None
            self.account = {"id": "acct_fixture", "business_profile": {"name": "Fixture"}}
            self.rows = {
                resource: [{"id": prefix + "_fixture", "livemode": False}]
                for resource, prefix in provider.RESOURCES.items()
            }
            self.has_more = False

        async def handle(self, request):
            self.requests.append(request)
            assert request.method == "GET"
            assert request.url.host == "api.stripe.com"
            assert request.headers["authorization"] == "Bearer " + KEY
            assert request.headers["stripe-version"] == provider.API_VERSION
            if self.callback:
                value = self.callback(request)
                if hasattr(value, "__await__"):
                    value = await value
                if value is not None:
                    return value
            path = request.url.path.removeprefix("/v1/")
            if path == "account":
                return httpx.Response(200, json=self.account)
            resource, _, record = path.partition("/")
            if record:
                rows = [row for row in self.rows[resource] if row["id"] == record]
                return httpx.Response(200, json=rows[0] if rows else {})
            return httpx.Response(
                200, json={"data": self.rows[resource], "has_more": self.has_more}
            )

    script = Script()
    native = httpx.AsyncClient
    transport = httpx.MockTransport(script.handle)

    def scripted_client(**kwargs):
        assert kwargs == {"timeout": 15, "follow_redirects": False}
        return native(transport=transport, **kwargs)

    monkeypatch.setattr(provider.httpx, "AsyncClient", scripted_client)
    return script


@pytest.fixture
def connected(stripe_env, stripe_http):
    tested = stripe_env.rpc("stripe.test", api_key=KEY)
    assert "result" in tested, tested
    result = stripe_env.rpc(
        "stripe.connect",
        api_key=KEY,
        challenge_id=tested["result"]["challenge_id"],
        authority_confirmed=True,
    )
    assert result["result"]["status"] == "connected", result
    stripe_http.requests.clear()
    return stripe_env
