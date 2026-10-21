"""Direct Fernet, real private files, the single typed credential source and safe errors."""

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from zylch import runtime
from zylch.auth import clear_session
from zylch.qonto import provider
from zylch.qonto.bootstrap import credentials
from zylch.qonto.errors import QontoError
from zylch.qonto.repository import read_binding
from zylch.qonto.secrets import cipher, decrypt_credentials

from .conftest import KEY, LOGIN, UID, signin

RETIRED_NAMES = ("QONTO_API_LOGIN", "QONTO_API_KEY", "QONTO_BOOTSTRAP_ENV_FILE")
LEFTOVER_LOGIN = "leftover-organization-login"
LEFTOVER_KEY = "leftover-api-key-secret"


@pytest.fixture
def leftover(env, monkeypatch):
    """Well-formed credential lines outside the request, and the bytes each file must keep.

    The lines sit in the profile ``.env`` and in the process environment, as
    profile activation leaves them, and in a second file named by the
    environment. Their values differ from the typed fixture credentials.
    """
    profile_env = env.directory / ".env"
    with profile_env.open("a") as stream:
        stream.write(f"QONTO_API_LOGIN={LEFTOVER_LOGIN}\nQONTO_API_KEY={LEFTOVER_KEY}\n")
    monkeypatch.setenv("QONTO_API_LOGIN", LEFTOVER_LOGIN)
    monkeypatch.setenv("QONTO_API_KEY", LEFTOVER_KEY)
    second = env.home / ".env.qonto"
    second.write_text(
        f"QONTO_API_LOGIN=second-{LEFTOVER_LOGIN}\nQONTO_API_KEY=second-{LEFTOVER_KEY}\n"
    )
    monkeypatch.setenv("QONTO_BOOTSTRAP_ENV_FILE", str(second))
    return {path: path.read_bytes() for path in (profile_env, second)}


def refusal(response):
    """Safe outcome word of a refused Qonto request."""
    assert "result" not in response
    assert response["error"]["code"] == QontoError.code
    return response["error"]["message"].split(":", 1)[0]


def save_parameters(challenge_id, *, authority_confirmed=True):
    """The four required ``qonto.connect`` parameters."""
    return {
        "challenge_id": challenge_id,
        "account_ids": ["account-eur"],
        "authority_confirmed": authority_confirmed,
        "consent_version": 1,
    }


def test_only_encrypted_application_copy_is_saved_and_survives_restart(env):
    assert env.connect()["result"]["ok"]
    row = read_binding(UID)
    assert KEY not in row.encrypted_credentials and LOGIN not in row.encrypted_credentials
    assert decrypt_credentials(row.encrypted_credentials, env.directory) == credentials(LOGIN, KEY)
    assert os.stat(env.directory / "qonto.key").st_mode & 0o777 == 0o600
    from zylch.storage import database as dbm

    dbm.dispose_engine()
    dbm.init_db()
    assert env.rpc("qonto.status")["result"]["status"] == "connected"
    assert decrypt_credentials(read_binding(UID).encrypted_credentials, env.directory).key == KEY
    assert "fixture-id-token" not in (env.directory / ".env").read_text()


@pytest.mark.parametrize("damage", ["missing", "wrong", "corrupt", "unsafe", "symlink"])
def test_key_and_ciphertext_fail_closed_before_connect_probe(env, damage):
    assert env.connect()["result"]["ok"]
    tested = env.rpc("qonto.test", **env.credentials)["result"]
    path = env.directory / "qonto.key"
    if damage == "missing":
        path.unlink()
    elif damage == "wrong":
        path.write_bytes(Fernet.generate_key())
    elif damage == "unsafe":
        path.chmod(0o644)
    elif damage == "symlink":
        target = env.directory / "unsafe-target"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
    else:
        from zylch.qonto.models import QontoConnection
        from zylch.qonto.repository import profile_transaction

        with profile_transaction() as session:
            session.get(QontoConnection, UID).encrypted_credentials = "gAAA-corrupt"
    before = len(env.provider.calls)
    response = env.rpc(
        "qonto.connect",
        **env.credentials,
        challenge_id=tested["challenge_id"],
        account_ids=["account-eur"],
        authority_confirmed=True,
        consent_version=1,
    )
    assert response.get("error"), response
    assert len(env.provider.calls) == before
    assert env.rpc("qonto.status")["result"]["source_access"] is False


def test_simultaneous_processes_create_one_persisted_key(env):
    script = "from pathlib import Path; from zylch.qonto.secrets import cipher; import sys; print(cipher(Path(sys.argv[1]), create=True).encrypt(b'probe').decode())"
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(env.directory)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    tokens = []
    for process in processes:
        out, err = process.communicate(timeout=30)
        assert process.returncode == 0, err
        tokens.append(out.strip())
    persisted = cipher(env.directory)
    assert all(persisted.decrypt(token.encode()) == b"probe" for token in tokens)


