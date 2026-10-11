"""Three mailboxes, a restart between two syncs: no duplicates, own cursors.

The profile holds the primary and two additional mailboxes, each on its own
fake server with its own UIDVALIDITY. The first sync stores every message;
the engine is then restarted (engines disposed, ``init_db`` again) and the
second sync stores nothing new; each mailbox's INBOX cursor carries its own
server's UIDVALIDITY and last UID.
"""

from __future__ import annotations

import asyncio
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from tests.email.fake_imap import FakeFolder, build_raw_message, make_client
from zylch.email import mailboxes, sync_cursor
from zylch.storage import database as dbm

OWNER = "owner@company.test"
SECOND = "pec@pec.company.test"
THIRD = "sales@company.test"


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "zylch.db")
    monkeypatch.setenv("ZYLCH_DB_PATH", db_path)
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    monkeypatch.setenv("EMAIL_PASSWORD", secrets.token_hex(8))
    monkeypatch.delenv("MAILBOX_SECRET_KEY", raising=False)
    dbm.dispose_engine()
    dbm.init_db()
    import zylch.storage.storage as storage_mod

    monkeypatch.setattr(storage_mod, "_generate_email_embedding", lambda email: None)
    mailboxes.add_mailbox(OWNER, SECOND, secrets.token_urlsafe(12))
    mailboxes.add_mailbox(OWNER, THIRD, secrets.token_urlsafe(12))
    yield db_path
    dbm.dispose_engine()


def _sync():
    from zylch.services.sync_service import SyncService
    from zylch.storage.storage import Storage

    svc = SyncService(owner_id=OWNER, supabase_storage=Storage())
    return asyncio.run(svc.sync_emails(days_back=30))


def test_three_mailboxes_survive_a_restart_without_duplicates(env, monkeypatch):
    when = datetime.now(timezone.utc) - timedelta(days=1)
    folders = {
        OWNER: {"INBOX": FakeFolder(uidvalidity=101)},
        SECOND: {"INBOX": FakeFolder(uidvalidity=202)},
        THIRD: {"INBOX": FakeFolder(uidvalidity=303)},
    }
    folders[OWNER]["INBOX"].add(1, build_raw_message("<p1@x>", date=when))
    folders[SECOND]["INBOX"].add(4, build_raw_message("<s1@x>", date=when))
    folders[THIRD]["INBOX"].add(5, build_raw_message("<t1@x>", date=when))
    folders[THIRD]["INBOX"].add(6, build_raw_message("<t2@x>", date=when))
    # the service disconnects each client after its mailbox: a fresh client per build
    monkeypatch.setattr(
        mailboxes,
        "build_imap_client",
        lambda mailbox: make_client(folders[mailbox.address], email_addr=mailbox.address),
    )

    first = _sync()
    assert first["success"] is True and first["errors"] == []
    assert [m["address"] for m in first["mailboxes"]] == [OWNER, SECOND, THIRD]
    assert first["new_messages"] == 4

    # a restart: every engine disposed and the profile booted again
    dbm.dispose_engine()
    dbm.init_db()

    second = _sync()
    assert second["success"] is True and second["new_messages"] == 0

    c = sqlite3.connect(env)
    try:
        assert c.execute("SELECT COUNT(*) FROM emails").fetchone() == (4,)
        per_mailbox = dict(
            c.execute(
                "SELECT m.address, COUNT(e.id) FROM mailboxes m "
                "LEFT JOIN emails e ON e.mailbox_id = m.id GROUP BY m.address"
            ).fetchall()
        )
    finally:
        c.close()
    assert per_mailbox == {OWNER: 1, SECOND: 1, THIRD: 2}

    by_address = {m.address: m for m in mailboxes.for_owner(OWNER)}
    third = sync_cursor.get_cursor(OWNER, "INBOX", by_address[THIRD].id)
    assert (third.uidvalidity, third.last_uid) == (303, 6)  # its own server, its own position
    assert sync_cursor.get_cursor(OWNER, "INBOX", by_address[SECOND].id).uidvalidity == 202
    assert sync_cursor.get_cursor(OWNER, "INBOX", by_address[OWNER].id).uidvalidity == 101
    assert all(m.last_sync_at is not None and m.last_error is None for m in by_address.values())
