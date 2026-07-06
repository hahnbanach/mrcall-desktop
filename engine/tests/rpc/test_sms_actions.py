"""Regression tests for the Settings SMS-sender RPC (`rpc/sms_actions.py`).

The bug: `sms.get_sender` / `sms.set_sender` never forwarded the profile
`SMS_BUSINESS_ID`, so for an admin / multi-assistant Firebase token
(support@ is a reseller token that sees EVERY business) mrcall-agent's
`resolve_business_id` refused to guess and returned **400
business_id_required** — breaking every Settings save. See the live
reproduction in the meta-repo execution plan.

We mock mrcall-agent with `httpx.MockTransport` (same convention as
`tests/llm/test_proxy_client.py`) and assert the outgoing request carries
`business_id` on the GET query string and in the PUT body. Async handlers
are driven with `asyncio.run`, matching the sync-test style of the suite.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from zylch.auth import session as sessmod
from zylch.rpc import sms_actions

_FAR_FUTURE_MS = 10_000_000_000_000  # year ~2286
_BID = "70060cbc-f7fa-35a4-b557-232eaaa9836d"


@pytest.fixture
def _session():
    sessmod.set_session(uid="u", email=None, id_token="tok", expires_at_ms=_FAR_FUTURE_MS)
    yield
    sessmod.clear_session()


@pytest.fixture
def _patch_httpx(monkeypatch):
    """Patch `httpx.AsyncClient` in sms_actions to record outgoing requests."""
    captured: list[httpx.Request] = []
    payload = {"sender": "MrCall", "business_id": _BID}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=payload)

    real_async_client = httpx.AsyncClient  # bind before patching to avoid recursion

    def _factory(*_a, **kw):
        kw.pop("transport", None)
        return real_async_client(transport=httpx.MockTransport(_handler), **kw)

    monkeypatch.setattr(sms_actions.httpx, "AsyncClient", _factory)
    return captured


def test_get_sender_forwards_business_id(monkeypatch, _session, _patch_httpx):
    monkeypatch.setenv("SMS_BUSINESS_ID", _BID)
    res = asyncio.run(sms_actions.sms_get_sender({}, lambda *a, **k: None))
    assert res["business_id"] == _BID
    # The 400 that broke Settings save is triggered by an ABSENT business_id;
    # it must ride on the query string for the GET.
    assert _patch_httpx[-1].url.params.get("business_id") == _BID


def test_set_sender_forwards_business_id(monkeypatch, _session, _patch_httpx):
    monkeypatch.setenv("SMS_BUSINESS_ID", _BID)
    res = asyncio.run(sms_actions.sms_set_sender({"sender": "MrCall"}, lambda *a, **k: None))
    assert res["business_id"] == _BID
    body = json.loads(_patch_httpx[-1].content.decode())
    assert body["sender"] == "MrCall"
    assert body["business_id"] == _BID


def test_business_id_omitted_when_unset(monkeypatch, _session, _patch_httpx):
    # Single-business owners have no SMS_BUSINESS_ID; the key must then be
    # OMITTED (not sent empty) so the server uses their sole visible business.
    monkeypatch.delenv("SMS_BUSINESS_ID", raising=False)
    asyncio.run(sms_actions.sms_get_sender({}, lambda *a, **k: None))
    assert "business_id" not in _patch_httpx[-1].url.params

    asyncio.run(sms_actions.sms_set_sender({"sender": "MrCall"}, lambda *a, **k: None))
    assert "business_id" not in json.loads(_patch_httpx[-1].content.decode())


def test_blank_business_id_is_omitted(monkeypatch, _session, _patch_httpx):
    # A whitespace-only SMS_BUSINESS_ID must be treated as unset, never sent.
    monkeypatch.setenv("SMS_BUSINESS_ID", "   ")
    asyncio.run(sms_actions.sms_get_sender({}, lambda *a, **k: None))
    assert "business_id" not in _patch_httpx[-1].url.params
