"""Profile step ``0003_emails_mailbox`` on a pre-mailbox ``zylch.db``.

Starts from the shape a live profile has today — ``emails`` unique on
``(owner_id, gmail_id)`` with rows of the current address, of a former
address and of ``local-user``, plus a v1 sync cursor table — and boots.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from zylch.email import mailboxes, sync_cursor
from zylch.storage import database as dbm
from zylch.storage.migrations import pending_step_ids, unrecord_step
from zylch.storage.step_emails_mailbox import NEW_CONSTRAINT, STEP_ID

OWNER = "current@company.test"
FORMER = "old@company.test"
LOCAL = "local-user"
GHOST = "ghost@company.test"  # has cursors but no mail


def _legacy_db(path: str, *, owners: dict[str, list[str]]) -> None:
    """A pre-0003 profile file: old ``emails`` shape, v1 cursor table.

    ``owners`` maps owner_id -> list of row ids to insert. Columns added
    after the table was first created (pin/read/archive flags) are left
    out on purpose: the column ensure pass adds them before the step runs
    and the rebuild copies only the columns the old table holds.
    """
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE emails (
            id VARCHAR(36) NOT NULL PRIMARY KEY,
            owner_id TEXT NOT NULL,
            gmail_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            from_email TEXT, from_name TEXT, to_email TEXT, cc_email TEXT, subject TEXT,
            date DATETIME NOT NULL, date_timestamp INTEGER, snippet TEXT,
            body_plain TEXT, body_html TEXT, labels TEXT, message_id_header TEXT,
            in_reply_to TEXT, "references" TEXT, created_at DATETIME, updated_at DATETIME,
            read_events JSON, memory_processed_at DATETIME, embedding BLOB,
            task_processed_at DATETIME, is_auto_reply BOOLEAN,
            CONSTRAINT emails_owner_gmail_unique UNIQUE (owner_id, gmail_id)
        );
        CREATE INDEX ix_emails_owner_id ON emails (owner_id);
        CREATE TABLE email_sync_cursor (
            owner_id TEXT NOT NULL, folder TEXT NOT NULL, uidvalidity INTEGER NOT NULL,
            last_uid INTEGER NOT NULL DEFAULT 0, last_synced_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, PRIMARY KEY (owner_id, folder)
        );
        """)
    for owner, ids in owners.items():
        for i, row_id in enumerate(ids):
            c.execute(
                "INSERT INTO emails (id, owner_id, gmail_id, thread_id, from_email, subject, "
                "date, date_timestamp, message_id_header, memory_processed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row_id,
                    owner,
                    f"<{row_id}@mail.test>",
                    f"thread-{owner}",
                    "customer@client.test",
                    f"Subject {i}",
                    "2026-09-01 10:00:00",
                    1756720800 + i,
                    f"<{row_id}@mail.test>",
                    "2026-09-02 10:00:00" if i == 0 else None,
                ),
            )
    for owner, uid in ((OWNER, 42), (FORMER, 9), (GHOST, 1)):
        c.execute(
            "INSERT INTO email_sync_cursor VALUES (?, 'INBOX', 101, ?, 't', 't')", (owner, uid)
        )
    c.commit()
    c.close()


def _rows(db_path: str, sql: str, params=()):
    c = sqlite3.connect(db_path)
    try:
        return c.execute(sql, params).fetchall()
    finally:
        c.close()


def _schema(db_path: str) -> tuple:
    cols = _rows(db_path, "PRAGMA table_info(emails)")
    ddl = _rows(db_path, "SELECT sql FROM sqlite_master WHERE name='emails'")[0][0]
    idx = _rows(db_path, "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='emails'")
    return (
        tuple((c[1], c[2].upper(), c[3]) for c in cols),
        NEW_CONSTRAINT in ddl,
        tuple(sorted(n[0] for n in idx if not n[0].startswith("sqlite_"))),
    )


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    db_path = str(tmp_path / "zylch.db")
    _legacy_db(db_path, owners={OWNER: ["e1", "e2"], FORMER: ["e3"], LOCAL: ["e4"]})
    monkeypatch.setenv("ZYLCH_DB_PATH", db_path)
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    monkeypatch.setenv("IMAP_HOST", "imap.company.test")
    monkeypatch.setenv("IMAP_PORT", "993")
    monkeypatch.setenv("SMTP_HOST", "smtp.company.test")
    monkeypatch.setenv("SMTP_PORT", "587")
    dbm.dispose_engine()
    yield db_path
    dbm.dispose_engine()


