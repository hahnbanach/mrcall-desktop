"""Native Stripe authority, revocation, encryption and HTTP refusal journeys."""

import asyncio
import json
import logging
import time
from dataclasses import replace

import httpx
import pytest

from tests.stripe.conftest import KEY
from zylch.auth import clear_session, get_session, set_session
from zylch.rpc import methods
from zylch.stripe import connection, identity, provider

NAMES = {
    "status",
    "test",
    "connect",
    "disconnect",
    "customers",
    "payments",
    "invoices",
    "subscriptions",
    "detail",
}


def refused(value, outcome):
    assert value["error"]["code"] == -32045, value
    assert value["error"]["message"].startswith(outcome + ":"), value


def test_discovery_all_nine_methods_and_encrypted_roundtrip(connected, stripe_http):
    env = connected
    assert {
        name.removeprefix("stripe.") for name in methods.METHODS if name.startswith("stripe.")
    } == NAMES
    caps = env.rpc("system.capabilities")["result"]
    assert caps["stripe"] == caps["contextual_email_policy"] == 1
    status = env.rpc("stripe.status")["result"]
    assert status["account"]["id"] == "acct_fixture" and status["generation"] == 1
    for resource in ("customers", "payments", "invoices", "subscriptions"):
        result = env.rpc("stripe." + resource, limit=1)["result"]
        assert result["coverage"] == "bounded_page" and len(result["data"]) == 1
    detail = env.rpc("stripe.detail", resource="customers", id="cus_fixture")["result"]
    assert detail["coverage"] == "single_record" and detail["data"]["id"] == "cus_fixture"
    actor = connection.authority()
    encrypted = (env.directory / "stripe.connection").read_bytes()
    assert KEY.encode() not in encrypted
    assert (env.directory / "stripe.connection").stat().st_mode & 0o777 == 0o600
    assert connection._read(actor)["api_key"] == KEY
    disconnected = env.rpc("stripe.disconnect")["result"]
    assert disconnected == {"status": "disconnected", "generation": 2, "capabilities": []}
    assert "api_key" not in connection._read(actor)
    refused(env.rpc("stripe.customers"), "not_connected")
    assert all(r.method == "GET" and r.url.host == "api.stripe.com" for r in stripe_http.requests)


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "expired",
        "foreign-session",
        "foreign-profile",
        "joining",
        "foreign-company",
        "foreign-host",
    ],
)
def test_engine_derived_authority_refusals(stripe_env, stripe_http, monkeypatch, fault):
    env = stripe_env
    if fault == "missing":
        clear_session()
    elif fault == "expired":
        set_session("alice", "alice@example.test", "fixture", int(time.time() * 1000) - 1000)
    elif fault == "foreign-session":
        set_session("bob", "alice@example.test", "fixture", int(time.time() * 1000) + 60000)
    elif fault == "foreign-profile":
        monkeypatch.setenv("OWNER_ID", "bob")
    elif fault == "joining":
        path = env.directory / ".env"
        path.write_text(path.read_text() + "MEMORY_JOIN_TO=other\n")
    elif fault == "foreign-company":
        from zylch.memory.company_key import mint_key

        monkeypatch.setenv("MEMORY_KEY", mint_key())
    else:
        from zylch import runtime

        monkeypatch.setattr(runtime, "_serving", True)
        monkeypatch.setenv("STRIPE_HOST_ID_FILE", str(env.directory / "host-id"))
    result = env.rpc("stripe.status")
    assert result["error"]["code"] == -32045, result
    assert stripe_http.requests == []


@pytest.mark.parametrize(
    "fault",
    ["consent", "expiry", "key", "reuse", "generation", "account", "session", "company", "host"],
)
def test_challenge_is_single_use_and_fenced(stripe_env, stripe_http, monkeypatch, fault):
    env = stripe_env
    tested = env.rpc("stripe.test", api_key=KEY)["result"]
    params = dict(api_key=KEY, challenge_id=tested["challenge_id"], authority_confirmed=True)
    if fault == "consent":
        params["authority_confirmed"] = False
    elif fault == "expiry":
        connection._challenges[tested["challenge_id"]]["expiry"] = time.time() - 1
    elif fault == "key":
        params["api_key"] = "rk_test_DifferentDisposableSecret"
    elif fault == "reuse":
        assert env.rpc("stripe.connect", **params)["result"]["status"] == "connected"
    elif fault == "generation":
        env.rpc("stripe.disconnect")
    elif fault == "account":
        stripe_http.account["id"] = "acct_other"
    elif fault == "session":
        set_session("alice", "alice@example.test", "new", int(time.time() * 1000) + 60000)
    elif fault in {"company", "host"}:
        actor = connection.authority()
        monkeypatch.setattr(
            identity,
            "current_authority",
            lambda: replace(
                actor,
                **({"company_scope": "other"} if fault == "company" else {"host_id": "other"}),
            ),
        )
        monkeypatch.setattr(connection, "current_authority", identity.current_authority)
    assert "error" in env.rpc("stripe.connect", **params)
    if fault != "reuse":
        assert env.rpc("stripe.status").get("result", {}).get("status") != "connected"


