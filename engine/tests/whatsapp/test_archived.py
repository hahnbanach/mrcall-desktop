"""Tests for archived-WhatsApp-chat exclusion from analysis.

Archived chats must be dropped from BOTH memory extraction and task
creation, but stay fully visible in the UI (no change to
``list_threads``). The archived flag is read read-only from neonize's
session DB (``whatsmeow_chat_settings``); these tests build a temp
sqlite file shaped like that table and exercise the two pure helpers in
``zylch.whatsapp.sync``:

* :func:`get_archived_chat_jids` — must return exactly the archived
  ``chat_jid``s, and degrade to an EMPTY set (never raise) when the file
  or the table is missing.
* :func:`drop_archived_messages` — pure filter, no DB.

``get_archived_chat_jids`` resolves its path via
``zylch.whatsapp.client._default_wa_db`` (imported inside the function),
so we monkeypatch it at that source module.
"""

import sqlite3

from zylch.whatsapp.sync import drop_archived_messages, get_archived_chat_jids


def _make_chat_settings_db(path, rows):
    """Create a sqlite file with a ``whatsmeow_chat_settings`` table.

    ``rows`` is a list of ``(chat_jid, archived)`` tuples mirroring the
    real whatsmeow schema (other columns present but unused here).
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE whatsmeow_chat_settings ("
            "our_jid TEXT, chat_jid TEXT, muted_until INTEGER, "
            "pinned BOOLEAN, archived BOOLEAN)"
        )
        conn.executemany(
            "INSERT INTO whatsmeow_chat_settings "
            "(our_jid, chat_jid, muted_until, pinned, archived) "
            "VALUES (?, ?, 0, 0, ?)",
            [("me@s.whatsapp.net", jid, archived) for jid, archived in rows],
        )
        conn.commit()
    finally:
        conn.close()


def test_get_archived_chat_jids_returns_only_archived(tmp_path, monkeypatch):
    db = tmp_path / "whatsapp.db"
    _make_chat_settings_db(
        db,
        [
            ("393281234567@s.whatsapp.net", 1),  # archived 1-on-1
            ("120363000000000000@g.us", 1),  # archived group
            ("86904452186141@lid", 1),  # archived lid chat
            ("393289999999@s.whatsapp.net", 0),  # not archived
            ("393287777777@s.whatsapp.net", 0),  # not archived
        ],
    )
    monkeypatch.setattr("zylch.whatsapp.client._default_wa_db", lambda: str(db))

    assert get_archived_chat_jids() == {
        "393281234567@s.whatsapp.net",
        "120363000000000000@g.us",
        "86904452186141@lid",
    }


def test_get_archived_chat_jids_all_unarchived_is_empty(tmp_path, monkeypatch):
    db = tmp_path / "whatsapp.db"
    _make_chat_settings_db(db, [("393281234567@s.whatsapp.net", 0)])
    monkeypatch.setattr("zylch.whatsapp.client._default_wa_db", lambda: str(db))

    assert get_archived_chat_jids() == set()


def test_get_archived_chat_jids_missing_file_returns_empty(tmp_path, monkeypatch):
    missing = tmp_path / "does_not_exist.db"
    monkeypatch.setattr("zylch.whatsapp.client._default_wa_db", lambda: str(missing))

    # Must NOT raise — degrade to empty.
    assert get_archived_chat_jids() == set()


def test_get_archived_chat_jids_missing_table_returns_empty(tmp_path, monkeypatch):
    # An older session DB exists but predates the chat_settings table.
    db = tmp_path / "whatsapp.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("CREATE TABLE whatsmeow_contacts (their_jid TEXT)")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr("zylch.whatsapp.client._default_wa_db", lambda: str(db))

    # File opens fine, but the SELECT fails on the missing table — no raise.
    assert get_archived_chat_jids() == set()


def test_drop_archived_messages_removes_archived_keeps_rest():
    msgs = [
        {"id": "a", "chat_jid": "393281234567@s.whatsapp.net"},  # archived
        {"id": "b", "chat_jid": "393289999999@s.whatsapp.net"},  # keep
        {"id": "c", "chat_jid": "120363000000000000@g.us"},  # archived
        {"id": "d", "chat_jid": "393287777777@s.whatsapp.net"},  # keep
    ]
    archived = {"393281234567@s.whatsapp.net", "120363000000000000@g.us"}

    kept = drop_archived_messages(msgs, archived)

    assert [m["id"] for m in kept] == ["b", "d"]


def test_drop_archived_messages_empty_set_is_passthrough():
    msgs = [
        {"id": "a", "chat_jid": "393281234567@s.whatsapp.net"},
        {"id": "b", "chat_jid": "393289999999@s.whatsapp.net"},
    ]
    # Same list contents back; passthrough on empty archived set.
    assert drop_archived_messages(msgs, set()) == msgs


def test_drop_archived_messages_keeps_rows_without_chat_jid():
    # Defensive: a row with no chat_jid is never silently dropped.
    msgs = [{"id": "a"}, {"id": "b", "chat_jid": ""}]
    assert drop_archived_messages(msgs, {"393281234567@s.whatsapp.net"}) == msgs
