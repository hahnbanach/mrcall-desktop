"""Mailbox rows, the primary from ``.env``, encrypted secrets, IMAP clients.

Real SQLite file, real Fernet, no IMAP connection (``IMAPClient`` connects
on first use). Passwords are generated per test and never written down.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import UTC, datetime

import pytest

from zylch.email import mailbox_secrets, mailboxes, sync_cursor
from zylch.email.mailbox_secrets import MailboxSecretError
from zylch.storage import database as dbm

OWNER = "owner@company.test"


@pytest.fixture
def booted(tmp_path, monkeypatch):
    db_path = str(tmp_path / "zylch.db")
    monkeypatch.setenv("ZYLCH_DB_PATH", db_path)
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    monkeypatch.setenv("EMAIL_PASSWORD", secrets.token_hex(8))
    monkeypatch.setenv("IMAP_HOST", "imap.company.test")
    monkeypatch.setenv("IMAP_PORT", "993")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_PORT", raising=False)
    monkeypatch.delenv(mailbox_secrets.SETTING, raising=False)
    dbm.dispose_engine()
    dbm.init_db()
    import zylch.storage.storage as storage_mod

    monkeypatch.setattr(storage_mod, "_generate_email_embedding", lambda email: None)
    yield db_path
    dbm.dispose_engine()


def _rows(db_path: str, sql: str, params=()):
    c = sqlite3.connect(db_path)
    try:
        return c.execute(sql, params).fetchall()
    finally:
        c.close()


def _email(message_id: str, when: datetime | None = None) -> dict:
    when = when or datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    return {
        "id": message_id,
        "thread_id": message_id,
        "from_email": "customer@client.test",
        "to_email": OWNER,
        "subject": "hello",
        "date": when.isoformat(),
        "date_timestamp": int(when.timestamp()),
        "message_id_header": message_id,
    }


# ─── fresh shape and the primary row ──────────────────────────


def test_fresh_db_has_the_new_shape_and_the_primary_from_env(booted):
    ddl = _rows(booted, "SELECT sql FROM sqlite_master WHERE name='emails'")[0][0]
    assert "emails_owner_mailbox_gmail_unique" in ddl
    cols = {r[1]: r[3] for r in _rows(booted, "PRAGMA table_info(emails)")}
    assert cols["mailbox_id"] == 1 and "original_message_id" in cols and "pec_markers" in cols
    assert _rows(booted, "SELECT name FROM sqlite_master WHERE name='mailboxes'")

    prim = mailboxes.primary(OWNER)
    assert prim is not None and prim.is_primary and not prim.has_secret
    assert (prim.address, prim.imap_host, prim.imap_port) == (OWNER, "imap.company.test", 993)
    assert prim.smtp_host is None and prim.smtp_port is None
    assert mailboxes.for_owner(OWNER) == [prim]
    assert mailboxes.by_id(OWNER, prim.id) == prim
    assert mailboxes.by_address(OWNER, OWNER) == prim
    assert mailboxes.by_address(OWNER, f" {OWNER.upper()} ") == prim  # trimmed, case-insensitive
    assert mailboxes.active_mailbox_ids(OWNER) == [prim.id]


def test_primary_hosts_follow_env_on_every_boot(booted, monkeypatch):
    before = mailboxes.primary(OWNER)
    monkeypatch.setenv("IMAP_HOST", "imap.other.test")
    monkeypatch.setenv("SMTP_HOST", "smtp.other.test")
    dbm.dispose_engine()
    dbm.init_db()
    after = mailboxes.primary(OWNER)
    assert after.id == before.id  # same row, refreshed
    assert (after.imap_host, after.smtp_host) == ("imap.other.test", "smtp.other.test")
    assert _rows(booted, "SELECT COUNT(*) FROM mailboxes") == [(1,)]


def test_default_mailbox_for_an_owner_without_address_is_owner_keyed(booted):
    other = "someone-else@company.test"
    first = mailboxes.default_mailbox_id(other)
    assert mailboxes.default_mailbox_id(other) == first
    row = mailboxes.by_id(other, first)
    assert row.address == other and not row.is_primary and not row.removed
    assert mailboxes.primary(other) is None


# ─── secrets ──────────────────────────────────────────────────


def test_add_mailbox_encrypts_the_password_and_persists_the_key(booted):
    from zylch.services.settings_io import read_env
    from zylch.services.settings_schema import KNOWN_KEYS

    password = secrets.token_urlsafe(12)
    box = mailboxes.add_mailbox(
        OWNER, "pec@pec.company.test", password, imap_host="imap.pec.test", imap_port=993
    )
    assert box.has_secret and not box.is_primary
    stored = _rows(booted, "SELECT secret FROM mailboxes WHERE id = ?", (box.id,))[0][0]
    assert stored != password and password not in stored
    key = os.environ[mailbox_secrets.SETTING]
    assert read_env()[mailbox_secrets.SETTING] == key  # written through settings_io
    assert mailbox_secrets.SETTING not in KNOWN_KEYS  # never a Settings schema key

    assert [m.address for m in mailboxes.for_owner(OWNER)] == [OWNER, "pec@pec.company.test"]
    client = mailboxes.build_imap_client(box)
    assert client.password == password
    assert (client.email_addr, client.imap_host, client.imap_port) == (
        "pec@pec.company.test",
        "imap.pec.test",
        993,
    )


def test_add_mailbox_refuses_active_duplicate_and_revives_a_removed_one(booted):
    box = mailboxes.add_mailbox(OWNER, "pec@pec.company.test", secrets.token_urlsafe(12))
    with pytest.raises(ValueError):
        mailboxes.add_mailbox(OWNER, "pec@pec.company.test", secrets.token_urlsafe(12))
    with pytest.raises(ValueError):
        mailboxes.add_mailbox(OWNER, OWNER, secrets.token_urlsafe(12))  # the primary too

    with dbm.get_engine().begin() as conn:
        conn.exec_driver_sql(
            "UPDATE mailboxes SET removed_at = '2026-09-30 00:00:00' WHERE id = ?", (box.id,)
        )
    assert mailboxes.for_owner(OWNER) == [mailboxes.primary(OWNER)]
    revived = mailboxes.add_mailbox(OWNER, "pec@pec.company.test", secrets.token_urlsafe(12))
    assert revived.id == box.id and not revived.removed


def test_primary_client_uses_env_password_and_hosts(booted, monkeypatch):
    prim = mailboxes.primary(OWNER)
    monkeypatch.setenv("IMAP_HOST", "imap.live.test")  # env wins over the mirrored row
    client = mailboxes.build_imap_client(prim)
    assert client.password == os.environ["EMAIL_PASSWORD"]
    assert (client.email_addr, client.imap_host) == (OWNER, "imap.live.test")

    monkeypatch.setenv("EMAIL_PASSWORD", "")
    with pytest.raises(MailboxSecretError):
        mailboxes.build_imap_client(prim)


def test_secret_round_trip_and_fail_closed(booted, monkeypatch):
    password = secrets.token_urlsafe(12)
    token = mailbox_secrets.encrypt_secret(password)
    key = os.environ[mailbox_secrets.SETTING]
    assert mailbox_secrets.decrypt_secret(token) == password

    with pytest.raises(MailboxSecretError) as e:
        mailbox_secrets.decrypt_secret("not-a-token")
    assert key not in str(e.value) and password not in str(e.value)
    with pytest.raises(MailboxSecretError):
        mailbox_secrets.decrypt_secret(None)
    with pytest.raises(MailboxSecretError):
        mailbox_secrets.encrypt_secret("")

    from cryptography.fernet import Fernet

    monkeypatch.setenv(mailbox_secrets.SETTING, Fernet.generate_key().decode())
    with pytest.raises(MailboxSecretError) as e:  # another profile's key
        mailbox_secrets.decrypt_secret(token)
    assert token not in str(e.value) and password not in str(e.value)

    monkeypatch.setenv(mailbox_secrets.SETTING, "")
    with pytest.raises(MailboxSecretError) as e:  # no key at all: never the input back
        mailbox_secrets.decrypt_secret(token)
    assert token not in str(e.value)


def test_secondary_without_key_fails_closed_never_returning_ciphertext(booted, monkeypatch):
    box = mailboxes.add_mailbox(OWNER, "pec@pec.company.test", secrets.token_urlsafe(12))
    monkeypatch.setenv(mailbox_secrets.SETTING, "")
    with pytest.raises(MailboxSecretError):
        mailboxes.build_imap_client(box)


# ─── rows and cursors per mailbox ─────────────────────────────


def test_same_message_id_in_two_mailboxes_is_two_rows(booted):
    from zylch.storage.storage import Storage

    st = Storage()
    prim = mailboxes.primary(OWNER)
    second = mailboxes.add_mailbox(OWNER, "pec@pec.company.test", secrets.token_urlsafe(12))

    assert st.store_emails_batch(OWNER, [_email("<shared@mail.test>")]) == 1  # default: primary
    assert st.store_emails_batch(OWNER, [_email("<shared@mail.test>")], mailbox_id=second.id) == 1
    rows = _rows(booted, "SELECT mailbox_id FROM emails WHERE gmail_id = '<shared@mail.test>'")
    assert sorted(r[0] for r in rows) == sorted([prim.id, second.id])

    # a re-store of the same copy updates, never duplicates
    st.store_emails_batch(OWNER, [_email("<shared@mail.test>")], mailbox_id=second.id)
    st.store_email(
        OWNER,
        {
            **_email("<shared@mail.test>"),
            "date": datetime(2026, 9, 1, 10, 0, tzinfo=UTC).replace(tzinfo=None),
        },
    )
    assert _rows(booted, "SELECT COUNT(*) FROM emails") == [(2,)]

    # dedup and floor lookups are per mailbox
    newer = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    st.store_emails_batch(OWNER, [_email("<only-second@mail.test>", newer)], mailbox_id=second.id)
    assert "<only-second@mail.test>" not in st.get_existing_email_ids(OWNER, prim.id)
    assert "<only-second@mail.test>" in st.get_existing_email_ids(OWNER, mailbox_id=second.id)
    assert st.get_newest_email_date(OWNER, prim.id).day == 1
    assert st.get_newest_email_date(OWNER, mailbox_id=second.id).day == 20

    pairs = st.get_thread_message_id_headers(OWNER, "<shared@mail.test>")
    assert sorted(pairs) == sorted(
        [(prim.id, "<shared@mail.test>"), (second.id, "<shared@mail.test>")]
    )


def test_direct_orm_insert_without_mailbox_gets_the_primary(booted):
    from zylch.storage.database import get_session
    from zylch.storage.models import Email

    with get_session() as session:
        session.add(
            Email(
                owner_id=OWNER,
                gmail_id="<direct@mail.test>",
                thread_id="t",
                date=datetime(2026, 9, 1, 10, 0, tzinfo=UTC).replace(tzinfo=None),
            )
        )
    assert _rows(booted, "SELECT mailbox_id FROM emails") == [(mailboxes.primary(OWNER).id,)]


def test_cursors_are_scoped_per_mailbox(booted):
    prim = mailboxes.primary(OWNER)
    second = mailboxes.add_mailbox(OWNER, "pec@pec.company.test", secrets.token_urlsafe(12))

    assert sync_cursor.set_cursor(OWNER, "INBOX", 7, 100, mailbox_id=prim.id) is True
    assert sync_cursor.set_cursor(OWNER, "INBOX", 9, 5, mailbox_id=second.id) is True
    assert sync_cursor.get_cursor(OWNER, "INBOX", mailbox_id=prim.id).last_uid == 100
    assert sync_cursor.get_cursor(OWNER, "INBOX", mailbox_id=second.id).last_uid == 5
    assert len(sync_cursor.list_cursors(OWNER)) == 2
    assert len(sync_cursor.list_cursors(OWNER, mailbox_id=second.id)) == 1
    assert sync_cursor.drop_cursor(OWNER, "INBOX", mailbox_id=second.id) is True
    assert sync_cursor.get_cursor(OWNER, "INBOX", mailbox_id=second.id) is None
    assert sync_cursor.get_cursor(OWNER, "INBOX", prim.id).last_uid == 100
