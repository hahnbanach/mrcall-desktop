"""M2 review repairs: classified all-mailbox failures, D2 across resets,
hidden twins, a raising progress callback, credential fingerprints.

Real SQLite storage and fake IMAP servers, as in ``test_multi_mailbox_sync``.
"""

from __future__ import annotations

import asyncio
import imaplib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from tests.email.fake_imap import FakeFolder, build_raw_message, make_client
from zylch.email import mailboxes
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

    yield {"db": db_path, "store": Storage(), "primary": mailboxes.primary(OWNER)}
    dbm.dispose_engine()


def _rows(db_path: str, sql: str, params=()):
    c = sqlite3.connect(db_path)
    try:
        return c.execute(sql, params).fetchall()
    finally:
        c.close()


def _inbox(uid_messages: dict) -> FakeFolder:
    folder = FakeFolder(uidvalidity=101)
    for uid, raw in uid_messages.items():
        folder.add(uid, raw)
    return folder


def _refusing(mailbox):
    """A client whose login is refused the way imaplib reports it."""
    client = make_client({"INBOX": _inbox({})}, email_addr=mailbox.address)

    def refuse():
        try:
            raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)")
        except imaplib.IMAP4.error as e:
            raise IMAPError(f"IMAP login for {mailbox.address} failed: {e}") from e

    client._ensure_connected = refuse
    return client


def _row(mid: str, when: datetime | None = None) -> dict:
    when = when or datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    return {
        "id": mid,
        "thread_id": "t",
        "from_email": "customer@client.test",
        "subject": mid,
        "date": when.isoformat(),
        "date_timestamp": int(when.timestamp()),
        "message_id_header": mid,
    }


# ─── finding 1: an all-mailbox failure stays classified ───────


def test_single_primary_auth_failure_is_classified_and_names_the_mailbox(env, monkeypatch):
    from zylch.services import process_pipeline
    from zylch.services.error_messages import humanize_entry

    monkeypatch.setattr(mailboxes, "build_imap_client", _refusing)
    monkeypatch.setattr(process_pipeline, "_run_whatsapp_sync", lambda o, s: {"skipped": True})
    errors: list = []
    result = asyncio.run(process_pipeline.run_sync_only(OWNER, days_back=30, errors_out=errors))

    assert result["sync_new"] == 0
    assert [e["mailbox"] for e in errors] == [OWNER]
    humanized = humanize_entry(errors[0])
    assert humanized["title"] == "Email login rejected"
    assert humanized["mailbox"] == OWNER and humanized["detail"].startswith(f"{OWNER}: ")


def test_all_failed_raise_is_chained_from_the_first_mailbox_exception(env, monkeypatch):
    from zylch.services.process_pipeline import _run_sync
    from zylch.services.sync_service import MailboxSyncFailed

    mailboxes.add_mailbox(OWNER, SECOND, secrets.token_urlsafe(12))
    monkeypatch.setattr(mailboxes, "build_imap_client", _refusing)
    with pytest.raises(MailboxSyncFailed) as e:
        asyncio.run(_run_sync(OWNER, env["store"], 30))
    assert isinstance(e.value.__cause__, IMAPError)
    assert isinstance(e.value.__cause__.__cause__, imaplib.IMAP4.error)
    assert [x["address"] for x in e.value.result["errors"]] == [OWNER, SECOND]


# ─── finding 2: D2 survives a reset; a twin in a removed mailbox does not hide ──


def test_reset_does_not_bring_the_second_copy_back(env):
    store, db = env["store"], env["db"]
    second = mailboxes.add_mailbox(OWNER, SECOND, secrets.token_urlsafe(12))
    store.store_emails_batch(OWNER, [_row("<m@client.test>")], mailbox_id=env["primary"].id)
    store.store_emails_batch(OWNER, [_row("<m@client.test>")], mailbox_id=second.id)
    assert len(store.get_unprocessed_emails(OWNER)) == 1

    store.reset_memory_processing_timestamps(OWNER)
    store.reset_task_processing_timestamps(OWNER)
    store.reset_processing_timestamps_for_period(
        owner_id=OWNER, days_back=3650, reset_memory=True, reset_task=True
    )
    assert _rows(db, "SELECT COUNT(*) FROM emails WHERE memory_processed_at IS NULL") == [(2,)]

    picked = store.get_unprocessed_emails(OWNER)
    first_id = _rows(db, "SELECT id FROM emails WHERE mailbox_id = ?", (env["primary"].id,))[0][0]
    assert [e["id"] for e in picked] == [first_id]
    assert [e["id"] for e in store.get_unprocessed_emails_for_task(OWNER)] == [first_id]

    from zylch.rpc.methods import _pending_email_counts

    assert _pending_email_counts(OWNER) == {
        "pending_memory": 1,
        "pending_tasks": 1,
        "pending_any": 1,
        "total": 2,
    }


