import base64
import copy
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from zylch.email import gmail_auth as auth

OWNER = "owner@example.test"
UID = "firebase-fixture-uid"


class Store:
    def __init__(self):
        self.rows = {}
        self.saved = []

    def get_provider_credentials(self, uid, provider):
        return copy.deepcopy(self.rows.get((uid, provider)))

    def save_provider_credentials(self, uid, provider, credentials):
        self.rows[(uid, provider)] = copy.deepcopy(credentials)
        self.saved.append((uid, provider))
        return True

    def delete_provider_credentials(self, uid, provider):
        self.rows.pop((uid, provider), None)
        return True


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    monkeypatch.setattr(auth, "_client_settings", lambda: ("client-id", "private-client-secret"))
    monkeypatch.delenv("GOOGLE_GMAIL_REDIRECT_URIS", raising=False)
    return Store()


def credentials(**changes):
    return {"email": OWNER, "scope": auth.GMAIL_SCOPE, "access_token": "private-access-token",
            "refresh_token": "private-refresh-token", "client_id": "client-id", "expires_at": time.time() + 3600, **changes}


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_begin_uses_s256_offline_scope_mailbox_hint_and_encrypted_store_api(configured):
    result = auth.begin(OWNER, credential_owner=UID, store=configured)
    query = parse_qs(urlsplit(result["auth_url"]).query)
    pending = configured.rows[(UID, auth.PENDING_PROVIDER)]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(pending["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == [challenge]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["openid email " + auth.GMAIL_SCOPE]
    assert query["access_type"] == ["offline"] and query["prompt"] == ["consent"]
    assert query["login_hint"] == [OWNER] and pending["email"] == OWNER
    assert "code_verifier" not in result and "private-client-secret" not in result["auth_url"]
    assert configured.saved == [(UID, auth.PENDING_PROVIDER)]


def test_hosted_callback_must_be_exactly_configured_before_begin(configured, monkeypatch):
    uri = "https://engine.example.test/oauth/gmail/callback"
    with pytest.raises(auth.GmailError, match="gmail_oauth_redirect_not_allowed"):
        auth.begin(OWNER, redirect_uri=uri, credential_owner=UID, store=configured)
    monkeypatch.setenv("GOOGLE_GMAIL_REDIRECT_URIS", json.dumps([uri]))
    result = auth.begin(OWNER, redirect_uri=uri, credential_owner=UID, store=configured)
    assert result["redirect_uri"] == uri


@pytest.mark.parametrize("value", ['"https://example.test"', '["http://remote.example.test/cb"]', '["https://user@example.test/cb"]', '["https://example.test/cb?code=private"]', '["https://example.test/cb#fragment"]', '[]', 'invalid'])
def test_invalid_redirect_configuration_refuses(configured, monkeypatch, value):
    monkeypatch.setenv("GOOGLE_GMAIL_REDIRECT_URIS", value)
    with pytest.raises(auth.GmailError, match="gmail_oauth_redirect_configuration_invalid"):
        auth.begin(OWNER, credential_owner=UID, store=configured)


def test_complete_exchanges_code_with_saved_pkce_then_binds_provider_mailbox(configured):
    started = auth.begin(OWNER, credential_owner=UID, store=configured)
    pending = configured.rows[(UID, auth.PENDING_PROVIDER)]
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            data = parse_qs(request.content.decode())
            assert data["code_verifier"] == [pending["code_verifier"]]
            assert data["redirect_uri"] == [started["redirect_uri"]]
            assert data["code"] == ["private-authorization-code"]
            return httpx.Response(200, json={"access_token": "private-new-token", "refresh_token": "private-new-refresh",
                                            "scope": auth.GMAIL_SCOPE, "expires_in": 3600, "token_type": "Bearer"})
        assert request.url.path.endswith("/profile") and request.headers["Authorization"] == "Bearer private-new-token"
        return httpx.Response(200, json={"emailAddress": OWNER})

    result = auth.complete(OWNER, "private-authorization-code", started["state"], credential_owner=UID, store=configured, http_client=client(handler))
    assert result == {"ok": True, "email": OWNER, "scope": auth.GMAIL_SCOPE}
    assert (UID, auth.PENDING_PROVIDER) not in configured.rows
    assert configured.rows[(UID, auth.PROVIDER)]["email"] == OWNER
    assert configured.rows[(UID, auth.PROVIDER)]["expires_at"] > time.time()
    assert len(calls) == 2 and all("private" not in str(v) for v in result.values())


@pytest.mark.parametrize("problem,expected", [("state", "gmail_oauth_state_mismatch"), ("expired", "gmail_oauth_expired"), ("owner", "gmail_mailbox_mismatch"), ("client", "gmail_oauth_client_mismatch")])
def test_callback_binding_errors_never_exchange_code(configured, problem, expected):
    started = auth.begin(OWNER, credential_owner=UID, store=configured)
    pending = configured.rows[(UID, auth.PENDING_PROVIDER)]
    if problem == "expired":
        pending["expires_at"] = time.time() - 1
    elif problem == "owner":
        pending["email"] = "foreign@example.test"
    elif problem == "client":
        pending["client_id"] = "another-client"
    state = "wrong-state" if problem == "state" else started["state"]
    with pytest.raises(auth.GmailError, match=expected):
        auth.complete(OWNER, "private-code", state, credential_owner=UID, store=configured,
                      http_client=client(lambda r: pytest.fail("invalid callback dispatched")))


@pytest.mark.parametrize("scope,email,expected", [("https://www.googleapis.com/auth/calendar.readonly", OWNER, "gmail_scope_missing"), (auth.GMAIL_SCOPE, "foreign@example.test", "gmail_mailbox_mismatch")])
def test_complete_refuses_calendar_only_and_foreign_mailbox_before_saving(configured, scope, email, expected):
    started = auth.begin(OWNER, credential_owner=UID, store=configured)

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"access_token": "private-new-token", "refresh_token": "private-refresh", "scope": scope, "expires_in": 3600})
        return httpx.Response(200, json={"emailAddress": email})

    with pytest.raises(auth.GmailError, match=expected):
        auth.complete(OWNER, "private-code", started["state"], credential_owner=UID, store=configured, http_client=client(handler))
    assert (UID, auth.PROVIDER) not in configured.rows


