"""Production admission accepts only one exact owner-scoped StarChat row."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from zylch.services.voice import business_binding as binding


EXPECTED = binding.ExpectedBusiness("business-1", "immutable-uid", "+390250552776")
ROW = {
    "businessId": EXPECTED.business_id,
    "owner": EXPECTED.owner_uid,
    "serviceNumber": EXPECTED.called_number,
    "template": "starter",
    "version": 9,
}


class Response:
    def __init__(self, rows):
        self.rows = rows

    def raise_for_status(self):
        return None

    def json(self):
        return self.rows


class Http:
    def __init__(self, rows):
        self.rows = rows
        self.request = None
        self.calls = 0

    async def post(self, endpoint, *, json):
        self.request = (endpoint, json)
        index = self.calls
        self.calls += 1
        rows = self.rows[index] if isinstance(self.rows, tuple) else self.rows
        return Response(rows)

    async def aclose(self):
        return None


def run(monkeypatch, rows, *, uid=EXPECTED.owner_uid, fresh=True, expired=False,
        previous_version=None, token_subject=EXPECTED.owner_uid):
    http = Http(rows)
    captured = {}
    monkeypatch.setattr(binding, "ensure_fresh_session", lambda _: fresh)
    monkeypatch.setattr(binding, "verify_firebase_id_token", lambda _: {"sub": token_subject})
    monkeypatch.setattr(
        binding,
        "require_session",
        lambda: SimpleNamespace(uid=uid, id_token="checked-token", is_expired=lambda: expired),
    )
    def client(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(realm="mrcall0", client=http)
    monkeypatch.setattr(binding, "StarChatClient", client)
    return http, captured, asyncio.run(binding.verify_business(EXPECTED, previous_version))


def test_exact_binding_and_version(monkeypatch):
    http, captured, result = run(monkeypatch, [ROW])
    assert result.version == 9
    assert captured["jwt_token"] == "checked-token"
    assert captured["owner_id"] == EXPECTED.owner_uid
    assert http.request == (
        "/mrcall/v1/mrcall0/crm/business/search",
        {"businessId": EXPECTED.business_id, "offset": 0, "limit": 100},
    )


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [ROW, ROW],
        [{**ROW, "businessId": "other"}],
        [{**ROW, "owner": "other"}],
        [{**ROW, "serviceNumber": "+390250552775"}],
        [{**ROW, "template": "desktop"}],
        [{**ROW, "version": "9"}],
    ],
)
def test_missing_ambiguous_or_changed_binding_refused(monkeypatch, rows):
    with pytest.raises(ValueError, match="Voice business binding unavailable"):
        run(monkeypatch, rows)


def test_unrelated_version_change_revalidates_fields(monkeypatch):
    http, _, result = run(monkeypatch, ([{**ROW, "version": 10}], [{**ROW, "version": 10}]), previous_version=9)
    assert result.version == 10
    assert http.calls == 2


def test_changed_version_with_changed_binding_refused(monkeypatch):
    with pytest.raises(ValueError, match="Voice business binding unavailable"):
        run(monkeypatch, ([{**ROW, "version": 10}], [{**ROW, "version": 10, "owner": "other"}]), previous_version=9)


def test_changing_version_during_stable_read_refused(monkeypatch):
    with pytest.raises(ValueError, match="Voice business binding unavailable"):
        run(monkeypatch, ([{**ROW, "version": 10}], [{**ROW, "version": 11}]), previous_version=9)


@pytest.mark.parametrize("uid,fresh", [("other", True), (EXPECTED.owner_uid, False)])
def test_headless_owner_failure_refused(monkeypatch, uid, fresh):
    with pytest.raises(ValueError, match="Voice business binding unavailable"):
        run(monkeypatch, [ROW], uid=uid, fresh=fresh)


def test_expired_session_refused(monkeypatch):
    with pytest.raises(ValueError, match="Voice business binding unavailable"):
        run(monkeypatch, [ROW], expired=True)


def test_misbound_refreshed_token_refused(monkeypatch):
    with pytest.raises(ValueError, match="Voice business binding unavailable"):
        run(monkeypatch, [ROW], token_subject="different-firebase-owner")


def test_refresh_timeout_refused(monkeypatch):
    original_timeout = asyncio.timeout
    monkeypatch.setattr(binding.asyncio, "timeout", lambda _: original_timeout(0.001))
    monkeypatch.setattr(binding, "ensure_fresh_session", lambda _: time.sleep(0.05))
    with pytest.raises(ValueError, match="Voice business binding unavailable"):
        asyncio.run(binding.verify_business(EXPECTED))
