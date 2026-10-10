"""Hosted CLI admission validates Qonto envelopes before server construction."""

import json
import logging
import os

import pytest
from click.testing import CliRunner
from cryptography.fernet import Fernet

from zylch import runtime
from zylch.qonto.models import QontoConnection
from zylch.qonto.repository import profile_transaction
from zylch.qonto.secrets import assert_hosted_credentials_ready
from zylch.storage.database import get_engine
from zylch.utils import encryption

from .conftest import KEY, LOGIN, UID


def startup(env, monkeypatch):
    from zylch.cli import main
    import zylch.config as config
    from zylch.rpc import server_ws

    launched = []

    async def server(host=None, port=None, **kwargs):
        launched.append({"host": host, "port": port, **kwargs})

    monkeypatch.setattr(main, "_check_update", lambda: None)
    monkeypatch.setattr(server_ws, "serve_ws", server)
    encryption.reset_for_tests()
    original_handlers = list(logging.getLogger().handlers)
    original_settings = config.settings
    try:
        result = CliRunner().invoke(main.cli, ["-p", UID, "serve", "--ws", "127.0.0.1:5174"])
    finally:
        config.settings = original_settings
        for handler in list(logging.getLogger().handlers):
            if handler not in original_handlers:
                logging.getLogger().removeHandler(handler)
                handler.close()
        encryption.reset_for_tests()
        from zylch.cli.profiles import release_lock

        release_lock()
    return result, launched


def hosted(env, monkeypatch, *, token=None):
    key = Fernet.generate_key()
    monkeypatch.setenv("ENCRYPTION_KEY", key.decode())
    value = (
        token
        or Fernet(key)
        .encrypt(json.dumps({"version": 1, "login": LOGIN, "key": KEY}).encode())
        .decode()
    )
    with profile_transaction() as session:
        session.add(
            QontoConnection(
                uid=UID,
                status="disconnected",
                generation=0,
                changed_at=1,
                encrypted_credentials=value,
            )
        )
    return value


@pytest.mark.parametrize("damage", ["corrupt", "plaintext", "wrong_key", "invalid_envelope"])
def test_real_cli_corrupted_envelope_refuses_before_server_or_provider(
    env, monkeypatch, caplog, damage
):
    token = hosted(env, monkeypatch)
    if damage == "wrong_key":
        monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    else:
        damaged = {
            "corrupt": "gAAAA-invalid",
            "plaintext": LOGIN + ":" + KEY,
            "invalid_envelope": Fernet(os.environ["ENCRYPTION_KEY"].encode())
            .encrypt(json.dumps({"version": 9, "login": LOGIN, "key": KEY}).encode())
            .decode(),
        }[damage]
        with profile_transaction() as session:
            session.get(QontoConnection, UID).encrypted_credentials = damaged
    with caplog.at_level(logging.DEBUG):
        result, launched = startup(env, monkeypatch)
    assert result.exit_code == 3, result.output
    assert "credentials_unreadable" in result.output
    assert not launched and not env.provider.calls
    assert token not in caplog.text and LOGIN not in caplog.text and KEY not in caplog.text
    assert LOGIN not in result.output and KEY not in result.output
    assert not (env.directory / "qonto.key").exists()


def test_real_cli_valid_envelope_reaches_server_without_provider(env, monkeypatch):
    hosted(env, monkeypatch)
    result, launched = startup(env, monkeypatch)
    assert result.exit_code == 0, result.output
    assert launched == [{"host": "127.0.0.1", "port": 5174}]
    assert not env.provider.calls and not (env.directory / "qonto.key").exists()


@pytest.mark.parametrize("schema", ["empty", "no_qonto_table"])
def test_real_cli_existing_profile_without_saved_qonto_is_unchanged(env, monkeypatch, schema):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    if schema == "no_qonto_table":
        with get_engine().begin() as connection:
            connection.exec_driver_sql("DROP TABLE qonto_connections")
        monkeypatch.setattr(runtime, "_serving", True)
        assert assert_hosted_credentials_ready() == 0
    result, launched = startup(env, monkeypatch)
    assert result.exit_code == 0, result.output
    assert len(launched) == 1 and not env.provider.calls


def test_hosted_helper_checks_every_nonempty_row_and_ignores_empty_rows(env, monkeypatch):
    token = hosted(env, monkeypatch)
    monkeypatch.setattr(runtime, "_serving", True)
    with profile_transaction() as session:
        session.add_all(
            [
                QontoConnection(
                    uid="empty",
                    status="disconnected",
                    generation=0,
                    changed_at=1,
                    encrypted_credentials="",
                ),
                QontoConnection(uid="absent", status="disconnected", generation=0, changed_at=1),
                QontoConnection(
                    uid="second",
                    status="disconnected",
                    generation=0,
                    changed_at=1,
                    encrypted_credentials=token,
                ),
            ]
        )
    assert assert_hosted_credentials_ready() == 2
    with profile_transaction() as session:
        session.get(QontoConnection, "second").encrypted_credentials = "bad"
    with pytest.raises(Exception, match="credentials_unreadable"):
        assert_hosted_credentials_ready()


def test_local_helper_does_not_require_hosted_key_or_touch_ciphertext(env, monkeypatch):
    hosted(env, monkeypatch, token="local-data-is-not-a-hosted-envelope")
    monkeypatch.delenv("ENCRYPTION_KEY")
    assert assert_hosted_credentials_ready() == 0
