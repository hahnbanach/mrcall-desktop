"""The sync cursor's own contract: persistence, keys, config, failure.

These are the invariants the mail-gap fix rests on. If the cursor
silently loses a position, or reads a folder under a different key than
it wrote it, the sync is back to guessing from stored content.
"""

import pytest

from zylch.email import sync_cursor


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "sync_cursor.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))

    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield db_path
    db_mod.dispose_engine()


OWNER = "owner-uid-1"


def test_table_is_created_on_first_use(fresh_db):
    """The module owns its schema — no migration-list entry needed."""
    assert sync_cursor.get_cursor(OWNER, "INBOX") is None

    from zylch.storage.database import get_engine

    with get_engine().begin() as conn:
        rows = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (sync_cursor.TABLE_NAME,),
        ).fetchall()
    assert rows, f"{sync_cursor.TABLE_NAME} was not created"


def test_round_trip_and_update(fresh_db):
    assert sync_cursor.set_cursor(OWNER, "INBOX", uidvalidity=12, last_uid=100) is True

    cursor = sync_cursor.get_cursor(OWNER, "INBOX")
    assert cursor is not None
    assert (cursor.uidvalidity, cursor.last_uid) == (12, 100)

    sync_cursor.set_cursor(OWNER, "INBOX", uidvalidity=12, last_uid=140)
    assert sync_cursor.get_cursor(OWNER, "INBOX").last_uid == 140


def test_cursors_are_scoped_per_owner_and_folder(fresh_db):
    sync_cursor.set_cursor(OWNER, "INBOX", 12, 100)
    sync_cursor.set_cursor(OWNER, '"[Gmail]/All Mail"', 77, 900)
    sync_cursor.set_cursor("other-owner", "INBOX", 12, 5)

    assert sync_cursor.get_cursor(OWNER, "INBOX").last_uid == 100
    assert sync_cursor.get_cursor(OWNER, '"[Gmail]/All Mail"').last_uid == 900
    assert sync_cursor.get_cursor("other-owner", "INBOX").last_uid == 5
    assert len(sync_cursor.list_cursors(OWNER)) == 2


def test_folder_key_ignores_imap_quoting(fresh_db):
    """`"[Gmail]/All Mail"` and `[Gmail]/All Mail` are one folder.

    IMAP needs the quotes for SELECT; the cursor must not end up with
    two rows (and two positions) for the same mailbox.
    """
    sync_cursor.set_cursor(OWNER, '"[Gmail]/All Mail"', 77, 900)

    assert sync_cursor.get_cursor(OWNER, "[Gmail]/All Mail").last_uid == 900
    assert len(sync_cursor.list_cursors(OWNER)) == 1


def test_drop_cursor_removes_the_row(fresh_db):
    sync_cursor.set_cursor(OWNER, "INBOX", 12, 100)
    assert sync_cursor.drop_cursor(OWNER, "INBOX") is True
    assert sync_cursor.get_cursor(OWNER, "INBOX") is None


def test_read_failure_degrades_to_no_cursor_and_logs_error(fresh_db, monkeypatch, caplog):
    """A broken read must re-seed (wider scan), never claim a position."""
    import zylch.storage.database as db_mod

    def boom():
        raise RuntimeError("database is locked")

    monkeypatch.setattr(db_mod, "get_engine", boom)
    with caplog.at_level("ERROR"):
        assert sync_cursor.get_cursor(OWNER, "INBOX") is None
    assert any("get_cursor" in r.message for r in caplog.records)


def test_write_failure_is_loud_but_does_not_raise(fresh_db, monkeypatch, caplog):
    """Emails are already stored when the cursor is written.

    Raising here would turn a bookkeeping problem into a pipeline abort
    and undo nothing; the correct behaviour is to scream and leave the
    cursor behind, so the next run re-examines the same UIDs.
    """
    import zylch.storage.database as db_mod

    def boom():
        raise RuntimeError("disk I/O error")

    monkeypatch.setattr(db_mod, "get_engine", boom)
    with caplog.at_level("ERROR"):
        assert sync_cursor.set_cursor(OWNER, "INBOX", 12, 100) is False
    assert any("set_cursor" in r.message and "FAILED" in r.message for r in caplog.records)


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, sync_cursor.DEFAULT_OVERLAP_DAYS),
        ("", sync_cursor.DEFAULT_OVERLAP_DAYS),
        ("14", 14),
        (" 3 ", 3),
        ("nonsense", sync_cursor.DEFAULT_OVERLAP_DAYS),
        ("0", sync_cursor.DEFAULT_OVERLAP_DAYS),
        ("-5", sync_cursor.DEFAULT_OVERLAP_DAYS),
    ],
)
def test_overlap_days_config(monkeypatch, value, expected):
    """A misconfigured window must not disable the backstop."""
    monkeypatch.delenv(sync_cursor.OVERLAP_DAYS_ENV, raising=False)
    if value is not None:
        monkeypatch.setenv(sync_cursor.OVERLAP_DAYS_ENV, value)
    assert sync_cursor.overlap_days() == expected


def test_default_overlap_is_wider_than_the_old_one_day_floor():
    """The old floor was `newest - 1 day`; that is what hid the message."""
    assert sync_cursor.DEFAULT_OVERLAP_DAYS >= 7