def test_calendar_credentials_are_never_used_as_gmail_auth(configured):
    configured.rows[(UID, "google_calendar")] = credentials(scope="https://www.googleapis.com/auth/calendar.readonly")
    instance = auth.GmailAuth(OWNER, credential_owner=UID, store=configured, http_client=client(lambda r: pytest.fail("wrong provider used")))
    with pytest.raises(auth.GmailError, match="gmail_authorization_required"):
        instance.access_token()


def test_current_gmail_token_is_bound_to_real_provider_profile(configured):
    configured.rows[(UID, auth.PROVIDER)] = credentials()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"emailAddress": OWNER})

    instance = auth.GmailAuth(OWNER, credential_owner=UID, store=configured, http_client=client(handler))
    assert instance.verify() == {"email": OWNER, "scope": auth.GMAIL_SCOPE}
    assert len(calls) == 1 and calls[0].method == "GET"


@pytest.mark.parametrize("changes,expected", [({"scope": "openid email"}, "gmail_scope_missing"), ({"email": "foreign@example.test"}, "gmail_mailbox_mismatch"), ({"access_token": ""}, "gmail_authorization_required")])
def test_bad_stored_scope_or_identity_never_dispatches(configured, changes, expected):
    configured.rows[(UID, auth.PROVIDER)] = credentials(**changes)
    instance = auth.GmailAuth(OWNER, credential_owner=UID, store=configured, http_client=client(lambda r: pytest.fail("invalid credentials dispatched")))
    with pytest.raises(auth.GmailError, match=expected):
        instance.access_token()