@pytest.mark.parametrize(
    "fault", ["disconnect", "generation", "account", "company", "host", "session"]
)
def test_inflight_read_rechecks_all_bindings(connected, stripe_http, monkeypatch, fault):
    env = connected
    actor = connection.authority()

    def during(request):
        if request.url.path == "/v1/customers":
            if fault == "disconnect":
                connection.disconnect()
            elif fault == "generation":
                row = connection._read(actor)
                row["generation"] += 1
                connection._write(actor, row)
            elif fault in {"company", "host"}:
                monkeypatch.setattr(
                    connection,
                    "current_authority",
                    lambda: replace(
                        actor,
                        **(
                            {"company_scope": "changed"}
                            if fault == "company"
                            else {"host_id": "changed"}
                        ),
                    ),
                )
            elif fault == "session":
                clear_session()
        if request.url.path == "/v1/account" and fault == "account":
            return httpx.Response(200, json={"id": "acct_changed"})

    stripe_http.callback = during
    assert "error" in env.rpc("stripe.customers")


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 51},
        {"limit": True},
        {"starting_after": "https://evil.test"},
        {"email": "bad"},
        {"url": "https://evil.test"},
    ],
)
def test_bad_page_and_identifier_refused_before_http(connected, stripe_http, params):
    assert "error" in connected.rpc("stripe.customers", **params)
    assert stripe_http.requests == []


@pytest.mark.parametrize(
    "fault", ["oversized-page", "has-more-empty", "bad-mode", "bad-id", "bad-amount", "bad-json"]
)
def test_malformed_provider_response_refuses_disclosure(connected, stripe_http, fault):
    if fault == "oversized-page":
        stripe_http.rows["customers"] *= 2
    elif fault == "has-more-empty":
        stripe_http.rows["customers"] = []
        stripe_http.has_more = True
    elif fault == "bad-mode":
        stripe_http.rows["customers"][0]["livemode"] = True
    elif fault == "bad-id":
        stripe_http.rows["customers"][0]["id"] = "https://evil.test"
    elif fault == "bad-amount":
        stripe_http.rows["customers"][0]["amount"] = True
    else:
        stripe_http.callback = lambda request: (
            httpx.Response(200, content=b"not-json")
            if request.url.path == "/v1/customers"
            else None
        )
    assert "error" in connected.rpc("stripe.customers", limit=1)


@pytest.mark.parametrize(
    "status,outcome",
    [
        (401, "auth"),
        (403, "permission"),
        (429, "rate_limited"),
        (404, "not_found"),
        (502, "network"),
    ],
)
def test_http_failure_is_safe_and_auth_revokes(connected, stripe_http, status, outcome, caplog):
    stripe_http.callback = lambda request: httpx.Response(status, text=KEY + " private customer")
    with caplog.at_level(logging.DEBUG):
        refused(connected.rpc("stripe.customers"), outcome)
    assert KEY not in caplog.text and "private customer" not in caplog.text
    if status in (401, 403):
        assert connected.rpc("stripe.status")["result"]["status"] == "revoked"
    if status == 429:
        assert len(stripe_http.requests) == 2


def test_blocked_write_unknown_method_and_private_errors(
    connected, stripe_http, monkeypatch, caplog
):
    for name in ("stripe.refund", "stripe.charge", "stripe.unknown"):
        assert connected.rpc(name, api_key=KEY)["error"]["code"] == -32601
    assert not stripe_http.requests

    async def explode(*args, **kwargs):
        raise RuntimeError(KEY + " customer-private")

    monkeypatch.setattr(provider, "get", explode)
    with caplog.at_level(logging.DEBUG):
        result = connected.rpc("stripe.customers", email="private@example.test")
    assert result["error"]["message"] == "Stripe operation failed"
    assert KEY not in json.dumps(result) + caplog.text
    assert "private@example.test" not in caplog.text


@pytest.mark.parametrize(
    "key",
    ["sk_live_RefusedWriteCapable", "rk_test_short", "https://evil.test", "rk_live_bad/value"],
)
def test_invalid_and_unrestricted_keys_never_reach_transport(stripe_env, stripe_http, key):
    refused(stripe_env.rpc("stripe.test", api_key=key), "invalid_key")
    assert stripe_http.requests == []


def test_duplicate_registration_refuses_in_actual_module_execution(monkeypatch):
    import runpy
    from zylch.rpc import stripe

    with monkeypatch.context() as patch:
        patch.setattr(stripe, "METHODS", {"system.capabilities": object()})
        with pytest.raises(RuntimeError, match="duplicate RPC method registration"):
            runpy.run_path(methods.__file__, run_name="__stripe_duplicate_registration_test__")


def test_hosted_encryption_uses_protected_key_and_wrong_key_refuses(
    stripe_env, stripe_http, monkeypatch
):
    import uuid
    from cryptography.fernet import Fernet
    from zylch import runtime

    host = stripe_env.home / "protected-host-id"
    host.write_text(str(uuid.uuid4()))
    host.chmod(0o600)
    secret = Fernet.generate_key()
    monkeypatch.setattr(runtime, "_serving", True)
    monkeypatch.setenv("STRIPE_HOST_ID_FILE", str(host))
    monkeypatch.setenv("ENCRYPTION_KEY", secret.decode())
    tested = stripe_env.rpc("stripe.test", api_key=KEY)["result"]
    result = stripe_env.rpc(
        "stripe.connect",
        api_key=KEY,
        challenge_id=tested["challenge_id"],
        authority_confirmed=True,
    )
    assert result["result"]["status"] == "connected"
    assert not (stripe_env.directory / "stripe.key").exists()
    raw = (stripe_env.directory / "stripe.connection").read_bytes()
    assert json.loads(Fernet(secret).decrypt(raw))["api_key"] == KEY
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    refused(stripe_env.rpc("stripe.status"), "credentials_unreadable")


def test_pagination_is_one_bounded_page_and_cursor_only(connected, stripe_http):
    stripe_http.has_more = True
    result = connected.rpc(
        "stripe.customers",
        limit=1,
        starting_after="cus_previous",
    )["result"]
    assert result["coverage"] == "bounded_page" and result["has_more"]
    assert result["next_cursor"] == "cus_fixture"
    assert len(stripe_http.requests) == 2
    query = stripe_http.requests[-1].url.params
    assert query["limit"] == "1" and query["starting_after"] == "cus_previous"
