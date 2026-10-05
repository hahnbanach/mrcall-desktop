"""Disposable split stores and the real RPC path for Qonto lifecycle checks."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from zylch.auth import clear_session, set_session
from zylch.qonto import provider
from zylch.qonto.provider import Account, Organization, Page
from zylch.rpc.dispatch import dispatch_raw
from zylch.storage import database as dbm

UID = "fixtureFirebaseUid"
LOGIN = "fixture-organization-login"
KEY = "fixture-api-key-secret"


@pytest.fixture(autouse=True)
def cleanup_test_data():
    yield


class FixtureProvider:
    def __init__(self):
        self.result = Organization(
            "org-id",
            "Fixture company",
            "Fixture legal company",
            (
                Account("account-eur", "Business account", "EUR"),
                Account("account-gbp", "Second account", "GBP"),
            ),
        )
        self.calls = []
        self.error = None

    async def organization(self, value):
        self.calls.append(value)
        if self.error:
            raise self.error
        return self.result

    async def transactions(self, value, account_id, basis, start, end, page):
        if self.error:
            raise self.error
        return Page((), None, 0, 0)


@dataclass
class Environment:
    directory: Path
    home: Path
    provider: FixtureProvider

    @property
    def credentials(self):
        return {"login": LOGIN, "api_key": KEY}

    def rpc(self, method, **params):
        return asyncio.run(self.arpc(method, **params))

    async def arpc(self, method, **params):
        return await dispatch_raw(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}),
            lambda *_: None,
        )

    def connect(self, **overrides):
        tested = self.rpc("qonto.test", **self.credentials)["result"]
        params = {
            **self.credentials,
            "challenge_id": tested["challenge_id"],
            "account_ids": ["account-eur"],
            "authority_confirmed": True,
            "consent_version": 1,
        }
        params.update(overrides)
        return self.rpc("qonto.connect", **params)


def signin(uid=UID, *, expired=False):
    set_session(
        uid,
        "display@example.test",
        "fixture-id-token",
        int(time.time() * 1000) + (-1000 if expired else 3600000),
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    from zylch import runtime
    from zylch.cli import profiles
    from zylch.llm import budget, client
    import zylch.llm as llm

    home = tmp_path / "engine-home"
    home.mkdir(mode=0o700)
    directory = home / "profiles" / UID
    directory.mkdir(parents=True, mode=0o700)
    (directory / ".env").write_text(f"OWNER_ID={UID}\nEMAIL_ADDRESS=display@example.test\n")
    (directory / ".env").chmod(0o600)
    monkeypatch.setenv("ZYLCH_HOME", str(home))
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(directory))
    monkeypatch.setenv("ZYLCH_DB_PATH", str(directory / "zylch.db"))
    monkeypatch.setenv("OWNER_ID", UID)
    monkeypatch.setenv("EMAIL_ADDRESS", "display@example.test")
    monkeypatch.setenv("MEMORY_KEY", "")
    monkeypatch.setenv("MEMORY_DB_DIR", str(home / "memory"))
    monkeypatch.delenv("QONTO_BOOTSTRAP_ENV_FILE", raising=False)
    monkeypatch.delenv("QONTO_HOST_ID_FILE", raising=False)
    monkeypatch.setattr(runtime, "_serving", False)
    monkeypatch.setattr(profiles, "_active_profile", UID)
    monkeypatch.setattr(profiles, "_active_profile_dir", str(directory))
    monkeypatch.setattr(profiles, "PROFILES_DIR", str(home / "profiles"))
    fixture = FixtureProvider()
    monkeypatch.setattr(provider, "_provider", fixture)
    calls = []

    def no_paid(*args, **kwargs):
        calls.append(1)
        raise AssertionError("Qonto lifecycle must not call a model or reserve budget")

    monkeypatch.setattr(llm, "make_llm_client", no_paid)
    monkeypatch.setattr(client.LLMClient, "create_message_sync", no_paid)
    monkeypatch.setattr(client.LLMClient, "create_message", no_paid)
    monkeypatch.setattr(budget, "reserve", no_paid)
    clear_session()
    signin()
    dbm.dispose_engine()
    dbm.init_db()
    yield Environment(directory, home, fixture)
    assert not calls
    clear_session()
    dbm.dispose_engine()


@pytest.fixture
def http_api(env, monkeypatch):
    import httpx
    from zylch.qonto.amounts import timestamp

    class API:
        def __init__(self):
            self.requests = []
            self.rows = []
            self.callback = None
            self.organization = {
                "id": "org-id",
                "legal_name": "Fixture legal company",
                "name": "Fixture company",
                "bank_accounts": [
                    {
                        "id": "account-eur",
                        "name": "Business account",
                        "currency": "EUR",
                        "balance": "100.43",
                        "balance_cents": 10043,
                        "authorized_balance": "99.00",
                        "authorized_balance_cents": 9900,
                        "updated_at": "2026-10-01T00:00:00Z",
                    },
                    {
                        "id": "account-gbp",
                        "name": "Second account",
                        "currency": "GBP",
                        "balance": "10.00",
                        "balance_cents": 1000,
                        "authorized_balance": "10.00",
                        "authorized_balance_cents": 1000,
                    },
                ],
            }

        async def handle(self, request):
            self.requests.append(request)
            if self.callback:
                answer = self.callback(request)
                if hasattr(answer, "__await__"):
                    answer = await answer
                if answer is not None:
                    return answer
            if request.url.path == "/v2/organization":
                return httpx.Response(200, json={"organization": self.organization})
            query = request.url.params
            basis = query["sort_by"].split(":")[0]
            start, end = timestamp(query[basis + "_from"]), timestamp(query[basis + "_to"])
            rows = [
                row
                for row in self.rows
                if row.get("bank_account_id", "account-eur") == query["bank_account_id"]
                and (row.get(basis) is None or start <= timestamp(row[basis]) <= end)
            ]
            rows.sort(key=lambda row: timestamp(row.get(basis)) or "")
            page = int(query["page"])
            count = len(rows)
            pages = max(1, (count + 99) // 100)
            return httpx.Response(
                200,
                json={
                    "transactions": rows[(page - 1) * 100 : page * 100],
                    "meta": {
                        "current_page": page,
                        "next_page": page + 1 if page < pages else None,
                        "total_pages": pages,
                        "total_count": count,
                        "per_page": 100,
                    },
                },
            )

    api = API()
    monkeypatch.setattr(
        provider, "_provider", provider.QontoProvider(transport=httpx.MockTransport(api.handle))
    )
    return api
