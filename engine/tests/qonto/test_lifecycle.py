"""Real lifecycle dispatch, single-use confirmation and persisted revocation races."""

import asyncio
import subprocess
import sys
import uuid
from dataclasses import replace

import pytest

from zylch.qonto import challenges, guard, repository
from zylch.qonto.errors import QontoError
from zylch.qonto.models import QontoAccount, QontoConnection, QontoTransaction
from zylch.storage import database as dbm

from .conftest import UID


def params(env, tested, **overrides):
    values = {
        **env.credentials,
        "challenge_id": tested["challenge_id"],
        "account_ids": ["account-eur"],
        "authority_confirmed": True,
        "consent_version": 1,
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    "change", ["credentials", "organization", "account", "expired", "host", "company", "uid"]
)
def test_confirmation_binding_cannot_be_reused_in_another_context(env, monkeypatch, change):
    tested = env.rpc("qonto.test", **env.credentials)["result"]
    values = params(env, tested)
    if change == "credentials":
        values["api_key"] = "other-key"
    elif change == "organization":
        env.provider.result = replace(env.provider.result, id="other-org")
    elif change == "account":
        values["account_ids"] = ["not-tested-account"]
    elif change == "expired":
        monkeypatch.setattr(challenges, "TTL_SECONDS", -1)
        tested = env.rpc("qonto.test", **env.credentials)["result"]
        values = params(env, tested)
    elif change == "host":
        (env.home / "engine-installation-id").write_text(str(uuid.uuid4()))
    elif change == "company":
        from zylch.memory.company_key import mint_key, persist_company_key

        persist_company_key(mint_key(), source="mint")
        dbm.dispose_engine()
        dbm.init_db()
    else:
        from .conftest import signin

        signin("anotherFirebaseUid")
    response = env.rpc("qonto.connect", **values)
    assert response.get("error"), response
    assert not repository.read_binding(UID).encrypted_credentials


def test_test_saves_no_credential_or_accounts_and_save_only_selected_accounts(env):
    tested = env.rpc("qonto.test", **env.credentials)["result"]
    assert repository.read_binding(UID).encrypted_credentials is None
    assert not (env.directory / "qonto.key").exists()
    with repository.profile_transaction() as session:
        assert session.query(QontoAccount).count() == 0
        assert session.query(QontoTransaction).count() == 0
    assert env.rpc("qonto.connect", **params(env, tested))["result"]["ok"]
    with repository.profile_transaction() as session:
        assert [row.account_id for row in session.query(QontoAccount).all()] == ["account-eur"]
    assert len(env.provider.calls) == 3


def test_reprobe_accounts_and_legal_company_must_match_test(env):
    tested = env.rpc("qonto.test", **env.credentials)["result"]
    env.provider.result = replace(env.provider.result, legal_name="Different legal company")
    assert "binding_changed" in env.rpc("qonto.connect", **params(env, tested))["error"]["message"]


def test_account_selection_narrows_tested_snapshot_and_replay_cannot_double_save(env):
    tested = env.rpc("qonto.test", **env.credentials)["result"]
    result = env.rpc("qonto.connect", **params(env, tested))["result"]
    assert result["account_count"] == 1
    first = repository.read_binding(UID)
    assert (
        "challenge_invalid" in env.rpc("qonto.connect", **params(env, tested))["error"]["message"]
    )
    assert repository.read_binding(UID) == first
    with repository.profile_transaction() as session:
        assert session.query(QontoConnection).count() == 1


def test_optional_test_selection_cannot_expand_on_save(env):
    tested = env.rpc("qonto.test", **env.credentials, account_ids=["account-eur"])["result"]
    assert (
        "accounts_invalid"
        in env.rpc("qonto.connect", **params(env, tested, account_ids=["account-gbp"]))["error"][
            "message"
        ]
    )


@pytest.mark.parametrize("authority,version", [(False, 1), ("true", 1), (True, 2), (True, True)])
def test_authority_confirmation_and_exact_consent_version_are_required(env, authority, version):
    tested = env.rpc("qonto.test", **env.credentials)["result"]
    assert (
        "authority_required"
        in env.rpc(
            "qonto.connect",
            **params(env, tested, authority_confirmed=authority, consent_version=version),
        )["error"]["message"]
    )


@pytest.mark.asyncio
async def test_disconnect_while_network_reprobe_waits_fences_late_connect(env, monkeypatch):
    tested = (await env.arpc("qonto.test", **env.credentials))["result"]
    entered, release = asyncio.Event(), asyncio.Event()
    original = env.provider.organization

    async def slow(value):
        entered.set()
        await release.wait()
        return await original(value)

    monkeypatch.setattr(env.provider, "organization", slow)
    save = asyncio.create_task(env.arpc("qonto.connect", **params(env, tested)))
    await asyncio.wait_for(entered.wait(), timeout=2)
    revoked = await asyncio.wait_for(env.arpc("qonto.disconnect"), timeout=2)
    release.set()
    response = await save
    assert revoked["result"]["status"] == "disconnected"
    assert "generation_changed" in response["error"]["message"]
    assert repository.read_binding(UID).encrypted_credentials is None


@pytest.mark.asyncio
async def test_company_join_fences_probe_and_retains_suspension_if_abandoned(env, monkeypatch):
    assert (await env.arpc("qonto.test", **env.credentials))["result"]["ok"]
    tested = (await env.arpc("qonto.test", **env.credentials))["result"]
    entered, release = asyncio.Event(), asyncio.Event()
    original = env.provider.organization

    async def slow(value):
        entered.set()
        await release.wait()
        return await original(value)

    monkeypatch.setattr(env.provider, "organization", slow)
    save = asyncio.create_task(env.arpc("qonto.connect", **params(env, tested)))
    await asyncio.wait_for(entered.wait(), timeout=2)
    guard.suspend_for_join()
    release.set()
    assert "generation_changed" in (await save)["error"]["message"]
    assert (await env.arpc("qonto.status"))["result"]["status"] == "suspended"


