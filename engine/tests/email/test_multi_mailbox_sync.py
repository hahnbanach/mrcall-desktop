"""Sync per mailbox (M2): two mailboxes on one profile, fake IMAP servers.

Real ``SyncService``, real ``EmailArchiveManager``, real SQLite storage;
``build_imap_client`` is replaced by a factory that hands each mailbox its
own fake server. No password is written down: the fake never logs in.
"""

from __future__ import annotations

import asyncio
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from tests.email.fake_imap import FakeFolder, build_raw_message, make_client
from zylch.email import mailboxes, sync_cursor
from zylch.email.imap_client import IMAPError
from zylch.storage import database as dbm

OWNER = "owner@company.test"
SECOND = "pec@pec.company.test"


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
    from zylch.storage.storage import Storage

    store = Storage()
    primary = mailboxes.primary(OWNER)
    second = mailboxes.add_mailbox(OWNER, SECOND, secrets.token_urlsafe(12))
    yield {"db": db_path, "store": store, "primary": primary, "second": second}
    dbm.dispose_engine()


def _servers(monkeypatch, per_address: dict) -> None:
    """Replace ``build_imap_client`` with one fake server per mailbox address."""

    def build(mailbox):
        maker = per_address[mailbox.address]
        return maker(mailbox) if callable(maker) else maker

    monkeypatch.setattr(mailboxes, "build_imap_client", build)


def _sync(store, days_back=30, progress=None):
    from zylch.services.sync_service import SyncService

    svc = SyncService(owner_id=OWNER, supabase_storage=store)
    return asyncio.run(svc.sync_emails(days_back=days_back, on_progress=progress))


def _rows(db_path: str, sql: str, params=()):
    c = sqlite3.connect(db_path)
    try:
        return c.execute(sql, params).fetchall()
    finally:
        c.close()


def _inbox(uid_messages: dict, uidvalidity: int = 101) -> FakeFolder:
    folder = FakeFolder(uidvalidity=uidvalidity)
    for uid, raw in uid_messages.items():
        folder.add(uid, raw)
    return folder


# ─── the same message in two mailboxes ────────────────────────


def test_same_message_id_in_both_is_two_rows_processed_once(env, monkeypatch):
    store, db = env["store"], env["db"]
    when = datetime.now(timezone.utc) - timedelta(days=2)
    shared = build_raw_message("<shared@client.test>", subject="Order 42", date=when)
    # The service disconnects each client after its mailbox, so every run
    # gets a fresh client over the same (persistent) fake folders.
    folders = {OWNER: {"INBOX": _inbox({10: shared})}, SECOND: {"INBOX": _inbox({7: shared})}}
    _servers(
        monkeypatch,
        {
            OWNER: lambda mb: make_client(folders[OWNER], email_addr=OWNER),
            SECOND: lambda mb: make_client(folders[SECOND], email_addr=SECOND),
        },
    )

    result = _sync(store)
    assert result["success"] is True and result["errors"] == []
    assert [m["address"] for m in result["mailboxes"]] == [OWNER, SECOND]
    assert result["new_messages"] == 2

    rows = _rows(
        db,
        "SELECT mailbox_id, memory_processed_at, task_processed_at FROM emails "
        "WHERE message_id_header = '<shared@client.test>'",
    )
    assert len(rows) == 2
    by_mailbox = {r[0]: r for r in rows}
    assert by_mailbox[env["primary"].id][1] is None  # first copy: to be processed
    assert by_mailbox[env["second"].id][1] is not None  # second copy: born processed
    assert by_mailbox[env["second"].id][2] is not None

    # only the first copy reaches the memory and task pickers
    assert [e["id"] for e in store.get_unprocessed_emails(OWNER)] == [
        _rows(db, "SELECT id FROM emails WHERE mailbox_id = ?", (env["primary"].id,))[0][0]
    ]
    assert len(store.get_unprocessed_emails_for_task(OWNER)) == 1

    # a second run re-stores the first copy through the update path: still unprocessed
    result = _sync(store)
    assert result["success"] is True
    assert _rows(
        db,
        "SELECT memory_processed_at, task_processed_at FROM emails WHERE mailbox_id = ?",
        (env["primary"].id,),
    ) == [(None, None)]
    assert _rows(db, "SELECT COUNT(*) FROM emails") == [(2,)]