def test_expired_token_refreshes_before_dispatch_and_preserves_refresh_token(configured):
    configured.rows[(UID, auth.PROVIDER)] = credentials(expires_at=time.time() - 1)
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            body = parse_qs(request.content.decode())
            assert body["refresh_token"] == ["private-refresh-token"]
            assert body["client_id"] == ["client-id"]
            assert body["grant_type"] == ["refresh_token"]
            return httpx.Response(200, json={"access_token": "fresh-token", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer fresh-token"
        return httpx.Response(200, json={"emailAddress": OWNER})

    instance = auth.GmailAuth(OWNER, credential_owner=UID, store=configured, http_client=client(handler))
    instance.verify()
    assert [r.method for r in calls] == ["POST", "GET"]
    assert configured.rows[(UID, auth.PROVIDER)]["refresh_token"] == "private-refresh-token"


def test_auth_error_never_retries_refresh_or_leaks_secrets(configured, caplog):
    configured.rows[(UID, auth.PROVIDER)] = credentials(expires_at=0)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400, json={"error": "private-refresh-token SECRET private-client-secret"})

    instance = auth.GmailAuth(OWNER, credential_owner=UID, store=configured, http_client=client(handler))
    with pytest.raises(auth.GmailError) as error:
        instance.access_token()
    assert len(calls) == 1
    assert all(value not in str(error.value) + caplog.text for value in ["SECRET", "private-refresh-token", "private-client-secret"])


def test_actual_profile_email_mismatch_refuses(configured):
    configured.rows[(UID, auth.PROVIDER)] = credentials()
    instance = auth.GmailAuth(OWNER, credential_owner=UID, store=configured, http_client=client(lambda r: httpx.Response(200, json={"emailAddress": "foreign@example.test"})))
    with pytest.raises(auth.GmailError, match="gmail_mailbox_mismatch"):
        instance.verify()


def test_disconnect_deletes_only_gmail_and_pending_credentials(configured):
    configured.rows[(UID, auth.PROVIDER)] = credentials()
    configured.rows[(UID, "google_calendar")] = {"scope": "calendar"}
    auth.begin(OWNER, credential_owner=UID, store=configured)
    assert auth.status(OWNER, credential_owner=UID, store=configured)["connected"] is True
    auth.disconnect(OWNER, credential_owner=UID, store=configured)
    assert auth.status(OWNER, credential_owner=UID, store=configured)["connected"] is False
    assert configured.rows == {(UID, "google_calendar"): {"scope": "calendar"}}


def test_pending_pkce_and_tokens_use_real_encrypted_store_across_restart(configured, monkeypatch, tmp_path):
    from cryptography.fernet import Fernet
    from zylch.storage import database, Storage
    from zylch.storage.models import OAuthToken
    from zylch.utils import encryption

    path = tmp_path / "profile.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(path))
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    encryption.reset_for_tests()
    database.dispose_engine()
    try:
        OAuthToken.__table__.create(database.get_engine())
        store = Storage.__new__(Storage)
        started = auth.begin(OWNER, credential_owner=UID, store=store)
        pending = store.get_provider_credentials(UID, auth.PENDING_PROVIDER)
        with database.get_engine().connect() as connection:
            stored = str(connection.exec_driver_sql("SELECT credentials FROM oauth_tokens").scalar())
        assert pending["code_verifier"] not in stored and pending["state"] not in stored
        database.dispose_engine()
        calls = []

        def handler(request):
            calls.append(request)
            if request.method == "POST":
                assert parse_qs(request.content.decode())["code_verifier"] == [pending["code_verifier"]]
                return httpx.Response(200, json={"access_token": "private-new-token", "refresh_token": "private-new-refresh",
                                                "scope": auth.GMAIL_SCOPE, "expires_in": 3600})
            return httpx.Response(200, json={"emailAddress": OWNER})

        result = auth.complete(OWNER, "private-code", started["state"], credential_owner=UID,
                               store=Storage.__new__(Storage), http_client=client(handler))
        assert result["ok"] is True and len(calls) == 2
        with database.get_engine().connect() as connection:
            stored = str(connection.exec_driver_sql("SELECT credentials FROM oauth_tokens WHERE provider = ?", (auth.PROVIDER,)).scalar())
        assert "private-new-token" not in stored and "private-new-refresh" not in stored
        database.dispose_engine()
        restored = Storage.__new__(Storage).get_provider_credentials(UID, auth.PROVIDER)
        assert restored["refresh_token"] == "private-new-refresh" and restored["email"] == OWNER
    finally:
        database.dispose_engine()
        encryption.reset_for_tests()