def test_real_join_and_recovery_hooks_fence_existing_finance(env):
    from zylch.memory.company_key import mint_key
    from zylch.memory.join import join
    from zylch.memory.store import open_memory_engine, prepare_store

    assert env.connect()["result"]["ok"]
    before = repository.read_binding(UID)
    key = mint_key()
    destination = open_memory_engine(key, create=True)
    prepare_store(destination, key, created_by="mint")
    destination.dispose()
    assert join(key)["ok"]
    after = repository.read_binding(UID)
    assert after.status == "suspended" and after.generation > before.generation
    dbm.dispose_engine()
    dbm.init_db()
    assert env.rpc("qonto.status")["result"]["status"] == "suspended"


def test_signout_fences_running_work_and_signin_does_not_resume(env):
    assert env.connect()["result"]["ok"]
    authority, binding = guard.active_binding()
    assert env.rpc("account.sign_out")["result"]["ok"]
    from .conftest import signin

    signin()
    assert env.rpc("qonto.status")["result"]["status"] == "suspended"
    with pytest.raises(QontoError, match="generation_changed"):
        with guard.commit_guard(authority, binding):
            pass


def test_disconnect_reconnect_same_binding_retains_dataset_other_binding_never_relabels(env):
    assert env.connect()["result"]["ok"]
    first = repository.read_binding(UID)
    env.rpc("qonto.disconnect")
    assert env.connect()["result"]["ok"]
    second = repository.read_binding(UID)
    assert second.dataset_id == first.dataset_id
    assert second.generation > first.generation
    env.rpc("qonto.disconnect")
    env.provider.result = replace(env.provider.result, id="different-org")
    assert env.connect()["result"]["ok"]
    assert repository.read_binding(UID).dataset_id != first.dataset_id
    with repository.profile_transaction() as session:
        old = session.get(QontoAccount, (first.dataset_id, "account-eur"))
        assert old.organization_id == "org-id" and old.selected is False


def test_state_changes_are_visible_to_another_process_after_restart(env):
    assert env.connect()["result"]["ok"]
    authority, binding = guard.active_binding()
    script = "from zylch.storage.database import init_db; from zylch.qonto.connection import disconnect; from zylch.auth import set_session; import sys,time; init_db(); set_session(sys.argv[1],None,'fixture-token',int(time.time()*1000)+100000); disconnect()"
    process = subprocess.run(
        [sys.executable, "-c", script, UID], capture_output=True, text=True, timeout=30
    )
    assert process.returncode == 0, process.stderr
    with pytest.raises(QontoError, match="generation_changed"):
        with guard.commit_guard(authority, binding):
            pass
    assert repository.read_binding(UID).encrypted_credentials is None


def test_explicit_delete_removes_only_private_finance_rows(env):
    assert env.connect()["result"]["ok"]
    assert (
        "confirmation_required"
        in env.rpc("qonto.delete_imported_data", confirmed=False)["error"]["message"]
    )
    assert env.rpc("qonto.delete_imported_data", confirmed=True)["result"]["deleted"]
    with repository.profile_transaction() as session:
        assert session.query(QontoAccount).count() == 0
        assert session.query(QontoTransaction).count() == 0
    assert env.rpc("qonto.status")["result"]["status"] == "disconnected"


def test_expiry_during_encryption_rolls_back_save(env, monkeypatch):
    from zylch.qonto import connection
    from .conftest import signin

    tested = env.rpc("qonto.test", **env.credentials)["result"]
    encrypt = connection.encrypt_credentials

    def expire(*args, **kwargs):
        result = encrypt(*args, **kwargs)
        signin(expired=True)
        return result

    monkeypatch.setattr(connection, "encrypt_credentials", expire)
    assert "session_expired" in env.rpc("qonto.connect", **params(env, tested))["error"]["message"]
    assert repository.read_binding(UID).encrypted_credentials is None
    assert repository.read_binding(UID).status == "disconnected"


def test_failed_new_credential_does_not_revoke_an_existing_working_credential(env):
    assert env.connect()["result"]["ok"]
    before = repository.read_binding(UID)
    env.provider.error = QontoError("auth")
    assert (
        "auth"
        in env.rpc("qonto.test", login="other-login", api_key="other-key")["error"]["message"]
    )
    assert repository.read_binding(UID) == before
    assert "auth" in env.rpc("qonto.test", **env.credentials)["error"]["message"]
    after = repository.read_binding(UID)
    assert after.status == "auth_failed" and after.encrypted_credentials is None
    assert after.generation > before.generation
    assert env.rpc("qonto.status")["result"]["status"] == "auth_failed"


def test_commit_guard_rechecks_expiry_at_exit_and_rolls_back_source_write(env):
    assert env.connect()["result"]["ok"]
    authority, binding = guard.active_binding()
    from .conftest import signin

    with pytest.raises(QontoError, match="session_expired"):
        with guard.commit_guard(authority, binding) as session:
            session.get(QontoAccount, (binding.dataset_id, "account-eur")).name = "must-not-land"
            signin(expired=True)
    with repository.profile_transaction() as session:
        assert (
            session.get(QontoAccount, (binding.dataset_id, "account-eur")).name
            == "Business account"
        )