def _backups(db_path: str) -> list[str]:
    return [name for name in os.listdir(os.path.join(os.path.dirname(db_path), "backups"))
            if STEP_ID in name]


def test_boot_creates_mailboxes_and_stamps_every_row(legacy):
    dbm.init_db()

    boxes = {
        r[1]: r
        for r in _rows(
            legacy,
            "SELECT id, address, is_primary, secret, imap_host, imap_port, smtp_host, smtp_port, "
            "removed_at, owner_id FROM mailboxes",
        )
    }
    assert set(boxes) == {OWNER, FORMER, LOCAL}
    prim = boxes[OWNER]
    assert prim[2] == 1 and prim[3] is None and prim[8] is None  # primary, no secret, active
    assert prim[4:8] == ("imap.company.test", 993, "smtp.company.test", 587)
    assert boxes[FORMER][2] == 0 and boxes[FORMER][8] is not None  # hidden
    assert boxes[LOCAL][2] == 0 and boxes[LOCAL][8] is not None  # hidden: owner has an address

    rows = dict(_rows(legacy, "SELECT id, mailbox_id FROM emails ORDER BY id"))
    assert set(rows) == {"e1", "e2", "e3", "e4"}  # ids preserved
    assert rows["e1"] == rows["e2"] == prim[0]
    assert rows["e3"] == boxes[FORMER][0] and rows["e4"] == boxes[LOCAL][0]
    assert _rows(legacy, "SELECT memory_processed_at FROM emails WHERE id='e1'")[0][0]
    assert _rows(legacy, "SELECT COUNT(*) FROM emails WHERE mailbox_id IS NULL") == [(0,)]

    cols, has_constraint, indexes = _schema(legacy)
    assert has_constraint
    assert ("mailbox_id", "VARCHAR(36)", 1) in cols
    assert "original_message_id" in {c[0] for c in cols} and "pec_markers" in {c[0] for c in cols}
    assert indexes == (
        "ix_emails_archived_at",
        "ix_emails_deleted_at",
        "ix_emails_has_attachments",
        "ix_emails_mailbox_id",
        "ix_emails_owner_id",
        "ix_emails_owner_message_id_header",
        "ix_emails_pinned_at",
        "ix_emails_read_at",
    )

    # the loader sees the same thing
    assert mailboxes.primary(OWNER).id == prim[0]
    assert [m.address for m in mailboxes.for_owner(OWNER)] == [OWNER]
    assert mailboxes.for_owner(FORMER) == []
    assert mailboxes.for_owner(FORMER, include_removed=True)[0].removed

    assert pending_step_ids(dbm.get_engine(), dbm.PROFILE_STEPS) == []
    backups = _backups(legacy)
    assert len(backups) == 1 and STEP_ID in backups[0]


def test_cursors_follow_their_mailbox_and_orphans_are_dropped(legacy):
    dbm.init_db()
    prim = mailboxes.primary(OWNER).id
    former = mailboxes.for_owner(FORMER, include_removed=True)[0].id

    v2 = _rows(legacy, "SELECT owner_id, mailbox_id, folder, last_uid FROM email_sync_cursor_v2")
    assert sorted(v2) == sorted([(OWNER, prim, "INBOX", 42), (FORMER, former, "INBOX", 9)])
    assert not _rows(legacy, "SELECT name FROM sqlite_master WHERE name='email_sync_cursor'")
    assert sync_cursor.get_cursor(OWNER, "INBOX", prim).last_uid == 42
    assert sync_cursor.get_cursor(OWNER, "INBOX", prim).mailbox_id == prim


def test_migrated_shape_equals_fresh_shape(legacy, tmp_path, monkeypatch):
    dbm.init_db()
    migrated = _schema(legacy)

    fresh_path = str(tmp_path / "fresh" / "zylch.db")
    monkeypatch.setenv("ZYLCH_DB_PATH", fresh_path)
    dbm.dispose_engine()
    dbm.init_db()
    assert _schema(fresh_path) == migrated


