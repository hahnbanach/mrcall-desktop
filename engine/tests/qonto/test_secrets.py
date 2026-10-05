"""Direct Fernet, real private files, bootstrap preservation and safe errors."""

import logging
import os
import subprocess
import sys

import pytest
from cryptography.fernet import Fernet

from zylch import runtime
from zylch.qonto import provider
from zylch.qonto.bootstrap import credentials
from zylch.qonto.errors import QontoError
from zylch.qonto.repository import read_binding
from zylch.qonto.secrets import cipher, decrypt_credentials

from .conftest import KEY, LOGIN, UID


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
def test_bootstrap_strict_credentials(key, login, expected):
    if expected:
        with pytest.raises(QontoError, match=expected):
            credentials(login, key)
    else:
        assert credentials(login, key) == credentials(LOGIN, KEY)


def test_bootstrap_is_preserved_on_disconnect_and_never_auto_imported(env):
    path = env.directory / ".env"
    with path.open("a") as stream:
        stream.write(f"QONTO_API_LOGIN={LOGIN}\nQONTO_API_KEY={KEY}\n")
    original = path.read_bytes()
    assert env.rpc("qonto.status")["result"]["bootstrap"]["available"] is True
    assert not env.provider.calls
    tested = env.rpc("qonto.test", credential_source="bootstrap")["result"]
    assert env.rpc(
        "qonto.connect",
        credential_source="bootstrap",
        challenge_id=tested["challenge_id"],
        account_ids=["account-eur"],
        authority_confirmed=True,
        consent_version=1,
    )["result"]["ok"]
    result = env.rpc("qonto.disconnect")["result"]
    assert result["bootstrap_retained"] is True
    assert result["bootstrap"]["available"] is True
    assert path.read_bytes() == original
    from zylch.storage import database as dbm

    dbm.dispose_engine()
    dbm.init_db()
    calls = len(env.provider.calls)
    assert env.rpc("qonto.status")["result"]["status"] == "disconnected"
    assert len(env.provider.calls) == calls
    assert read_binding(UID).encrypted_credentials is None
    assert path.read_bytes() == original


def test_explicit_development_file_never_interpolates_or_gets_rewritten(env, monkeypatch):
    path = env.home / ".env.qonto"
    path.write_text(f"QONTO_API_LOGIN={LOGIN}\nQONTO_API_KEY='${{EXPAND_ME}}'\nOTHER=ignored\n")
    monkeypatch.setenv("EXPAND_ME", KEY)
    monkeypatch.setenv("QONTO_BOOTSTRAP_ENV_FILE", str(path))
    original = path.read_bytes()
    assert (
        "invalid_credentials"
        in env.rpc("qonto.test", credential_source="bootstrap")["error"]["message"]
    )
    assert path.read_bytes() == original
    monkeypatch.setattr(runtime, "_serving", True)
    from zylch.qonto.bootstrap import load_bootstrap

    with pytest.raises(QontoError, match="bootstrap_override_disabled"):
        load_bootstrap()


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
