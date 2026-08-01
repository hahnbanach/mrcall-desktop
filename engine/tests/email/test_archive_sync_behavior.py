"""End-to-end behaviour of the cursor-driven archive sync.

Real EmailArchiveManager, real IMAPClient, real SQLite storage, fake
IMAP server. Each test is one unit of behaviour the July 2026 gap
needed and did not have.

The shape being reproduced: the archive holds a NEWER message, an OLDER
message was never ingested, and the daemon runs every five minutes. The
old floor (`newest stored - 1 day`, day granularity) sat above the
missed message, so every run reported success and found nothing.
"""

from datetime import datetime, timedelta, timezone

import pytest

from tests.email.fake_imap import FakeFolder, build_raw_message, make_client
from zylch.email import sync_cursor

OWNER = "support@example.com"


@pytest.fixture
def storage(tmp_path, monkeypatch):
    db_path = tmp_path / "archive_sync.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))

    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()

    # Embeddings are irrelevant here and would make every store a model
    # call; the sync path under test never looks at them.
    import zylch.storage.storage as storage_mod

    monkeypatch.setattr(storage_mod, "_generate_email_embedding", lambda email: None)

    from zylch.storage.storage import Storage

    yield Storage()
    db_mod.dispose_engine()


def _archive_row(message_id: str, when: datetime, subject: str = "Already stored"):
    return {
        "id": message_id,
        "thread_id": message_id,
        "from_email": "customer@example.com",
        "from_name": "Customer",
        "to_email": OWNER,
        "cc_email": "",
        "subject": subject,
        "date": when.isoformat(),
        "date_timestamp": int(when.timestamp()),
        "snippet": subject,
        "body_plain": subject,
        "body_html": "",
        "labels": [],
        "message_id_header": message_id,
        "in_reply_to": "",
        "references": "",
    }


def _manager(client, storage):
    from zylch.tools.email_archive import EmailArchiveManager

    return EmailArchiveManager(gmail_client=client, owner_id=OWNER, supabase_storage=storage)


def _stored_ids(storage):
    return {e["gmail_id"] for e in storage.get_emails(OWNER, limit=500)}


def _criteria_issued(client, folder="INBOX"):
    """The SEARCH criteria the client actually sent for a folder."""
    issued = []
    selected = None
    for command in client._conn.commands:
        if command[0] == "SELECT":
            selected = command[1]
        elif command[0] == "UID" and command[1] == "SEARCH" and selected == folder:
            issued.append(command[-1])
    return issued


# ---------------------------------------------------------------------
# The July shape
# ---------------------------------------------------------------------


def test_older_missed_message_is_found_despite_a_newer_stored_one(storage):
    """The regression, reproduced: newer stored message + older hole.

    Old behaviour: floor = newest stored - 1 day, so a message three
    days older than the newest row was outside every subsequent search.
    New behaviour: the floor is the overlap window (7 days by default)
    and, from the second run onwards, a UID cursor.
    """
    now = datetime.now(timezone.utc)
    newest_stored = now - timedelta(days=1)
    missed = now - timedelta(days=4)
    oldest_stored = now - timedelta(days=100)

    # The hole is unreachable under the old floor by construction.
    assert missed < newest_stored - timedelta(days=1)

    storage.store_emails_batch(
        OWNER,
        [
            _archive_row("<old@example.com>", oldest_stored),
            _archive_row("<newest@example.com>", newest_stored),
        ],
    )

    inbox = FakeFolder(uidvalidity=101)
    inbox.add(41, build_raw_message("<missed@example.com>", subject="Never ingested", date=missed))
    inbox.add(42, build_raw_message("<newest@example.com>", date=newest_stored))
    client = make_client({"INBOX": inbox})

    result = _manager(client, storage).incremental_sync()

    assert result["success"] is True
    assert "<missed@example.com>" in _stored_ids(storage)
    assert result["messages_added"] == 1

    # The floor really was the overlap window, not `newest - 1 day`.
    criteria = _criteria_issued(client)[0]
    floor_used = datetime.strptime(criteria.split('"')[1], "%d-%b-%Y").replace(tzinfo=timezone.utc)
    assert floor_used <= missed
    assert floor_used < newest_stored - timedelta(days=1)


def test_second_run_is_cursor_driven_and_idempotent(storage):
    now = datetime.now(timezone.utc)
    inbox = FakeFolder(uidvalidity=101)
    inbox.add(41, build_raw_message("<a@example.com>", date=now - timedelta(days=2)))
    inbox.add(42, build_raw_message("<b@example.com>", date=now - timedelta(days=1)))
    client = make_client({"INBOX": inbox})
    manager = _manager(client, storage)

    first = manager.incremental_sync()
    assert first["messages_added"] == 2
    assert sync_cursor.get_cursor(OWNER, "INBOX").last_uid == 42

    second = manager.incremental_sync()
    assert second["messages_added"] == 0
    assert second["folders"]["INBOX"]["missing"] == 0
    assert "(OR UID 43:*" in _criteria_issued(client)[1]


