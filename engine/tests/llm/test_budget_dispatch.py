"""Paid dispatch admission exercised through the actual client and RPC."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zylch.llm.budget import BudgetError, budget_snapshot
from zylch.llm.client import LLMClient
from zylch.storage import database


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.setenv("OWNER_ID", "uid-test")
    monkeypatch.setenv("EMAIL_ADDRESS", "display@example.test")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    database.dispose_engine()
    from zylch.storage.models import LlmReservation, LlmUsage

    database.Base.metadata.create_all(
        database.get_engine(), tables=[LlmUsage.__table__, LlmReservation.__table__]
    )
    yield
    database.dispose_engine()


def client(result=None, error=None):
    c = LLMClient(transport="direct", api_key="fake", model="claude-haiku-4-5")
    c._client.messages.create = Mock(
        side_effect=error,
        return_value=result
        or SimpleNamespace(
            content=[],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=20, output_tokens=3),
        ),
    )
    return c


ARGS = {"messages": [{"role": "user", "content": "label this"}], "max_tokens": 32}


def test_zero_budget_makes_no_upstream_attempt(monkeypatch):
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "0")
    c = client()
    with pytest.raises(BudgetError):
        c.create_message_sync(**ARGS)
    c._client.messages.create.assert_not_called()


def test_sdk_automatic_retries_disabled():
    c = client()
    assert c._client.max_retries == 0


def test_async_dispatch_carries_tag_and_atomic_accounting():
    from zylch.llm.usage import call_site
    from zylch.rpc.usage_queries import usage_today

    c = client()
    with call_site("memory.test"):
        asyncio.run(c.create_message(**ARGS))
    assert c._client.messages.create.call_count == 1
    assert c._client.messages.create.call_args.kwargs["service_tier"] == "standard_only"
    snapshot = asyncio.run(usage_today({}, lambda *args: None))
    assert snapshot["spent_usd"] > 0
    assert snapshot["reserved_usd"] == 0
    assert snapshot["calls_today"] == 1
    assert snapshot["by_site"]["memory.test"]["calls"] == 1


def test_timeout_keeps_money_reserved_and_never_retries():
    c = client(error=TimeoutError("unknown upstream outcome"))
    with pytest.raises(TimeoutError):
        c.create_message_sync(**ARGS)
    assert c._client.messages.create.call_count == 1
    assert budget_snapshot("uid-test")["reserved_usd"] > 0


def test_missing_usage_is_not_settled_as_zero():
    c = client(result=SimpleNamespace(content=[], stop_reason="end_turn", usage=None))
    with pytest.raises(BudgetError):
        c.create_message_sync(**ARGS)
    state = budget_snapshot("uid-test")
    assert state["reserved_usd"] > 0 and state["spent_usd"] == 0


def test_unpriced_kwargs_cannot_override_request_bound():
    c = client()
    with pytest.raises(BudgetError):
        c.create_message_sync(**ARGS, extra_body={"max_tokens": 999999})
    c._client.messages.create.assert_not_called()


def test_compaction_cannot_bypass_paused_account(monkeypatch):
    from zylch import llm
    from zylch.services.chat_compaction import _summarize

    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "0")
    c = client()
    monkeypatch.setattr(llm, "make_llm_client", lambda **kw: c)
    with pytest.raises(BudgetError):
        asyncio.run(_summarize("conversation"))
    c._client.messages.create.assert_not_called()


def test_usage_rpc_explains_unpriced_credit_mode(monkeypatch):
    from zylch.llm import client as client_module
    from zylch.rpc.usage_queries import usage_today
    monkeypatch.setattr(client_module, "_read_profile_anthropic_key", lambda: None)
    snapshot = asyncio.run(usage_today({}, lambda *args: None))
    assert snapshot["billing_supported"] is False
    assert snapshot["paused"] is True
    assert snapshot["remaining_usd"] == 5