def test_second_boot_and_forced_rerun_are_no_ops(legacy):
    dbm.init_db()
    snapshot = (
        _rows(legacy, "SELECT id, mailbox_id, thread_id FROM emails ORDER BY id"),
        _rows(legacy, "SELECT id, address, is_primary, removed_at FROM mailboxes ORDER BY id"),
        _rows(legacy, "SELECT * FROM email_sync_cursor_v2 ORDER BY owner_id"),
    )
    dbm.dispose_engine()
    dbm.init_db()  # second boot
    unrecord_step(dbm.get_engine(), STEP_ID)  # the rollback window: forward runs again
    dbm.dispose_engine()
    dbm.init_db()
    assert (
        _rows(legacy, "SELECT id, mailbox_id, thread_id FROM emails ORDER BY id"),
        _rows(legacy, "SELECT id, address, is_primary, removed_at FROM mailboxes ORDER BY id"),
        _rows(legacy, "SELECT * FROM email_sync_cursor_v2 ORDER BY owner_id"),
    ) == snapshot
    assert _rows(legacy, "SELECT COUNT(*) FROM mailboxes") == [(3,)]


def test_profile_without_address_gets_no_primary(tmp_path, monkeypatch):
    db_path = str(tmp_path / "zylch.db")
    _legacy_db(db_path, owners={LOCAL: ["e1", "e2"], FORMER: ["e3"]})
    monkeypatch.setenv("ZYLCH_DB_PATH", db_path)
    monkeypatch.delenv("EMAIL_ADDRESS", raising=False)
    dbm.dispose_engine()
    try:
        dbm.init_db()
        assert _rows(db_path, "SELECT COUNT(*) FROM mailboxes WHERE is_primary = 1") == [(0,)]
        local = mailboxes.for_owner(LOCAL)
        assert len(local) == 1 and not local[0].is_primary  # current owner stays visible
        assert mailboxes.primary(LOCAL) is None
        assert mailboxes.for_owner(FORMER) == []
        stamped = dict(_rows(db_path, "SELECT id, mailbox_id FROM emails"))
        assert stamped["e1"] == stamped["e2"] == local[0].id
        assert stamped["e3"] == mailboxes.for_owner(FORMER, include_removed=True)[0].id
        assert pending_step_ids(dbm.get_engine(), dbm.PROFILE_STEPS) == []
    finally:
        dbm.dispose_engine()


def test_empty_profile_has_empty_mailbox_list_without_address(tmp_path, monkeypatch):
    db_path = str(tmp_path / "zylch.db")
    monkeypatch.setenv("ZYLCH_DB_PATH", db_path)
    monkeypatch.delenv("EMAIL_ADDRESS", raising=False)
    dbm.dispose_engine()
    try:
        dbm.init_db()
        assert _rows(db_path, "SELECT COUNT(*) FROM mailboxes") == [(0,)]
        assert mailboxes.for_owner(LOCAL) == []
    finally:
        dbm.dispose_engine()


# ─── owner identity is the runtime's, byte for byte ───────────


def test_current_address_is_taken_raw_like_the_runtime_owner(tmp_path, monkeypatch):
    """EMAIL_ADDRESS with trailing whitespace: the runtime keys rows by the raw
    value, so the primary row carries it and the user's rows stay visible."""
    raw = "a@x.test "
    db_path = str(tmp_path / "zylch.db")
    _legacy_db(db_path, owners={raw: ["e1"], FORMER: ["e2"]})
    monkeypatch.setenv("ZYLCH_DB_PATH", db_path)
    monkeypatch.setenv("EMAIL_ADDRESS", raw)
    dbm.dispose_engine()
    try:
        dbm.init_db()
        prim = mailboxes.primary(raw)
        assert prim is not None and prim.address == raw
        assert mailboxes.primary(raw.strip()) is None
        assert _rows(db_path, "SELECT COUNT(*) FROM mailboxes") == [(2,)]
        stamped = dict(_rows(db_path, "SELECT id, mailbox_id FROM emails"))
        assert stamped["e1"] == prim.id
        assert stamped["e2"] == mailboxes.for_owner(FORMER, include_removed=True)[0].id
    finally:
        dbm.dispose_engine()


def test_empty_owner_id_rows_migrate_into_a_hidden_mailbox(tmp_path, monkeypatch):
    """A legacy row with owner_id '' is a real former owner, not a NULL to skip."""
    db_path = str(tmp_path / "zylch.db")
    _legacy_db(db_path, owners={OWNER: ["e1"], "": ["e2"]})
    monkeypatch.setenv("ZYLCH_DB_PATH", db_path)
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    dbm.dispose_engine()
    try:
        dbm.init_db()
        empty = mailboxes.for_owner("", include_removed=True)
        assert len(empty) == 1 and empty[0].address == "" and empty[0].removed
        assert dict(_rows(db_path, "SELECT id, mailbox_id FROM emails"))["e2"] == empty[0].id
        assert pending_step_ids(dbm.get_engine(), dbm.PROFILE_STEPS) == []
    finally:
        dbm.dispose_engine()