def test_copy_whose_only_twin_is_in_a_removed_mailbox_is_processed(env):
    store, db = env["store"], env["db"]
    second = mailboxes.add_mailbox(OWNER, SECOND, secrets.token_urlsafe(12))
    store.store_emails_batch(OWNER, [_row("<m@client.test>")], mailbox_id=second.id)  # first
    with dbm.get_engine().begin() as conn:
        conn.exec_driver_sql(
            "UPDATE mailboxes SET removed_at = '2026-09-30 00:00:00' WHERE id = ?", (second.id,)
        )
    # the same message now arrives in the primary: not "already held"
    store.store_emails_batch(OWNER, [_row("<m@client.test>")], mailbox_id=env["primary"].id)
    marks = dict(_rows(db, "SELECT mailbox_id, memory_processed_at FROM emails"))
    assert marks[env["primary"].id] is None
    primary_row = _rows(db, "SELECT id FROM emails WHERE mailbox_id = ?", (env["primary"].id,))[0][
        0
    ]
    assert [e["id"] for e in store.get_unprocessed_emails(OWNER)] == [primary_row]
    assert [e["id"] for e in store.get_unprocessed_emails_for_task(OWNER)] == [primary_row]

    from zylch.rpc.methods import _pending_email_counts

    assert _pending_email_counts(OWNER)["pending_any"] == 1


def test_thread_history_shows_one_copy_and_no_hidden_mailbox(env):
    from zylch.storage.database import get_session
    from zylch.workers.thread_presenter import build_thread_history

    store = env["store"]
    second = mailboxes.add_mailbox(OWNER, SECOND, secrets.token_urlsafe(12))
    store.store_emails_batch(OWNER, [_row("<m@client.test>")], mailbox_id=env["primary"].id)
    store.store_emails_batch(OWNER, [_row("<m@client.test>")], mailbox_id=second.id)
    later = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
    store.store_emails_batch(OWNER, [_row("<only-second@x>", later)], mailbox_id=second.id)

    with get_session() as session:
        history = build_thread_history(session, OWNER, "t", OWNER)
    # the history renders one dated block per message: the shared one once
    assert history.count("[2026-09-01 10:00]") == 1 and "[2026-09-02 10:00]" in history

    with dbm.get_engine().begin() as conn:
        conn.exec_driver_sql(
            "UPDATE mailboxes SET removed_at = '2026-09-30 00:00:00' WHERE id = ?", (second.id,)
        )
    with get_session() as session:
        history = build_thread_history(session, OWNER, "t", OWNER)
    assert history.count("[2026-09-01 10:00]") == 1 and "[2026-09-02 10:00]" not in history


# ─── finding 6: a raising progress callback stops nothing ──────


def test_a_raising_progress_callback_does_not_stop_the_other_mailboxes(env, monkeypatch):
    from zylch.services.sync_service import SyncService

    store, db = env["store"], env["db"]
    second = mailboxes.add_mailbox(OWNER, SECOND, secrets.token_urlsafe(12))
    when = datetime.now(timezone.utc) - timedelta(days=1)
    good = {"INBOX": _inbox({41: build_raw_message("<ok@pec.test>", date=when)})}

    def build(mailbox):
        if mailbox.address == OWNER:
            return _refusing(mailbox)
        return make_client(good, email_addr=SECOND)

    monkeypatch.setattr(mailboxes, "build_imap_client", build)

    def explode(pct, msg):
        raise RuntimeError("renderer went away")

    svc = SyncService(owner_id=OWNER, supabase_storage=store)
    result = asyncio.run(svc.sync_emails(days_back=30, on_progress=explode))
    assert result["success"] is True
    assert [e["address"] for e in result["errors"]] == [OWNER]
    assert _rows(db, "SELECT mailbox_id FROM emails") == [(second.id,)]
    assert mailboxes.by_id(OWNER, second.id).last_sync_at is not None
    assert mailboxes.primary(OWNER).last_error


# ─── finding 5: a password change rebuilds the cached client ───


