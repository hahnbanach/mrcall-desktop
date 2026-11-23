from types import SimpleNamespace

import pytest

from zylch.email.gmail_auth import GmailError
from zylch.rpc import google_gmail_actions as actions
from zylch.rpc.param_spec import parse_signature

OWNER = "owner@example.test"
UID = "fixture-firebase-uid"


@pytest.fixture
def actor(monkeypatch):
    monkeypatch.setattr(actions, "require_session", lambda: SimpleNamespace(uid=UID))
    monkeypatch.setattr(actions.gmail_auth, "_profile_owner", lambda: UID)
    monkeypatch.setattr("zylch.cli.utils.get_owner_id", lambda: OWNER)


@pytest.mark.asyncio
async def test_begin_complete_status_disconnect_route_only_authenticated_profile(actor, monkeypatch):
    calls = []

    def record(name):
        def run(*args, **kwargs):
            calls.append((name, args, kwargs))
            return {"route": name}
        return run

    for method in ["begin", "complete", "status", "disconnect"]:
        monkeypatch.setattr(actions.gmail_auth, method, record(method))
    notify = lambda *args: None
    assert await actions.google_gmail_begin({"redirect_uri": "https://engine.example.test/cb"}, notify) == {"route": "begin"}
    assert await actions.google_gmail_complete({"code": "private-code", "state": "private-state"}, notify) == {"route": "complete"}
    await actions.google_gmail_status({}, notify)
    await actions.google_gmail_disconnect({}, notify)
    assert [c[0] for c in calls] == ["begin", "complete", "status", "disconnect"]
    assert all(c[1][0] == OWNER and c[2]["credential_owner"] == UID for c in calls)
    assert calls[1][1][1:] == ("private-code", "private-state")


@pytest.mark.asyncio
async def test_session_and_active_profile_mismatch_refuses_before_oauth(actor, monkeypatch):
    monkeypatch.setattr(actions.gmail_auth, "_profile_owner", lambda: "foreign-profile")
    monkeypatch.setattr(actions.gmail_auth, "begin", lambda *a, **kw: pytest.fail("cross-profile authorization"))
    with pytest.raises(GmailError, match="gmail_profile_mismatch"):
        await actions.google_gmail_begin({}, lambda *args: None)


def test_each_auth_rpc_declares_precise_public_parameters():
    expected = {"google.gmail.begin": {"redirect_uri"}, "google.gmail.complete": {"code", "state"},
                "google.gmail.status": set(), "google.gmail.disconnect": set()}
    assert {name: parse_signature(name, handler.__doc__) for name, handler in actions.METHODS.items()} == expected


def test_dispatch_redacts_oauth_codes_state_and_redirect_parameters():
    from zylch.rpc.dispatch import _redact_params

    params = {"code": "private-code", "state": "private-state", "redirect_uri": "https://engine.example.test/cb"}
    redacted = _redact_params("google.gmail.complete", params)
    assert "private-code" not in str(redacted) and "private-state" not in str(redacted)


@pytest.mark.asyncio
async def test_local_oauth_begin_reports_required_encryption_without_writing_pending_state(actor, monkeypatch, tmp_path):
    from zylch import runtime
    from zylch.config import settings
    from zylch.storage import Storage, database
    from zylch.storage.models import OAuthToken
    from zylch.utils import encryption

    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(settings, "encryption_key", None)
    monkeypatch.setattr(runtime, "_serving", False)
    monkeypatch.setattr(actions.gmail_auth, "_client_settings", lambda: ("synthetic-client-id", "synthetic-client-secret"))
    encryption.reset_for_tests()
    database.dispose_engine()
    try:
        OAuthToken.__table__.create(database.get_engine())
        monkeypatch.setattr(actions.gmail_auth, "_store", lambda: Storage.__new__(Storage))
        with pytest.raises(GmailError, match="gmail_encrypted_storage_required"):
            await actions.google_gmail_begin({}, lambda *args: None)
        with database.get_engine().connect() as conn:
            assert conn.exec_driver_sql("SELECT count(*) FROM oauth_tokens").scalar() == 0
    finally:
        database.dispose_engine()
        encryption.reset_for_tests()
