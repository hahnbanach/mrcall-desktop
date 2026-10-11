"""Actual migration, table routing, credential exclusion and rekey verification."""

import sqlite3

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import inspect

from zylch.qonto.models import QontoConnection, TABLE_NAMES
from zylch.qonto.repository import profile_transaction, read_binding
from zylch.storage import database as dbm, rekey

from .conftest import KEY, UID


def test_init_db_adds_finance_only_to_profile_and_replays_without_rewriting(env):
    profile = set(inspect(dbm.get_engine()).get_table_names())
    company = set(inspect(dbm.current_memory_engine()).get_table_names())
    assert TABLE_NAMES <= profile
    assert not TABLE_NAMES & company
    assert not TABLE_NAMES & set(dbm.MEMORY_TABLE_NAMES)
    with dbm.get_engine().begin() as conn:
        conn.exec_driver_sql("CREATE TABLE untouched_fixture (value TEXT)")
        conn.exec_driver_sql("INSERT INTO untouched_fixture VALUES ('keep')")
    assert env.connect()["result"]["ok"]
    before = read_binding(UID)
    dbm.init_db()
    assert read_binding(UID) == before
    with dbm.get_engine().begin() as conn:
        assert conn.exec_driver_sql("SELECT value FROM untouched_fixture").scalar_one() == "keep"
        assert (
            conn.exec_driver_sql(
                "SELECT COUNT(*) FROM schema_version WHERE id='0003_qonto_private'"
            ).scalar_one()
            == 1
        )


def test_first_addition_backs_up_wal_database_and_private_config(env):
    dbm.dispose_engine()
    path = env.directory / "zylch.db"
    with sqlite3.connect(path) as conn:
        for table in TABLE_NAMES:
            conn.execute(f"DROP TABLE {table}")
        conn.execute("DELETE FROM schema_version WHERE id='0003_qonto_private'")
        conn.execute("CREATE TABLE wal_fixture (value TEXT)")
        conn.execute("INSERT INTO wal_fixture VALUES ('preserved-wal-row')")
        conn.commit()
        dbm.init_db()
    backups = list((env.directory / "backups").glob("*.qonto-private-v1.*.bak"))
    assert len(backups) == 1
    backup = backups[0]
    assert backup.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT value FROM wal_fixture").fetchone()[0] == "preserved-wal-row"
        assert not TABLE_NAMES & {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    config = type(backup)(str(backup) + ".env")
    assert config.read_bytes() == (env.directory / ".env").read_bytes()
    assert config.stat().st_mode & 0o777 == 0o600
    dbm.init_db()
    assert len(list((env.directory / "backups").glob("*.qonto-private-v1.*.bak"))) == 1


@pytest.mark.parametrize(
    "key",
    [
        "QONTO_API_LOGIN",
        "QONTO_API_KEY",
        "QONTO_BOOTSTRAP_ENV_FILE",
        "QONTO_HOST_ID_FILE",
        "qonto_api_login",
    ],
)
def test_settings_schema_readback_writeback_and_provisioning_refuse_finance(env, monkeypatch, key):
    from zylch.services import settings_schema
    from zylch.provisiond import handler

    with (env.directory / ".env").open("a") as stream:
        stream.write(f"{key}={KEY}\n")
    monkeypatch.setattr(settings_schema, "KNOWN_KEYS", settings_schema.KNOWN_KEYS | {key})
    monkeypatch.setattr(settings_schema, "SECRET_KEYS", settings_schema.SECRET_KEYS | {key})
    assert key not in env.rpc("settings.get")["result"]["values"]
    assert KEY not in repr(env.rpc("settings.get"))
    assert env.rpc("settings.get_secret", key=key).get("error")
    assert env.rpc("settings.update", updates={key: "new"}).get("error")
    assert KEY in (env.directory / ".env").read_text()
    monkeypatch.setattr(handler, "_systemctl_is_active", lambda _: False)
    monkeypatch.setattr(handler, "_tenant_dropin_path", lambda _: str(env.home / "absent"))
    monkeypatch.setenv("MRCALL_PROFILES_ROOT", str(env.home / "provisioned"))
    monkeypatch.setattr(handler, "KNOWN_KEYS", handler.KNOWN_KEYS | {key})
    with pytest.raises(handler.ProvisionError, match="not transferable"):
        handler.handle_provision({"sub": "newFirebaseUid"}, {key: KEY})
    assert not (env.home / "provisioned").exists()


def test_rekey_and_startup_enumeration_include_qonto_and_refuse_plaintext(env):
    assert env.connect()["result"]["ok"]
    old = (env.directory / "qonto.key").read_text()
    new = Fernet.generate_key().decode()
    report = rekey.rekey(old, new)
    assert report.ok and report.rewritten == 1
    assert rekey.verify(new).ok
    assert not rekey.verify(old).ok
    second = rekey.rekey(old, new)
    assert second.ok and second.already == 1 and second.rewritten == 0
    assert rekey.rekey(new, old).ok
    assert rekey.verify(old).ok
    with profile_transaction() as session:
        session.get(QontoConnection, UID).encrypted_credentials = '{"login":"plain","key":"plain"}'
    report = rekey.rekey(old, new)
    assert not report.ok and report.failed == ["qonto: credential envelope does not decrypt"]
    assert not rekey.verify(new).ok


def test_migration_and_finance_deletion_preserve_actual_mail_task_token_rows(env):
    from datetime import datetime, timezone
    from zylch.storage.models import Email, TaskItem, OAuthToken

    with profile_transaction() as session:
        session.add(
            Email(
                id="mail-fixture",
                owner_id="display@example.test",
                gmail_id="provider-mail",
                thread_id="thread-fixture",
                date=datetime.now(timezone.utc),
                body_plain="keep email",
            )
        )
        session.add(
            TaskItem(
                id="task-fixture",
                owner_id="display@example.test",
                event_type="email",
                event_id="provider-mail",
                channel="email",
                title="keep task",
            )
        )
        session.add(
            OAuthToken(
                id="token-fixture",
                owner_id=UID,
                provider="fixture",
                email="display@example.test",
                credentials={"fixture": "keep token"},
            )
        )
    dbm.dispose_engine()
    dbm.init_db()
    assert env.connect()["result"]["ok"]
    assert env.rpc("qonto.delete_imported_data", confirmed=True)["result"]["deleted"]
    with profile_transaction() as session:
        assert session.get(Email, "mail-fixture").body_plain == "keep email"
        assert session.get(TaskItem, "task-fixture").title == "keep task"
        assert session.get(OAuthToken, "token-fixture").credentials == {"fixture": "keep token"}
    assert env.rpc("tasks.list")["result"][0]["id"] == "task-fixture"
