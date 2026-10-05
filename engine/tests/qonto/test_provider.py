"""Real RPC dispatch through an injected fixed HTTP transport."""

import asyncio
import ssl

import httpx
import pytest

from zylch.qonto import provider
from zylch.qonto.bootstrap import Credentials
from zylch.qonto.errors import QontoError
from zylch.qonto.models import QontoAccount
from zylch.qonto.repository import profile_transaction


@pytest.mark.parametrize(
    "code,outcome",
    [
        (302, "invalid_response"),
        (401, "auth"),
        (403, "auth"),
        (429, "rate_limited"),
        (503, "network"),
        (400, "invalid_response"),
    ],
)
def test_safe_http_errors(env, http_api, code, outcome):
    http_api.callback = lambda request: httpx.Response(
        code,
        headers={"Location": "https://untrusted.test/secret"},
        text="provider-private-bank-payload",
    )
    result = env.rpc("qonto.test", **env.credentials)
    assert result["error"]["message"].split(":", 1)[0] == outcome
    assert "provider-private-bank-payload" not in str(result)
    assert len(http_api.requests) == 1


def test_fixed_get_literal_authorization_and_no_url_override(env, http_api, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://invalid.test:1234")
    monkeypatch.setenv("QONTO_API_URL", "https://invalid.test")
    result = env.rpc("qonto.test", **env.credentials)
    assert "result" in result
    request = http_api.requests[0]
    assert str(request.url) == "https://thirdparty.qonto.com/v2/organization"
    assert request.method == "GET"
    assert (
        request.headers["authorization"]
        == env.credentials["login"] + ":" + env.credentials["api_key"]
    )
    with pytest.raises(QontoError):
        asyncio.run(
            provider.get_provider()._get("https://evil.test", Credentials("fixture", "fixture"))
        )
    assert len(http_api.requests) == 1
    assert (
        env.rpc("qonto.test", **env.credentials, url="https://evil.test")["error"]["code"] == -32602
    )


def test_balance_changes_do_not_invalidate_challenge(env, http_api):
    tested = env.rpc("qonto.test", **env.credentials)["result"]
    http_api.organization["bank_accounts"][0].update(balance="101.00", balance_cents=10100)
    result = env.rpc(
        "qonto.connect",
        **env.credentials,
        challenge_id=tested["challenge_id"],
        account_ids=["account-eur"],
        authority_confirmed=True,
        consent_version=1,
    )
    assert result["result"]["initial_sync"]["status"] == "completed"
    with profile_transaction() as session:
        account = session.query(QontoAccount).filter_by(account_id="account-eur").one()
        assert account.balance_minor == 10100 and account.authorized_balance_minor == 9900
        assert account.balance_provider_at == "2026-10-01T00:00:00.000000Z"
        assert account.balance_retrieved_at
    requests = [
        request for request in http_api.requests if request.url.path.endswith("transactions")
    ]
    assert len(requests) == 30
    for request in requests:
        assert request.url.params.get_list("status[]") == [
            "pending",
            "completed",
            "declined",
            "reversed",
        ]
        assert request.url.params["per_page"] == "100"
        assert request.url.params["bank_account_id"] == "account-eur"
        assert request.url.params["sort_by"] == "emitted_at:asc"


@pytest.mark.parametrize(
    "failure,outcome",
    [
        (httpx.ConnectError("secret"), "network"),
        (httpx.ReadTimeout("secret"), "network"),
        (ssl.SSLCertVerificationError("secret"), "tls"),
    ],
)
def test_network_tls_classification(env, http_api, failure, outcome):
    def fail(request):
        if isinstance(failure, ssl.SSLError):
            try:
                raise failure
            except ssl.SSLError as exc:
                raise httpx.ConnectError("secret") from exc
        raise failure

    http_api.callback = fail
    result = env.rpc("qonto.test", **env.credentials)
    assert result["error"]["message"].split(":", 1)[0] == outcome
    assert "secret" not in str(result)


@pytest.mark.parametrize(
    "body",
    [b"not-json", b'{"organization": NaN}', b"x" * (provider.MAX_BYTES + 1)],
    ids=["malformed", "nonfinite", "oversize"],
)
def test_response_caps_and_invalid_json(env, http_api, body):
    http_api.callback = lambda request: httpx.Response(200, content=body)
    assert (
        env.rpc("qonto.test", **env.credentials)["error"]["message"].split(":", 1)[0]
        == "invalid_response"
    )


def test_finite_retry_after():
    assert provider.retry_after("999999999999999999999999") == 86400
    assert provider.retry_after("invalid-private-value") == 30
    assert provider.retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 1


def test_cross_process_sync_lease_and_disconnect_fence(env, http_api):
    import json
    import subprocess
    import sys
    import time
    from .conftest import UID
    from zylch.qonto.models import QontoTransaction

    assert env.connect()["result"]["ok"]
    entered = env.directory / "fixture-sync-entered"
    release = env.directory / "fixture-sync-release"
    organization = env.directory / "fixture-organization.json"
    organization.write_text(json.dumps(http_api.organization))
    organization.chmod(0o600)
    script = """
import asyncio,json,sys,time
from pathlib import Path
import httpx
from zylch.auth import set_session
from zylch.qonto import provider
from zylch.rpc.dispatch import dispatch_raw
from zylch.storage.database import init_db
init_db()
set_session(sys.argv[1],None,'fixture-token',int(time.time()*1000)+100000)
async def handle(request):
    if request.url.path.endswith('organization'):
        return httpx.Response(200,json={'organization':json.loads(Path(sys.argv[4]).read_text())})
    Path(sys.argv[2]).touch(mode=0o600)
    while not Path(sys.argv[3]).exists():
        await asyncio.sleep(0.01)
    return httpx.Response(200,json={'transactions':[], 'meta':{'current_page':1,'next_page':None,'total_pages':1,'total_count':0,'per_page':100}})
provider._provider=provider.QontoProvider(transport=httpx.MockTransport(handle))
async def main():
    result=await dispatch_raw(json.dumps({'jsonrpc':'2.0','id':1,'method':'qonto.sync','params':{}}),lambda *_:None)
    print(json.dumps(result))
asyncio.run(main())
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, UID, str(entered), str(release), str(organization)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while not entered.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert entered.exists()
        assert env.rpc("qonto.sync")["error"]["message"].startswith("busy:")
        assert env.rpc("qonto.disconnect")["result"]["status"] == "disconnected"
        release.touch(mode=0o600)
        output, error = process.communicate(timeout=15)
        assert process.returncode == 0, error
        assert json.loads(output)["error"]["message"].startswith("generation_changed:")
        with profile_transaction() as session:
            assert session.query(QontoTransaction).count() == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def test_request_overall_timeout_has_safe_rpc_outcome(env, http_api, monkeypatch):
    async def blocked(request):
        await asyncio.sleep(2)

    http_api.callback = blocked
    monkeypatch.setattr(provider, "REQUEST_SECONDS", 0.01)
    assert env.rpc("qonto.test", **env.credentials)["error"]["message"].startswith("network:")


def test_provider_payload_never_appears_in_rpc_logs(env, http_api, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    http_api.organization["legal_name"] = "private-fixture-company-name"
    result = env.connect()
    assert result["result"]["ok"]
    assert "private-fixture-company-name" not in caplog.text
    assert env.credentials["login"] not in caplog.text
    assert env.credentials["api_key"] not in caplog.text


def test_http_client_security_options_used_by_real_rpc(env, http_api, monkeypatch):
    original = httpx.AsyncClient
    options = []

    def client(**kwargs):
        options.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    assert env.rpc("qonto.test", **env.credentials)["result"]["ok"]
    assert options[0]["verify"] is True
    assert options[0]["trust_env"] is False
    assert options[0]["follow_redirects"] is False
    assert options[0]["timeout"].connect == 5
    assert options[0]["timeout"].read == 15