def test_empty_email_address_is_the_runtime_owner_and_gets_the_primary(tmp_path, monkeypatch):
    db_path = str(tmp_path / "zylch.db")
    _legacy_db(db_path, owners={"": ["e1"]})
    monkeypatch.setenv("ZYLCH_DB_PATH", db_path)
    monkeypatch.setenv("EMAIL_ADDRESS", "")
    dbm.dispose_engine()
    try:
        dbm.init_db()
        prim = mailboxes.primary("")
        assert prim is not None and prim.address == ""
        assert dict(_rows(db_path, "SELECT id, mailbox_id FROM emails"))["e1"] == prim.id
    finally:
        dbm.dispose_engine()


# ─── one row per (owner, address), revived rather than duplicated ──


def test_hidden_owner_keyed_row_is_revived_not_duplicated(legacy, monkeypatch):
    """Migrate with an address and old local-user rows, then boot without the
    address: local-user is the runtime owner again and its one row is revived."""
    dbm.init_db()
    hidden = mailboxes.for_owner(LOCAL, include_removed=True)
    assert len(hidden) == 1 and hidden[0].removed

    monkeypatch.delenv("EMAIL_ADDRESS", raising=False)
    dbm.dispose_engine()
    dbm.init_db()
    assert mailboxes.default_mailbox_id(LOCAL) == hidden[0].id
    active = mailboxes.for_owner(LOCAL)
    assert [m.id for m in active] == [hidden[0].id] and not active[0].removed
    assert _rows(legacy, "SELECT COUNT(*) FROM mailboxes WHERE owner_id = ?", (LOCAL,)) == [(1,)]


def test_owner_address_pair_is_unique_in_both_shapes(legacy, tmp_path, monkeypatch):
    import sqlite3 as _sqlite3

    dbm.init_db()
    for path in (legacy,):
        ddl = _rows(path, "SELECT sql FROM sqlite_master WHERE name='mailboxes'")[0][0]
        assert "mailboxes_owner_address_unique" in ddl
        c = _sqlite3.connect(path)
        try:
            with pytest.raises(_sqlite3.IntegrityError):
                c.execute(
                    "INSERT INTO mailboxes (id, owner_id, address, is_primary) VALUES ('dup', ?, ?, 0)",
                    (OWNER, OWNER),
                )
        finally:
            c.close()
    fresh_path = str(tmp_path / "fresh" / "zylch.db")
    monkeypatch.setenv("ZYLCH_DB_PATH", fresh_path)
    dbm.dispose_engine()
    dbm.init_db()
    assert "mailboxes_owner_address_unique" in (
        _rows(fresh_path, "SELECT sql FROM sqlite_master WHERE name='mailboxes'")[0][0]
    )


def test_mailbox_and_qonto_steps_survive_reopen_together(legacy):
    from zylch.qonto.models import TABLE_NAMES

    dbm.init_db()
    with dbm.get_engine().begin() as conn:
        names = {r[0] for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}
        assert TABLE_NAMES <= names
        conn.exec_driver_sql(
            "INSERT INTO qonto_connections (uid, status, generation, selected_account_ids, changed_at) "
            "VALUES ('synthetic-uid', 'disconnected', 7, '[]', 1)"
        )
    before = _rows(legacy, "SELECT id, mailbox_id FROM emails ORDER BY id")
    dbm.dispose_engine()
    dbm.init_db()
    assert _rows(legacy, "SELECT id, mailbox_id FROM emails ORDER BY id") == before
    assert _rows(legacy, "SELECT generation FROM qonto_connections WHERE uid='synthetic-uid'") == [(7,)]
    recorded = {r[0] for r in _rows(legacy, "SELECT id FROM schema_version")}
    assert {STEP_ID, '0003_qonto_private', '0004_qonto_source_sync', '0005_qonto_managed_history'} <= recorded
    backups = os.listdir(os.path.join(os.path.dirname(legacy), 'backups'))
    assert len([n for n in backups if '.qonto-private-v1.' in n and n.endswith('.bak')]) == 1
    assert len(_backups(legacy)) == 1