def test_dangling_symlink_cannot_create_key_or_write_target(env):
    target = env.directory / "must-stay-absent"
    (env.directory / "qonto.key").symlink_to(target)
    response = env.connect()
    assert response["error"]["code"] == -32040
    assert not target.exists()


def test_hosted_missing_or_invalid_key_never_generates_local_key(env, monkeypatch):
    monkeypatch.setattr(runtime, "_serving", True)
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    with pytest.raises(QontoError, match="encryption_unavailable"):
        cipher(env.directory, create=True)
    monkeypatch.setenv("ENCRYPTION_KEY", "invalid")
    with pytest.raises(QontoError, match="encryption_unavailable"):
        cipher(env.directory, create=True)
    assert not (env.directory / "qonto.key").exists()


@pytest.mark.parametrize(
    "key,login,expected",
    [
        (KEY, None, "login_required"),
        (f"{LOGIN}:{KEY}", None, None),
        (f"{LOGIN}:{KEY}", "conflicting", "invalid_credentials"),
        (f"{LOGIN}:{KEY}:ambiguous", None, "invalid_credentials"),
        (KEY + "\n", LOGIN, "invalid_credentials"),
    ],
)
def test_strict_credential_format(key, login, expected):
    if expected:
        with pytest.raises(QontoError, match=expected):
            credentials(login, key)
    else:
        assert credentials(login, key) == credentials(LOGIN, KEY)


def test_bootstrap_is_explicit_read_only_and_cannot_mix_with_typed_input(env, leftover):
    status = env.rpc("qonto.status")["result"]
    assert status["bootstrap"] == {"available": True, "status": "available"}
    assert not env.provider.calls
    tested = env.rpc("qonto.test", credential_source="bootstrap")["result"]
    assert tested["ok"] and env.provider.calls[-1].login == "second-" + LEFTOVER_LOGIN
    assert read_binding(UID) is None or read_binding(UID).encrypted_credentials is None
    response = env.rpc("qonto.test", credential_source="bootstrap", **env.credentials)
    assert refusal(response) == "invalid_credentials"
    response = env.rpc(
        "qonto.connect", credential_source="bootstrap", **save_parameters(tested["challenge_id"])
    )
    assert response["result"]["ok"]
    disconnected = env.rpc("qonto.disconnect")["result"]
    assert disconnected["bootstrap_retained"] is True
    assert disconnected["bootstrap"]["available"] is True
    assert read_binding(UID).encrypted_credentials is None
    assert {path: path.read_bytes() for path in leftover} == leftover


def test_bootstrap_override_refusal_does_not_revoke_saved_connection(env, leftover, monkeypatch):
    monkeypatch.setattr(runtime, "_serving", True)
    monkeypatch.setenv("QONTO_HOST_ID_FILE", str(env.home / "host-id"))
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert env.connect()["result"]["ok"]
    before = read_binding(UID)
    assert (
        refusal(env.rpc("qonto.test", credential_source="bootstrap"))
        == "bootstrap_override_disabled"
    )
    assert read_binding(UID) == before
    assert {path: path.read_bytes() for path in leftover} == leftover


@pytest.mark.parametrize("method", ["qonto.test", "qonto.connect"])
@pytest.mark.parametrize(
    "source",
    [
        "",
        " input",
        "INPUT",
        "Input",
        "file",
        None,
        0,
        1.5,
        True,
        [],
        ["input"],
        {},
        {"credential_source": "input"},
    ],
    ids=repr,
)
def test_every_source_other_than_input_and_bootstrap_is_invalid(env, leftover, method, source):
    required = save_parameters("never-issued") if method == "qonto.connect" else {}
    for carried in ({}, env.credentials):
        response = env.rpc(method, credential_source=source, **carried, **required)
        assert refusal(response) == "invalid_credentials"
    assert env.provider.calls == []
    assert env.rpc("qonto.status")["result"]["status"] == "disconnected"
    assert {path: path.read_bytes() for path in leftover} == leftover


@pytest.mark.parametrize("source", [{}, {"credential_source": "input"}], ids=["omitted", "input"])
def test_typed_test_and_save_preserve_explicit_bootstrap_status(env, leftover, source):
    tested = env.rpc("qonto.test", **source, **env.credentials)["result"]
    assert tested["ok"] and tested["organization"]["id"] == "org-id"
    saved = env.rpc(
        "qonto.connect", **source, **env.credentials, **save_parameters(tested["challenge_id"])
    )["result"]
    assert saved["ok"] and saved["status"] == "connected"
    assert env.provider.calls and all(
        value == credentials(LOGIN, KEY) for value in env.provider.calls
    )
    stored = read_binding(UID).encrypted_credentials
    assert decrypt_credentials(stored, env.directory) == credentials(LOGIN, KEY)
    status = env.rpc("qonto.status")["result"]
    assert status["status"] == "connected" and status["bootstrap"]["available"] is True
    disconnected = env.rpc("qonto.disconnect")["result"]
    assert disconnected["status"] == "disconnected"
    assert (
        disconnected["bootstrap"]["available"] is True
        and disconnected["bootstrap_retained"] is True
    )
    deleted = env.rpc("qonto.delete_imported_data", confirmed=True)["result"]
    assert deleted["deleted"] is True
    assert deleted["deleted"] is True
    assert read_binding(UID).encrypted_credentials is None
    assert {path: path.read_bytes() for path in leftover} == leftover


