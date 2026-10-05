"""The real dispatch path requires a live immutable Firebase profile binding."""

import time

import pytest

from zylch.auth import clear_session, set_session
from zylch.qonto.identity import current_authority
from zylch.storage import database as dbm

from .conftest import UID, signin


def error(response, outcome):
    assert outcome in response["error"]["message"], response


@pytest.mark.parametrize("mode", ["missing", "other_uid", "expired", "email_uid"])
def test_session_authority_is_not_email_or_memory_membership(env, mode):
    if mode == "missing":
        clear_session()
    elif mode == "expired":
        signin(expired=True)
    else:
        signin("otherFirebaseUid" if mode == "other_uid" else "display@example.test")
    error(
        env.rpc("qonto.test", **env.credentials),
        "session_expired" if mode == "expired" else "identity_required",
    )
    assert not env.provider.calls


@pytest.mark.parametrize("field", ["env_owner", "disk_owner", "profile_name", "db_path"])
def test_profile_uid_disagreement_refuses_before_provider(env, monkeypatch, field):
    from zylch.cli import profiles

    if field == "env_owner":
        monkeypatch.setenv("OWNER_ID", "wrongFirebaseUid")
    elif field == "disk_owner":
        (env.directory / ".env").write_text("OWNER_ID=display@example.test\n")
    elif field == "profile_name":
        monkeypatch.setattr(profiles, "_active_profile", "otherFirebaseUid")
    else:
        monkeypatch.setenv("ZYLCH_DB_PATH", str(env.home / "wrong.db"))
    error(env.rpc("qonto.test", **env.credentials), "identity_required")
    assert not env.provider.calls


def test_company_unavailable_and_pending_join_refuse_before_provider(env, monkeypatch):
    monkeypatch.setenv("MEMORY_KEY", "other-company-key")
    error(env.rpc("qonto.test", **env.credentials), "binding_changed")


def test_pending_join_is_not_qonto_authority(env):
    with (env.directory / ".env").open("a") as stream:
        stream.write("MEMORY_JOIN_TO=not-a-public-capability\n")
    error(env.rpc("qonto.test", **env.credentials), "company_joining")
    assert not env.provider.calls


def test_email_changes_do_not_change_finance_owner(env, monkeypatch):
    before = current_authority()
    monkeypatch.setenv("EMAIL_ADDRESS", "renamed@example.test")
    signin()
    assert current_authority() == before
    assert env.connect()["result"]["ok"]


@pytest.mark.parametrize(
    "override", ["owner_id", "uid", "company_key", "host_id", "organization_id"]
)
def test_rpc_rejects_identity_overrides(env, override):
    response = env.rpc("qonto.test", **env.credentials, **{override: "untrusted"})
    assert response["error"]["code"] == -32602
    assert not env.provider.calls


def test_expiry_during_probe_refuses_confirmation(env, monkeypatch):
    original = env.provider.organization

    async def expire(value):
        result = await original(value)
        set_session(UID, None, "new-token", int(time.time() * 1000) - 1)
        return result

    monkeypatch.setattr(env.provider, "organization", expire)
    error(env.rpc("qonto.test", **env.credentials), "session_expired")


def test_boot_suspends_a_connection_bound_to_another_company(env, monkeypatch):
    assert env.connect()["result"]["ok"]
    from zylch.memory.company_key import mint_key, persist_company_key

    persist_company_key(mint_key(), source="mint")
    dbm.dispose_engine()
    dbm.init_db()
    assert env.rpc("qonto.status")["result"]["status"] == "suspended"


def test_an_operator_changed_company_file_fences_a_stale_running_process(env):
    assert env.connect()["result"]["ok"]
    authority, binding = __import__(
        "zylch.qonto.guard", fromlist=["active_binding"]
    ).active_binding()
    path = env.directory / ".env"
    from zylch.memory.company_key import mint_key

    lines = [
        f"MEMORY_KEY={mint_key()}\n" if line.startswith("MEMORY_KEY=") else line
        for line in path.read_text().splitlines(keepends=True)
    ]
    path.write_text("".join(lines))
    from zylch.qonto.guard import commit_guard
    from zylch.qonto.errors import QontoError

    with pytest.raises(QontoError, match="binding_changed"):
        with commit_guard(authority, binding):
            pytest.fail("stale process must not reach commit")
    assert env.rpc("qonto.status")["result"]["status"] == "suspended"