def test_restoring_the_first_copy_before_processing_leaves_it_unprocessed(env):
    store, db = env["store"], env["db"]
    row = {
        "id": "<m@client.test>",
        "thread_id": "t",
        "from_email": "customer@client.test",
        "subject": "hi",
        "date": datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc).isoformat(),
        "date_timestamp": 1756720800,
        "message_id_header": "<m@client.test>",
    }
    store.store_emails_batch(OWNER, [row], mailbox_id=env["primary"].id)
    store.store_emails_batch(OWNER, [row], mailbox_id=env["second"].id)
    store.store_emails_batch(OWNER, [dict(row, subject="edited")], mailbox_id=env["primary"].id)
    marks = dict(_rows(db, "SELECT mailbox_id, memory_processed_at FROM emails"))
    assert marks[env["primary"].id] is None and marks[env["second"].id] is not None
    assert _rows(db, "SELECT subject FROM emails WHERE mailbox_id = ?", (env["primary"].id,)) == [
        ("edited",)
    ]


# ─── independent floors, cursors and failures ─────────────────


def test_second_mailbox_first_sync_reaches_its_own_floor(env, monkeypatch):
    store, db = env["store"], env["db"]
    now = datetime.now(timezone.utc)
    newest_primary = now - timedelta(days=1)
    old_in_second = now - timedelta(days=20)
    _servers(
        monkeypatch,
        {
            OWNER: make_client(
                {"INBOX": _inbox({1: build_raw_message("<new@client.test>", date=newest_primary)})},
                email_addr=OWNER,
            ),
            SECOND: make_client(
                {"INBOX": _inbox({1: build_raw_message("<old@pec.test>", date=old_in_second)})},
                email_addr=SECOND,
            ),
        },
    )
    assert _sync(store, days_back=30)["success"] is True  # the primary holds newer mail
    stored = {r[0]: r[1] for r in _rows(db, "SELECT gmail_id, mailbox_id FROM emails")}
    assert stored["<new@client.test>"] == env["primary"].id
    assert stored["<old@pec.test>"] == env["second"].id  # 20 days old, inside its own window
    assert store.get_newest_email_date(OWNER, env["second"].id).day == old_in_second.day


def test_one_mailbox_failing_leaves_the_other_cursor_advanced(env, monkeypatch):
    store = env["store"]
    when = datetime.now(timezone.utc) - timedelta(days=1)
    good = make_client(
        {"INBOX": _inbox({41: build_raw_message("<ok@client.test>", date=when)})}, email_addr=OWNER
    )

    def broken(mailbox):
        client = make_client({"INBOX": _inbox({})}, email_addr=mailbox.address)

        def refuse():
            raise IMAPError("login refused by the server")

        client._ensure_connected = refuse
        return client

    _servers(monkeypatch, {OWNER: good, SECOND: broken})
    messages: list[str] = []
    result = _sync(store, progress=lambda pct, msg: messages.append(msg))

    assert result["success"] is True  # the primary synced
    assert [e["address"] for e in result["errors"]] == [SECOND]
    assert "login refused" in result["errors"][0]["error"]
    assert isinstance(result["errors"][0]["exception"], IMAPError)
    assert sync_cursor.get_cursor(OWNER, "INBOX", env["primary"].id).last_uid == 41
    assert sync_cursor.get_cursor(OWNER, "INBOX", env["second"].id) is None
    assert any(m.startswith(f"{SECOND}: failed:") for m in messages)
    assert any(m.startswith(f"{OWNER}: ") for m in messages)

    prim = mailboxes.primary(OWNER)
    second = mailboxes.by_id(OWNER, env["second"].id)
    assert prim.last_sync_at is not None and prim.last_error is None
    assert second.last_sync_at is None and "login refused" in second.last_error

    # the pipeline reports the failed mailbox by address without losing the primary's mail
    from zylch.services.error_messages import humanize_entry
    from zylch.services.process_pipeline import mailbox_error_entries

    entries = mailbox_error_entries(result)
    assert entries[0]["mailbox"] == SECOND and entries[0]["stage"] == "email_sync"
    humanized = humanize_entry(entries[0])
    assert humanized["mailbox"] == SECOND and humanized["detail"].startswith(f"{SECOND}: ")


