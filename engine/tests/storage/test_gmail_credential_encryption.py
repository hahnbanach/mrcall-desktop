import json

import pytest
from cryptography.fernet import Fernet

from zylch import runtime
from zylch.email.gmail_auth import GmailError
from zylch.storage import Storage, database
from zylch.storage.models import OAuthToken
from zylch.utils import encryption

UID = "synthetic-firebase-uid"


@pytest.fixture
def store(tmp_path, monkeypatch):
    import zylch.config as config

    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(config.settings, "encryption_key", None)
    monkeypatch.setattr(runtime, "_serving", False)
    encryption.reset_for_tests()
    database.dispose_engine()
    OAuthToken.__table__.create(database.get_engine())
    yield Storage.__new__(Storage)
    database.dispose_engine()
    encryption.reset_for_tests()


def raw_rows():
    with database.get_engine().connect() as conn:
        return conn.exec_driver_sql("SELECT owner_id, provider, credentials FROM oauth_tokens ORDER BY provider").fetchall()


@pytest.mark.parametrize("provider", ["google_gmail", "google_gmail_pending"])
def test_gmail_secret_storage_refuses_local_missing_key_without_plaintext_write(store, provider):
    with pytest.raises(GmailError, match="gmail_encrypted_storage_required"):
        store.save_provider_credentials(UID, provider, {"refresh_token": "synthetic-private-refresh", "code_verifier": "synthetic-private-pkce"})
    assert raw_rows() == []


@pytest.mark.parametrize("provider", ["google_gmail", "google_gmail_pending"])
def test_gmail_backend_failure_never_writes_plaintext_or_exposes_secret(store, monkeypatch, provider, caplog):
    class Broken:
        def encrypt(self, plaintext):
            raise RuntimeError("synthetic-secret-backend-echo")

    monkeypatch.setattr(encryption, "_get_fernet", lambda: Broken())
    with pytest.raises(GmailError, match="gmail_encrypted_storage_required") as error:
        store.save_provider_credentials(UID, provider, {"refresh_token": "synthetic-private-refresh"})
    assert raw_rows() == []
    assert "synthetic-private-refresh" not in str(error.value) + caplog.text
    assert "synthetic-secret-backend-echo" not in str(error.value) + caplog.text


def test_failure_of_outer_encryption_preserves_existing_row_byte_for_byte(store, monkeypatch):
    fernet = Fernet(Fernet.generate_key())
    monkeypatch.setattr(encryption, "_get_fernet", lambda: fernet)
    store.save_provider_credentials(UID, "google_gmail", {"refresh_token": "synthetic-old-refresh"})
    original = raw_rows()

    class FailOuter:
        def __init__(self):
            self.calls = 0

        def encrypt(self, plaintext):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("synthetic-outer-failure")
            return fernet.encrypt(plaintext)

        def decrypt(self, ciphertext):
            return fernet.decrypt(ciphertext)

    backend = FailOuter()
    monkeypatch.setattr(encryption, "_get_fernet", lambda: backend)
    with pytest.raises(GmailError, match="gmail_encrypted_storage_required"):
        store.save_provider_credentials(UID, "google_gmail", {"refresh_token": "synthetic-new-refresh"})
    assert raw_rows() == original


def test_gmail_normal_fernet_roundtrip_encrypts_fields_and_outer_metadata(store, monkeypatch):
    key = Fernet.generate_key()
    monkeypatch.setenv("ENCRYPTION_KEY", key.decode())
    encryption.reset_for_tests()
    credentials = {"refresh_token": "synthetic-private-refresh", "code_verifier": "synthetic-private-pkce"}
    for provider in ["google_gmail", "google_gmail_pending"]:
        store.save_provider_credentials(UID, provider, credentials, metadata_dict={"private_label": "synthetic-label"})
    for _, provider, stored in raw_rows():
        serialized = str(stored)
        assert all(secret not in serialized for secret in [*credentials.values(), "synthetic-label"])
        outer = json.loads(Fernet(key).decrypt(json.loads(serialized).encode()))
        assert Fernet(key).decrypt(outer[provider]["refresh_token"][10:].encode()).decode() == credentials["refresh_token"]
        assert store.get_provider_credentials(UID, provider) == credentials


def test_other_provider_local_missing_key_preserves_legacy_default(store):
    assert store.save_provider_credentials(UID, "google_calendar", {"refresh_token": "synthetic-calendar-refresh"}) is True
    assert store.get_provider_credentials(UID, "google_calendar") == {"refresh_token": "synthetic-calendar-refresh"}
    assert "synthetic-calendar-refresh" in str(raw_rows())


def test_gmail_silent_backend_passthrough_is_refused(store, monkeypatch):
    class Passthrough:
        def encrypt(self, plaintext):
            return plaintext

        def decrypt(self, plaintext):
            return plaintext

    monkeypatch.setattr(encryption, "_get_fernet", lambda: Passthrough())
    with pytest.raises(GmailError, match="gmail_encrypted_storage_required"):
        store.save_provider_credentials(UID, "google_gmail", {"refresh_token": "synthetic-private-refresh"})
    assert raw_rows() == []


def test_gmail_invalid_key_refuses_without_plaintext_row(store, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "synthetic-invalid-key")
    encryption.reset_for_tests()
    with pytest.raises(GmailError, match="gmail_encrypted_storage_required"):
        store.save_provider_credentials(UID, "google_gmail_pending", {"code_verifier": "synthetic-private-pkce"})
    assert raw_rows() == []


@pytest.mark.parametrize("provider", ["google_gmail", "google_gmail_pending"])
@pytest.mark.parametrize("replacement", ["missing", "other"])
def test_reopened_gmail_ciphertext_has_typed_refusal_and_remains_unchanged(store, monkeypatch, provider, replacement):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    encryption.reset_for_tests()
    store.save_provider_credentials(UID, provider, {"refresh_token": "synthetic-original-refresh"})
    original = raw_rows()
    if replacement == "missing":
        monkeypatch.delenv("ENCRYPTION_KEY")
    else:
        monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    encryption.reset_for_tests()
    with pytest.raises(GmailError, match="gmail_encrypted_storage_required"):
        store.get_provider_credentials(UID, provider)
    with pytest.raises(GmailError, match="gmail_encrypted_storage_required"):
        store.save_provider_credentials(UID, provider, {"refresh_token": "synthetic-replacement-refresh"})
    assert raw_rows() == original


@pytest.mark.parametrize("replacement", ["missing", "other"])
def test_dispatch_begin_after_pending_ciphertext_reopen_preserves_typed_error(store, monkeypatch, replacement):
    import asyncio
    from zylch.rpc import google_gmail_actions as actions
    from zylch.rpc.dispatch import dispatch_raw

    monkeypatch.setattr(actions, "_actor", lambda: ("owner@example.test", UID))
    monkeypatch.setenv("EMAIL_ADDRESS", "owner@example.test")
    monkeypatch.setattr(actions.gmail_auth, "_client_settings", lambda: ("synthetic-client", "synthetic-secret"))
    monkeypatch.setattr(actions.gmail_auth, "_store", lambda: store)

    def begin():
        return asyncio.run(dispatch_raw(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "google.gmail.begin", "params": {}}), lambda *args: None))

    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    encryption.reset_for_tests()
    assert "result" in begin()
    original = raw_rows()
    if replacement == "missing":
        monkeypatch.delenv("ENCRYPTION_KEY")
    else:
        monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    encryption.reset_for_tests()
    outcome = begin()
    assert raw_rows() == original
    assert outcome["error"]["code"] == -32030
    assert "gmail_encrypted_storage_required" in outcome["error"]["message"]