@pytest.mark.parametrize("method", ["qonto.test", "qonto.connect"])
@pytest.mark.parametrize("state", ["signed_out", "expired", "other_uid"])
def test_identity_checks_precede_the_source_refusal(env, leftover, method, state):
    if state == "signed_out":
        clear_session()
        expected = "identity_required"
    elif state == "expired":
        signin(expired=True)
        expected = "session_expired"
    else:
        signin("otherFirebaseUid")
        expected = "identity_required"
    required = save_parameters("never-issued") if method == "qonto.connect" else {}
    for extra in (
        {"credential_source": "bootstrap"},
        {"credential_source": "bootstrap", **env.credentials},
        {"credential_source": "file", **env.credentials},
        dict(env.credentials),
    ):
        assert refusal(env.rpc(method, **extra, **required)) == expected
    assert env.provider.calls == []
    assert {path: path.read_bytes() for path in leftover} == leftover


@pytest.mark.parametrize("override", [True, False])
def test_serving_engine_preserves_profile_bootstrap_but_refuses_override(
    env, leftover, monkeypatch, override
):
    if not override:
        monkeypatch.delenv("QONTO_BOOTSTRAP_ENV_FILE")
    monkeypatch.setattr(runtime, "_serving", True)
    monkeypatch.setenv("QONTO_HOST_ID_FILE", str(env.home / "host-id"))
    expected = (
        {"available": False, "status": "bootstrap_override_disabled"}
        if override
        else {"available": True, "status": "available"}
    )
    assert env.rpc("qonto.status")["result"]["bootstrap"] == expected
    if override:
        assert (
            refusal(env.rpc("qonto.test", credential_source="bootstrap"))
            == "bootstrap_override_disabled"
        )
        assert not env.provider.calls
    else:
        assert env.rpc("qonto.test", credential_source="bootstrap")["result"]["ok"]
        assert env.provider.calls[-1].login == LEFTOVER_LOGIN
    assert read_binding(UID) is None or read_binding(UID).encrypted_credentials is None
    assert {path: path.read_bytes() for path in leftover} == leftover


def test_disconnected_profile_stays_disconnected_after_reopen_with_leftover_lines(env, leftover):
    from zylch.storage import database as dbm

    assert env.connect()["result"]["ok"]
    assert env.rpc("qonto.disconnect")["result"]["status"] == "disconnected"
    dbm.dispose_engine()
    dbm.init_db()
    calls = len(env.provider.calls)
    status = env.rpc("qonto.status")["result"]
    assert status["status"] == "disconnected" and status["credential_stored"] is False
    assert len(env.provider.calls) == calls
    assert read_binding(UID).encrypted_credentials is None
    assert {path: path.read_bytes() for path in leftover} == leftover


def test_logs_never_carry_leftover_or_typed_values(env, leftover, caplog):
    caplog.set_level(logging.DEBUG)
    save = save_parameters("never-issued")
    env.rpc("qonto.status")
    env.rpc("qonto.test", credential_source="bootstrap")
    env.rpc("qonto.test", credential_source="bootstrap", **env.credentials)
    env.rpc("qonto.connect", credential_source="bootstrap", **env.credentials, **save)
    env.rpc("qonto.test", credential_source="file", **env.credentials)
    assert env.connect()["result"]["ok"]
    env.rpc("qonto.disconnect")
    env.rpc("qonto.delete_imported_data", confirmed=True)
    assert caplog.text
    for secret in (LEFTOVER_LOGIN, LEFTOVER_KEY, LOGIN, KEY):
        assert secret not in caplog.text


def test_bootstrap_variables_are_confined_to_read_only_bootstrap_module():
    root = Path(__file__).resolve().parents[2] / "zylch"
    found = {
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        for name in RETIRED_NAMES
        if name.encode() in path.read_bytes()
    }
    assert found == {"qonto/bootstrap.py"}


def test_logs_and_provider_exception_never_include_credentials_or_lengths(env, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    assert env.rpc("qonto.test", **env.credentials)["result"]["ok"]
    env.provider.error = RuntimeError(f"Authorization {LOGIN}:{KEY}; SQL secret parameters")
    response = env.rpc("qonto.test", **env.credentials)
    assert response["error"]["code"] == -32040
    assert KEY not in repr(response) and LOGIN not in repr(response)
    assert KEY not in caplog.text and LOGIN not in caplog.text
    assert "len=" not in caplog.text


def test_missing_transport_refuses_instead_of_fake_success(env, monkeypatch):
    monkeypatch.setattr(provider, "_provider", provider.UnavailableProvider())
    response = env.rpc("qonto.test", **env.credentials)
    assert "transport_unavailable" in response["error"]["message"]
