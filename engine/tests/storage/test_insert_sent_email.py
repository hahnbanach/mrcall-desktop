"""``Storage.insert_sent_email``: the sent copy belongs to the primary mailbox.

Dedup by Message-ID and the parent lookup that derives ``thread_id`` are
scoped to the primary, so a copy of the same message held by another
mailbox neither blocks the insert nor lends its thread.
"""

from __future__ import annotations

import secrets
import sqlite3
from datetime import UTC, datetime

import pytest

from zylch.email import mailboxes
from zylch.storage import database as dbm

OWNER = "owner@company.test"
SENT_AT = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path, monkeypatch):
    db_path = str(tmp_path / "zylch.db")
    monkeypatch.setenv("ZYLCH_DB_PATH", db_path)
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    dbm.dispose_engine()
    dbm.init_db()
    import zylch.storage.storage as storage_mod

    monkeypatch.setattr(storage_mod, "_generate_email_embedding", lambda email: None)
    from zylch.storage.storage import Storage

    yield Storage(), db_path
    dbm.dispose_engine()


def _rows(db_path: str, sql: str, params=()):
    c = sqlite3.connect(db_path)
    try:
        return c.execute(sql, params).fetchall()
    finally:
        c.close()


def _sent(st, **overrides):
    args = {
        "owner_id": OWNER,
        "thread_id": None,
        "message_id": "<sent-1@company.test>",
        "from_email": OWNER,
        "to_email": "customer@client.test",
        "cc": None,
        "subject": "Re: order",
        "body_plain": "On its way.",
        "sent_at": SENT_AT,
    }
    args.update(overrides)
    return st.insert_sent_email(**args)


def _row_for(message_id: str, thread_id: str) -> dict:
    return {
        "id": message_id,
        "thread_id": thread_id,
        "from_email": "customer@client.test",
        "to_email": OWNER,
        "subject": "order",
        "date": SENT_AT.isoformat(),
        "date_timestamp": int(SENT_AT.timestamp()),
        "message_id_header": message_id,
    }


def test_sent_copy_is_stamped_with_the_primary_and_deduped_there(store):
    st, db_path = store
    prim = mailboxes.primary(OWNER)

    row = _sent(st)
    assert row["mailbox_id"] == prim.id
    assert row["gmail_id"] == "<sent-1@company.test>"
    assert row["thread_id"] == "<sent-1@company.test>"  # no parent: its own anchor

    again = _sent(st, subject="changed")
    assert again["id"] == row["id"]  # existing copy returned, nothing inserted
    assert _rows(db_path, "SELECT COUNT(*) FROM emails") == [(1,)]


def test_dedup_and_parent_lookup_ignore_other_mailboxes(store):
    st, db_path = store
    prim = mailboxes.primary(OWNER)
    second = mailboxes.add_mailbox(OWNER, "pec@pec.company.test", secrets.token_urlsafe(12))

    # the other mailbox already holds a copy of the sent message
    st.store_emails_batch(
        OWNER, [_row_for("<sent-1@company.test>", "other-thread")], mailbox_id=second.id
    )
    row = _sent(st)
    assert row is not None and row["mailbox_id"] == prim.id
    assert _rows(
        db_path, "SELECT COUNT(*) FROM emails WHERE message_id_header = '<sent-1@company.test>'"
    ) == [(2,)]

    # the parent exists only in the other mailbox: no thread borrowed from it
    st.store_emails_batch(
        OWNER, [_row_for("<parent@client.test>", "other-thread")], mailbox_id=second.id
    )
    reply = _sent(st, message_id="<sent-2@company.test>", in_reply_to="<parent@client.test>")
    assert reply["thread_id"] == "<sent-2@company.test>"

    # the parent in the primary lends its thread
    st.store_emails_batch(OWNER, [_row_for("<parent@client.test>", "primary-thread")])
    reply = _sent(st, message_id="<sent-3@company.test>", in_reply_to="<parent@client.test>")
    assert reply["thread_id"] == "primary-thread"
