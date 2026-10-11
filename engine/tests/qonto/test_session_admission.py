"""Signed-session admission at real RPC, WS and headless refresh boundaries."""

import asyncio
import json
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from zylch.auth import clear_session, get_session, set_session
from zylch.auth import refresh
from zylch.config import settings
from zylch.rpc import firebase_auth, server_ws
from zylch.storage.storage import Storage

from .conftest import UID


@pytest.fixture
def signer(env, monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        firebase_auth, "_fetch_google_certs", lambda **_: {"fixture-key": private.public_key()}
    )

    def token(uid=UID, expiry=None):
        now = int(time.time())
        claims = {
            "sub": uid,
            "email": "signed@example.test",
            "iat": now - 60,
            "exp": expiry or now + 3600,
            "aud": settings.firebase_project_id,
            "iss": f"https://securetoken.google.com/{settings.firebase_project_id}",
        }
        return jwt.encode(claims, private, algorithm="RS256", headers={"kid": "fixture-key"})

    return token


@pytest.mark.parametrize("method", ["account.set_firebase_token", "auth.refresh"])
def test_forged_token_cannot_install_or_extend_session(env, signer, method):
    clear_session()
    params = {"id_token": "not-a-jwt"}
    if method == "account.set_firebase_token":
        params.update(uid=UID, expires_at_ms=2**53, email="untrusted@example.test")
    response = env.rpc(method, **params)
    assert response["error"]["code"] == -32011
    assert get_session() is None
    assert "error" in env.rpc("qonto.test", **env.credentials)
    assert not env.provider.calls


@pytest.mark.parametrize("method", ["account.set_firebase_token", "auth.refresh"])
def test_verified_other_uid_cannot_replace_selected_profile(env, signer, method):
    original = get_session()
    params = {"id_token": signer("otherFirebaseUid")}
    if method == "account.set_firebase_token":
        params.update(uid="otherFirebaseUid", expires_at_ms=2**53)
    assert env.rpc(method, **params)["error"]["code"] == -32011
    assert get_session() is original


def test_client_expiry_and_email_are_replaced_by_signed_claims(env, signer):
    expiry = int(time.time()) + 3600
    response = env.rpc(
        "account.set_firebase_token",
        uid=UID,
        id_token=signer(expiry=expiry),
        expires_at_ms=2**53,
        email="untrusted@example.test",
    )
    assert response["result"]["ok"]
    session = get_session()
    assert session.uid == UID
    assert session.expires_at_ms == expiry * 1000
    assert session.email == "signed@example.test"


def test_requested_uid_must_match_signed_uid_even_before_profile(env, signer, monkeypatch):
    monkeypatch.delenv("OWNER_ID")
    assert "error" in env.rpc(
        "account.set_firebase_token", uid="otherFirebaseUid", id_token=signer(), expires_at_ms=2**53
    )
    assert env.rpc("account.set_firebase_token", uid=UID, id_token=signer(), expires_at_ms=2**53)[
        "result"
    ]["ok"]


def test_verified_preprofile_signin_remains_available(env, signer, monkeypatch):
    monkeypatch.delenv("OWNER_ID")
    assert env.rpc("auth.refresh", id_token=signer())["result"]["uid"] == UID


def test_hosted_missing_owner_refuses_admission(env, signer, monkeypatch):
    from zylch import runtime

    monkeypatch.setattr(runtime, "_serving", True)
    monkeypatch.delenv("OWNER_ID")
    assert env.rpc("auth.refresh", id_token=signer())["error"]["code"] == -32011


@pytest.mark.parametrize("kind", ["forged", "other_uid", "expired"])
def test_headless_refresh_refuses_unverified_identity_before_rotation(
    env, signer, monkeypatch, kind
):
    clear_session()
    saved = []
    store = SimpleNamespace(
        get_firebase_refresh_token=lambda owner: "fixture-refresh",
        store_firebase_refresh_token=lambda *args: saved.append(args),
    )
    monkeypatch.setattr(Storage, "get_instance", lambda: store)
    monkeypatch.setattr(settings, "firebase_web_api_key", "fixture-public-api-key")
    token = {
        "forged": "not-a-jwt",
        "other_uid": signer("otherFirebaseUid"),
        "expired": signer(expiry=int(time.time()) - 1),
    }[kind]
    monkeypatch.setattr(
        refresh,
        "exchange_refresh_token",
        lambda *_: {"id_token": token, "refresh_token": "rotated", "expires_at_ms": 2**53},
    )
    assert not refresh.ensure_fresh_session(UID)
    assert get_session() is None
    assert not saved