def test_all_mailboxes_failing_raises_in_the_pipeline(env, monkeypatch):
    store = env["store"]

    def broken(mailbox):
        client = make_client({"INBOX": _inbox({})}, email_addr=mailbox.address)

        def refuse():
            raise IMAPError("login refused")

        client._ensure_connected = refuse
        return client

    _servers(monkeypatch, {OWNER: broken, SECOND: broken})
    from zylch.services.process_pipeline import _run_sync

    with pytest.raises(RuntimeError) as e:
        asyncio.run(_run_sync(OWNER, store, 30))
    assert OWNER in str(e.value) and SECOND in str(e.value)


# ─── a removed mailbox disappears from every query ────────────


def test_rows_of_a_removed_mailbox_are_hidden_everywhere(env):
    store, db = env["store"], env["db"]
    when = datetime.now(timezone.utc) - timedelta(days=1)

    def row(mid, mailbox, sender="customer@client.test", to=OWNER):
        return {
            "id": mid,
            "thread_id": mid,
            "from_email": sender,
            "to_email": to,
            "subject": f"invoice {mid}",
            "body_plain": f"invoice {mid}",
            "snippet": f"invoice {mid}",
            "date": when.isoformat(),
            "date_timestamp": int(when.timestamp()),
            "message_id_header": mid,
        }

    store.store_emails_batch(
        OWNER, [row("<p1@x>", env["primary"].id)], mailbox_id=env["primary"].id
    )
    store.store_emails_batch(
        OWNER,
        [row("<s1@x>", env["second"].id), row("<s2@x>", env["second"].id, sender=OWNER, to="c@x")],
        mailbox_id=env["second"].id,
    )
    with dbm.get_engine().begin() as conn:
        conn.exec_driver_sql(
            "UPDATE mailboxes SET removed_at = '2026-09-30 00:00:00' WHERE id = ?",
            (env["second"].id,),
        )

    assert [t["thread_id"] for t in store.list_inbox_threads(OWNER, OWNER)] == ["<p1@x>"]
    assert store.list_sent_threads(OWNER, OWNER) == []
    assert [t["thread_id"] for t in store.search_threads(OWNER, OWNER, "invoice", "all")] == [
        "<p1@x>"
    ]
    assert [e["thread_id"] for e in store.search_emails_flat(OWNER, OWNER, "invoice")] == ["<p1@x>"]
    assert [e["gmail_id"] for e in store.search_emails(OWNER, "invoice")] == ["<p1@x>"]
    assert store.get_thread_emails(OWNER, "<s1@x>") == []
    assert store.get_threads_in_window(OWNER, 30) == ["<p1@x>"]
    assert (
        store.get_sibling_threads_with_contact(OWNER, "customer@client.test", OWNER, "<p1@x>") == []
    )
    assert [e["id"] for e in store.get_unprocessed_emails(OWNER)] == [
        _rows(db, "SELECT id FROM emails WHERE gmail_id = '<p1@x>'")[0][0]
    ]
    assert len(store.get_unprocessed_emails_for_task(OWNER)) == 1
    assert _rows(db, "SELECT COUNT(*) FROM emails") == [(3,)]  # rows stay on disk

    from zylch.rpc.methods import _estimate_update_eta
    from zylch.storage.database import get_session
    from zylch.storage.models import Email
    from zylch.storage.storage import Storage

    assert isinstance(_estimate_update_eta(store, OWNER), str)  # the filtered counts run
    with get_session() as session:
        pending = (
            session.query(Email)
            .filter(Email.owner_id == OWNER, Storage.active_mailbox_filter(OWNER))
            .filter(Email.memory_processed_at.is_(None))
            .count()
        )
    assert pending == 1


# ─── the factory hands each mailbox its own client ────────────


def test_factory_caches_one_client_per_mailbox(env):
    from zylch.tools.config import ToolConfig
    from zylch.tools.factory import ToolFactory

    config = ToolConfig(owner_id=OWNER)
    a1 = ToolFactory._create_imap_client(config, "sync", mailbox=env["primary"])
    a2 = ToolFactory._create_imap_client(config, "sync", mailbox=env["primary"])
    b1 = ToolFactory._create_imap_client(config, "sync", mailbox=env["second"])
    env_client = ToolFactory._create_imap_client(config, "sync")
    assert a1 is a2
    assert b1 is not a1 and b1.email_addr == SECOND
    assert env_client is not b1 and env_client.email_addr == OWNER
