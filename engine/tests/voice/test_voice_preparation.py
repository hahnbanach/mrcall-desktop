"""Real headless refresh path with no operator session and automatic processing off."""

import asyncio
import time
from unittest.mock import Mock

import pytest

from tests.voice.m2_fixture import NUMBER, OWNER
from tests.voice.test_agent_config import save
from zylch.auth import refresh, session
from zylch.config import settings
from zylch.services.voice import preparation
from zylch.services.voice.agent_config import snapshot_for_call
from zylch.storage.storage import Storage


@pytest.mark.parametrize("initial", ["missing", "expired", "fresh"])
def test_credits_prepares_without_operator(fixture_db, monkeypatch, initial):
    monkeypatch.delenv("ZYLCH_PROFILE_DIR")
    monkeypatch.setenv("LLM_PROVIDER", "mrcall")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "1")
    monkeypatch.setenv("AUTO_UPDATE_ENABLED", "false")
    save()
    snap = snapshot_for_call(NUMBER)
    session.clear_session()
    if initial != "missing":
        session.set_session(
            OWNER,
            None,
            "old-token",
            int(time.time() * 1000) + (3600000 if initial == "fresh" else -1000),
        )
    store = Mock()
    store.get_firebase_refresh_token.return_value = "isolated-refresh"
    monkeypatch.setattr(Storage, "get_instance", lambda: store)
    monkeypatch.setattr(settings, "firebase_web_api_key", "synthetic-web-key")
    exchange = Mock(
        return_value={
            "id_token": "new-memory-only-id",
            "refresh_token": "rotated-refresh",
            "expires_at_ms": int(time.time() * 1000) + 3600000,
        }
    )
    monkeypatch.setattr(refresh, "exchange_refresh_token", exchange)
    from zylch.llm.bounded_proxy import BoundedProxyClient, PROTOCOL, digest

    def quote(_client, request):
        value = dict(
            protocol=PROTOCOL,
            currency="USD",
            account_id=OWNER,
            business_id="selected-test-business",
            payload_hash=digest(request),
            tariff_version="fixture",
            model=request["model"],
            credit_value_micro_usd=1000,
            max_credits=1,
            max_debit_micro_usd=1000,
        )
        return value | {"quote_hash": digest(value)}

    monkeypatch.setattr(BoundedProxyClient, "quote", quote)
    try:
        client = asyncio.run(preparation.prepare_client(snap))
        assert client.transport == "proxy"
        assert session.get_session().uid == OWNER
        if initial == "fresh":
            exchange.assert_not_called()
        else:
            exchange.assert_called_once_with("isolated-refresh", "synthetic-web-key")
            store.store_firebase_refresh_token.assert_called_once_with(OWNER, "rotated-refresh")
            assert session.get_session().id_token == "new-memory-only-id"
    finally:
        session.clear_session()


@pytest.mark.parametrize("failure", ["refresh", "missing", "wrong_uid", "zero_budget"])
def test_preparation_fails_closed(fixture_db, monkeypatch, failure):
    monkeypatch.delenv("ZYLCH_PROFILE_DIR")
    monkeypatch.setenv("LLM_PROVIDER", "mrcall")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "0" if failure == "zero_budget" else "1")
    save()
    snap = snapshot_for_call(NUMBER)
    session.clear_session()
    store = Mock()
    store.get_firebase_refresh_token.return_value = None if failure == "missing" else "refresh"
    monkeypatch.setattr(Storage, "get_instance", lambda: store)
    monkeypatch.setattr(settings, "firebase_web_api_key", "synthetic-web-key")
    monkeypatch.setattr(
        refresh, "exchange_refresh_token", Mock(side_effect=RuntimeError("synthetic failure"))
    )
    if failure in ("wrong_uid", "zero_budget"):
        session.set_session(
            "wrong" if failure == "wrong_uid" else OWNER,
            None,
            "token",
            int(time.time() * 1000) + 3600000,
        )
    factory = Mock()
    monkeypatch.setattr(preparation, "make_llm_client", factory)
    try:
        with pytest.raises(ValueError, match="preparation unavailable"):
            asyncio.run(preparation.prepare_client(snap))
        factory.assert_not_called()
    finally:
        session.clear_session()


def test_quote_failure_prevents_voice_readiness(fixture_db, monkeypatch):
    monkeypatch.delenv("ZYLCH_PROFILE_DIR")
    monkeypatch.setenv("LLM_PROVIDER", "mrcall")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "1")
    save()
    snap = snapshot_for_call(NUMBER)
    client = Mock(transport="proxy", model="claude-haiku-4-5")
    client._client.quote.side_effect = ValueError("business_id_required")
    monkeypatch.setattr(preparation, "make_llm_client", lambda: client)
    monkeypatch.setattr(preparation, "ensure_fresh_session", lambda _: True)
    session.set_session(OWNER, None, "synthetic-id", int(time.time() * 1000) + 3600000)
    try:
        with pytest.raises(ValueError, match="preparation unavailable"):
            asyncio.run(preparation.prepare_client(snap))
        client._client.execute.assert_not_called()
    finally:
        session.clear_session()