def test_headless_refresh_derives_verified_expiry_and_preserves_rotation(env, signer, monkeypatch):
    clear_session()
    saved = []
    store = SimpleNamespace(
        get_firebase_refresh_token=lambda owner: "fixture-refresh",
        store_firebase_refresh_token=lambda *args: saved.append(args),
    )
    monkeypatch.setattr(Storage, "get_instance", lambda: store)
    monkeypatch.setattr(settings, "firebase_web_api_key", "fixture-public-api-key")
    expiry = int(time.time()) + 3600
    monkeypatch.setattr(
        refresh,
        "exchange_refresh_token",
        lambda *_: {
            "id_token": signer(expiry=expiry),
            "refresh_token": "rotated",
            "expires_at_ms": 2**53,
        },
    )
    assert refresh.ensure_fresh_session(UID)
    assert get_session().expires_at_ms == expiry * 1000
    assert saved == [(UID, "rotated")]


def test_cached_headless_expiry_is_derived_from_verified_token(env, signer, monkeypatch):
    expiry = int(time.time()) + 3600
    set_session(UID, None, signer(expiry=expiry), 2**53)
    monkeypatch.setattr(
        Storage, "get_instance", lambda: pytest.fail("fresh session must not open DB")
    )
    assert refresh.ensure_fresh_session(UID)
    assert get_session().expires_at_ms == expiry * 1000


@pytest.mark.parametrize("kind", ["forged", "expired"])
def test_cached_headless_fake_expiry_cannot_skip_verification(env, signer, monkeypatch, kind):
    token = "not-a-jwt" if kind == "forged" else signer(expiry=int(time.time()) - 1)
    set_session(UID, None, token, 2**53)
    monkeypatch.setattr(
        Storage, "get_instance", lambda: SimpleNamespace(get_firebase_refresh_token=lambda _: None)
    )
    assert not refresh.ensure_fresh_session(UID)


def test_ws_expiry_grace_cannot_be_extended_by_forged_rpc(env, signer, monkeypatch):
    from zylch import runtime

    monkeypatch.setattr(runtime, "_serving", True)
    expiry = int(time.time()) + 120
    token = signer(expiry=expiry)
    requests = [
        ("qonto.test", env.credentials),
        (
            "account.set_firebase_token",
            {"uid": UID, "id_token": "not-a-jwt", "expires_at_ms": 2**53},
        ),
        ("qonto.test", env.credentials),
    ]

    class Connection:
        def __init__(self):
            self.responses = []
            self.ready = asyncio.Queue()
            self.closed = None

        async def send(self, raw):
            response = json.loads(raw)
            if "id" in response:
                self.responses.append(response)
                await self.ready.put(None)

        async def close(self, code, reason):
            self.closed = code

        def respond(self, status, body):
            return status

        async def __aiter__(self):
            monkeypatch.setattr(time, "time", lambda: expiry + 1)
            for number, (method, params) in enumerate(requests, 1):
                yield json.dumps(
                    {"jsonrpc": "2.0", "id": number, "method": method, "params": params}
                )
                await asyncio.wait_for(self.ready.get(), timeout=3)
            monkeypatch.setattr(time, "time", lambda: expiry + 31)
            yield json.dumps({"jsonrpc": "2.0", "id": 4, "method": "account.who_am_i"})

    async def scenario():
        connection = Connection()
        assert (
            await server_ws._process_request(
                connection, SimpleNamespace(headers={"Authorization": f"Bearer {token}"})
            )
            is None
        )
        await server_ws._handle_connection(connection)
        return connection

    connection = asyncio.run(scenario())
    assert len(connection.responses) == 3
    assert all("error" in response for response in connection.responses)
    assert connection.responses[1]["error"]["code"] == -32011
    assert not env.provider.calls
    assert connection.closed == server_ws.WS_CLOSE_AUTH_EXPIRED
    assert get_session().expires_at_ms == expiry * 1000