def test_cursor_catches_a_new_message_whose_date_is_outside_the_window(storage):
    """UID range, not dates, is what makes the sync gap-proof.

    A message can enter a folder with a Date far in the past (a late
    delivery, a message moved in from another mailbox). The date window
    would never see it; the UID cursor does.
    """
    now = datetime.now(timezone.utc)
    inbox = FakeFolder(uidvalidity=101)
    inbox.add(41, build_raw_message("<a@example.com>", date=now - timedelta(days=1)))
    client = make_client({"INBOX": inbox})
    manager = _manager(client, storage)

    manager.incremental_sync()
    assert sync_cursor.get_cursor(OWNER, "INBOX").last_uid == 41

    inbox.add(
        42,
        build_raw_message("<late@example.com>", date=now - timedelta(days=60)),
    )
    result = manager.incremental_sync()

    assert "<late@example.com>" in _stored_ids(storage)
    assert result["messages_added"] == 1


# ---------------------------------------------------------------------
# Folder scope
# ---------------------------------------------------------------------


def test_message_that_never_touched_inbox_is_ingested_from_all_mail(storage):
    """Archived/filtered mail was invisible forever under INBOX+Sent."""
    now = datetime.now(timezone.utc)
    inbox = FakeFolder(uidvalidity=101)
    inbox.add(10, build_raw_message("<inboxed@example.com>", date=now - timedelta(hours=2)))

    archive = FakeFolder(uidvalidity=303)
    archive.add(90, build_raw_message("<inboxed@example.com>", date=now - timedelta(hours=2)))
    archive.add(
        91,
        build_raw_message("<filtered@example.com>", subject="Filtered", date=now),
    )
    client = make_client({"INBOX": inbox, '"[Gmail]/All Mail"': archive})

    result = _manager(client, storage).incremental_sync()

    assert "<filtered@example.com>" in _stored_ids(storage)
    assert result["success"] is True


def test_same_message_in_two_folders_is_stored_once(storage):
    """Dedup is by Message-ID, the archive's own key."""
    now = datetime.now(timezone.utc)
    raw = build_raw_message("<shared@example.com>", date=now)
    inbox = FakeFolder(uidvalidity=101, messages={10: raw})
    archive = FakeFolder(uidvalidity=303, messages={90: raw})
    client = make_client({"INBOX": inbox, '"[Gmail]/All Mail"': archive})

    result = _manager(client, storage).incremental_sync()

    rows = [
        e for e in storage.get_emails(OWNER, limit=50) if e["gmail_id"] == "<shared@example.com>"
    ]
    assert len(rows) == 1
    assert result["folders"]['"[Gmail]/All Mail"']["missing"] == 0


def test_unsent_drafts_are_not_ingested(storage):
    """An unsent draft in All Mail must never read as a reply we sent."""
    now = datetime.now(timezone.utc)
    archive = FakeFolder(uidvalidity=303)
    archive.add(90, build_raw_message("<real@example.com>", date=now))
    archive.add(91, build_raw_message("<draft@example.com>", subject="Draft reply", date=now))
    archive.drafts = {91}
    client = make_client({"INBOX": FakeFolder(uidvalidity=101), '"[Gmail]/All Mail"': archive})

    _manager(client, storage).incremental_sync()

    stored = _stored_ids(storage)
    assert "<real@example.com>" in stored
    assert "<draft@example.com>" not in stored


# ---------------------------------------------------------------------
# Loud failures
# ---------------------------------------------------------------------


def test_failed_search_does_not_advance_the_cursor_and_logs_error(storage, caplog):
    now = datetime.now(timezone.utc)
    inbox = FakeFolder(uidvalidity=101)
    inbox.add(41, build_raw_message("<a@example.com>", date=now - timedelta(days=1)))
    client = make_client({"INBOX": inbox})
    manager = _manager(client, storage)

    manager.incremental_sync()
    assert sync_cursor.get_cursor(OWNER, "INBOX").last_uid == 41

    inbox.add(42, build_raw_message("<b@example.com>", date=now))
    inbox.search_fails = True

    with caplog.at_level("ERROR"):
        result = manager.incremental_sync()

    assert result["success"] is False
    assert result["folder_errors"][0]["folder"] == "INBOX"
    assert sync_cursor.get_cursor(OWNER, "INBOX").last_uid == 41
    assert "<b@example.com>" not in _stored_ids(storage)
    assert any("cursor NOT advanced" in r.message for r in caplog.records)

    # ...and the very next healthy run picks the message up.
    inbox.search_fails = False
    assert manager.incremental_sync()["messages_added"] == 1