def test_factory_rebuilds_the_client_when_the_secret_changes(env):
    from zylch.tools.config import ToolConfig
    from zylch.tools.factory import ToolFactory

    config = ToolConfig(owner_id=OWNER)
    box = mailboxes.add_mailbox(OWNER, SECOND, secrets.token_urlsafe(12))
    first = ToolFactory._create_imap_client(config, "sync", mailbox=box)
    assert ToolFactory._create_imap_client(config, "sync", mailbox=box) is first
    fingerprint = mailboxes.credential_fingerprint(box)
    assert box.address not in fingerprint and len(fingerprint) == 64

    with dbm.get_engine().begin() as conn:
        conn.exec_driver_sql(
            "UPDATE mailboxes SET removed_at = '2026-09-30 00:00:00' WHERE id = ?", (box.id,)
        )
    revived = mailboxes.add_mailbox(OWNER, SECOND, secrets.token_urlsafe(12))  # new password
    assert revived.id == box.id
    rebuilt = ToolFactory._create_imap_client(config, "sync", mailbox=revived)
    assert rebuilt is not first and rebuilt.password != first.password


# ─── third pass: the first-copy rule is indexed; an empty mailbox list still reports ──


@pytest.mark.parametrize("stage", ["memory", "task"])
def test_picker_query_uses_the_message_id_index(env, stage):
    """The pickers correlate on (owner_id, message_id_header): the plan must
    SEARCH the twin through ``ix_emails_owner_message_id_header``, never scan."""
    from sqlalchemy.dialects import sqlite as sqlite_dialect

    from zylch.storage.database import get_session
    from zylch.storage.models import Email
    from zylch.storage.storage import Storage

    with get_session() as session:
        statement = (
            session.query(Email.id)
            .filter(*Storage.unprocessed_email_filters(OWNER, stage))
            .statement.compile(
                dialect=sqlite_dialect.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
    plan = "\n".join(r[-1] for r in _rows(env["db"], f"EXPLAIN QUERY PLAN {statement}"))
    assert "USING INDEX ix_emails_owner_message_id_header" in plan, plan
    assert "SCAN emails_1" not in plan, plan  # the twin is searched, never scanned


def test_migrated_and_fresh_files_both_carry_the_message_id_index(env):
    names = {r[0] for r in _rows(env["db"], "SELECT name FROM sqlite_master WHERE type='index'")}
    assert "ix_emails_owner_message_id_header" in names


def test_no_mailbox_row_still_reports_the_email_stage(env, monkeypatch):
    """Env credentials set but no mailbox row: the stage entry, never nothing."""
    from zylch.services.process_pipeline import sync_failure_entries
    from zylch.services.sync_service import MailboxSyncFailed

    monkeypatch.setattr(mailboxes, "for_owner", lambda owner_id, include_removed=False: [])
    from zylch.services.process_pipeline import _run_sync

    with pytest.raises(MailboxSyncFailed) as e:
        asyncio.run(_run_sync(OWNER, env["store"], 30))
    entries = sync_failure_entries(e.value)
    assert len(entries) == 1 and entries[0]["stage"] == "email_sync"
    assert entries[0]["error"] is e.value and entries[0].get("mailbox") is None


def test_restoring_the_first_copy_after_its_twin_keeps_its_id_and_birth(env):
    """The upsert never rewrites `id` or `created_at`: a re-stored first copy
    stays the first copy, so exactly one row is picked and links still hold."""
    store, db = env["store"], env["db"]
    second = mailboxes.add_mailbox(OWNER, SECOND, secrets.token_urlsafe(12))
    store.store_emails_batch(OWNER, [_row("<m@client.test>")], mailbox_id=env["primary"].id)
    first_id, first_born = _rows(
        db, "SELECT id, created_at FROM emails WHERE mailbox_id = ?", (env["primary"].id,)
    )[0]
    store.store_emails_batch(OWNER, [_row("<m@client.test>")], mailbox_id=second.id)
    store.store_emails_batch(
        OWNER, [dict(_row("<m@client.test>"), subject="edited")], mailbox_id=env["primary"].id
    )
    assert _rows(
        db, "SELECT id, created_at, subject FROM emails WHERE mailbox_id = ?", (env["primary"].id,)
    ) == [(first_id, first_born, "edited")]
    assert [e["id"] for e in store.get_unprocessed_emails(OWNER)] == [first_id]
    assert [e["id"] for e in store.get_unprocessed_emails_for_task(OWNER)] == [first_id]
