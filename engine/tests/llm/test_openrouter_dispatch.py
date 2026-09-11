"""Actual HTTP adapter and durable ledger, without network or provider charges."""
import json

import httpx
import pytest

from zylch.llm.budget import BudgetError, budget_snapshot
from zylch.llm.client import LLMClient
from zylch.llm.openrouter_client import OpenRouterClient
from zylch.llm.openrouter_pricing import MODEL
from zylch.storage import database
from zylch.storage.models import LlmReservation, LlmUsage


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.setenv("OWNER_ID", "immutable-test-uid")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    database.dispose_engine()
    database.Base.metadata.create_all(database.get_engine(),
                                     tables=[LlmReservation.__table__, LlmUsage.__table__])
    yield
    database.dispose_engine()


def client(handler):
    c = LLMClient("openrouter", api_key="fake-test-key", model=MODEL)
    c._client = OpenRouterClient(api_key="fake-test-key", http_client=httpx.Client(
        transport=httpx.MockTransport(handler)))
    return c


def response(cost=0.00002):
    return httpx.Response(200, json={"id": "response-test", "model": MODEL,
        "content": [{"type": "text", "text": "SKIP"}], "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 2, "cost": cost}})


ARGS = {"messages": [{"role": "user", "content": "test fixture"}], "max_tokens": 20}


def test_real_adapter_reserves_before_http_and_settles_receipt(ledger):
    calls = []
    def upstream(req):
        assert budget_snapshot("uid")["reserved_usd"] > 0
        body = json.loads(req.content)
        assert body["provider"]["allow_fallbacks"] is False
        assert body["provider"]["max_price"]["request"] == "0"
        assert body["thinking"] == {"type": "disabled"}
        assert req.headers["Authorization"] == "Bearer fake-test-key"
        calls.append(body)
        return response()
    result = client(upstream).create_message_sync(**ARGS)
    assert result.content[0].text == "SKIP"
    assert len(calls) == 1
    state = budget_snapshot("uid")
    assert state["spent_usd"] == 0.00002
    assert state["reserved_usd"] == 0


def test_zero_allowance_never_reaches_http(ledger, monkeypatch):
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "0")
    def forbidden(req):
        pytest.fail("paid dispatch while paused")
    with pytest.raises(BudgetError):
        client(forbidden).create_message_sync(**ARGS)


def test_missing_receipt_keeps_hold(ledger):
    with pytest.raises(BudgetError):
        client(lambda req: response(None)).create_message_sync(**ARGS)
    assert budget_snapshot("uid")["reserved_usd"] > 0


def test_breach_persists_and_stops_following_calls(ledger):
    calls = []
    def upstream(req):
        calls.append(req)
        return response(1)
    c = client(upstream)
    with pytest.raises(BudgetError):
        c.create_message_sync(**ARGS)
    with pytest.raises(BudgetError):
        c.create_message_sync(**ARGS)
    assert len(calls) == 1
    assert budget_snapshot("uid")["pricing_fault"] is True


def test_documented_nullable_cache_usage_and_public_counters(ledger):
    def upstream(req):
        result = response()
        data = result.json()
        data['usage'].update(cache_creation_input_tokens=None, cache_read_input_tokens=None)
        return httpx.Response(200, json=data)
    result = client(upstream).create_message_sync(**ARGS)
    assert result.usage['input_tokens'] == 10
    assert result.usage['output_tokens'] == 2
    assert result.usage['cache_creation_input_tokens'] == 0
    assert budget_snapshot('uid')['reserved_usd'] == 0


def test_saved_policy_change_refuses_existing_client(ledger, tmp_path, monkeypatch):
    from zylch.llm.client import make_llm_client
    profile = tmp_path / 'profile'
    profile.mkdir()
    env = profile / '.env'
    env.write_text('LLM_PROVIDER=openrouter\nOPENROUTER_API_KEY=fake\nLLM_DAILY_BUDGET_USD=5\n')
    monkeypatch.setenv('ZYLCH_PROFILE_DIR', str(profile))
    c = make_llm_client()
    def forbidden(req):
        pytest.fail('stale client dispatched')
    c._client = OpenRouterClient(api_key='fake', http_client=httpx.Client(transport=httpx.MockTransport(forbidden)))
    env.write_text(env.read_text() + 'LLM_MODEL_PRESET=balanced\n')
    with pytest.raises(BudgetError, match='settings changed'):
        c.create_message_sync(**ARGS)
    assert budget_snapshot('uid')['reserved_usd'] == 0