def test_partial_fetch_failure_is_counted_and_holds_the_cursor(storage, caplog):
    now = datetime.now(timezone.utc)
    inbox = FakeFolder(uidvalidity=101)
    inbox.add(41, build_raw_message("<a@example.com>", date=now - timedelta(days=2)))
    inbox.add(42, build_raw_message("<broken@example.com>", date=now - timedelta(days=1)))
    inbox.add(43, build_raw_message("<c@example.com>", date=now))
    inbox.fetch_errors = {42}
    client = make_client({"INBOX": inbox})
    manager = _manager(client, storage)

    with caplog.at_level("ERROR"):
        result = manager.incremental_sync()

    folder_result = result["folders"]["INBOX"]
    assert folder_result["failures"] == 1
    assert 42 in (folder_result["fetch_failed_uids"] + folder_result["unresolved_uids"])
    # The cursor stops below the failure even though uid 43 was stored.
    assert sync_cursor.get_cursor(OWNER, "INBOX").last_uid == 41
    assert any("holding the cursor at 41" in r.message for r in caplog.records)

    inbox.fetch_errors = set()
    manager.incremental_sync()
    assert "<broken@example.com>" in _stored_ids(storage)
    assert sync_cursor.get_cursor(OWNER, "INBOX").last_uid == 43


def test_store_failure_holds_the_cursor(storage, caplog, monkeypatch):
    """A batch that fails to persist must not be treated as ingested."""
    now = datetime.now(timezone.utc)
    inbox = FakeFolder(uidvalidity=101)
    inbox.add(41, build_raw_message("<a@example.com>", date=now))
    client = make_client({"INBOX": inbox})
    manager = _manager(client, storage)

    def explode(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(storage, "store_emails_batch", explode)
    with caplog.at_level("ERROR"):
        result = manager.incremental_sync()

    assert result["folders"]["INBOX"]["failures"] == 1
    assert sync_cursor.get_cursor(OWNER, "INBOX").last_uid == 40
    assert any("cursor will not advance past uid 41" in r.message for r in caplog.records)


def test_secondary_folder_failure_does_not_fail_the_whole_sync(storage, caplog):
    """Losing All Mail degrades coverage; losing INBOX is a failure."""
    now = datetime.now(timezone.utc)
    inbox = FakeFolder(uidvalidity=101)
    inbox.add(10, build_raw_message("<a@example.com>", date=now))
    archive = FakeFolder(uidvalidity=303)
    archive.select_fails = True
    client = make_client({"INBOX": inbox, '"[Gmail]/All Mail"': archive})

    with caplog.at_level("ERROR"):
        result = _manager(client, storage).incremental_sync()

    assert result["success"] is True
    assert result["messages_added"] == 1
    assert [e["folder"] for e in result["folder_errors"]] == ['"[Gmail]/All Mail"']


# ---------------------------------------------------------------------
# UIDVALIDITY
# ---------------------------------------------------------------------


def test_uidvalidity_change_resets_the_cursor_loudly(storage, caplog):
    """Renumbering makes every stored UID meaningless — say so, re-seed."""
    now = datetime.now(timezone.utc)
    inbox = FakeFolder(uidvalidity=101)
    inbox.add(41, build_raw_message("<a@example.com>", date=now - timedelta(days=1)))
    client = make_client({"INBOX": inbox})
    manager = _manager(client, storage)

    manager.incremental_sync()
    assert sync_cursor.get_cursor(OWNER, "INBOX").uidvalidity == 101

    # The server renumbers: same messages, brand new UID space.
    inbox.uidvalidity = 999
    inbox.messages = {
        7: build_raw_message("<a@example.com>", date=now - timedelta(days=1)),
        8: build_raw_message("<after-renumber@example.com>", date=now),
    }

    with caplog.at_level("ERROR"):
        result = manager.incremental_sync()

    assert any("UIDVALIDITY CHANGED" in r.message for r in caplog.records)
    cursor = sync_cursor.get_cursor(OWNER, "INBOX")
    assert cursor.uidvalidity == 999
    assert cursor.last_uid == 8
    assert "<after-renumber@example.com>" in _stored_ids(storage)
    assert result["messages_added"] == 1


def test_empty_folder_anchors_the_cursor_at_uidnext(storage):
    """A seed run that matches nothing still records a position."""
    client = make_client({"INBOX": FakeFolder(uidvalidity=101)})
    result = _manager(client, storage).incremental_sync()

    assert result["success"] is True
    cursor = sync_cursor.get_cursor(OWNER, "INBOX")
    assert cursor is not None
    assert cursor.last_uid == 0
