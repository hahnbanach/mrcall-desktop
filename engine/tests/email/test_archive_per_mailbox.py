"""``emails.archive`` across mailboxes (D3), on fake IMAP servers.

Each mailbox moves its own copies over its own client; a Message-ID the
source mailbox does not hold is a named failure whose row stays visible;
the primary's connection never touches another mailbox's messages.
"""

from __future__ import annotations

import asyncio
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from tests.email.fake_imap import FakeFolder, build_raw_message, make_client
from tests.email.test_pec_envelope import _envelope, _inner
from zylch.email import mailboxes
from zylch.rpc import email_actions
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
    monkeypatch.setattr("zylch.cli.utils.get_owner_id", lambda: OWNER)
    dbm.dispose_engine()
    dbm.init_db()
    import zylch.storage.storage as storage_mod

    monkeypatch.setattr(storage_mod, "_generate_email_embedding", lambda email: None)
    from zylch.storage.storage import Storage

    store = Storage()
    monkeypatch.setattr("zylch.storage.storage.Storage.get_instance", lambda: store)
    second = mailboxes.add_mailbox(OWNER, SECOND, secrets.token_urlsafe(12))
    yield {"db": db_path, "store": store, "primary": mailboxes.primary(OWNER), "second": second}
    dbm.dispose_engine()


def _servers(monkeypatch, env, primary_msgs: dict, second_msgs: dict) -> dict:
    """One fake server per mailbox, each with INBOX and an archive folder."""
    servers = {}
    for address, msgs in ((OWNER, primary_msgs), (SECOND, second_msgs)):
        inbox = FakeFolder(uidvalidity=11)
        for uid, raw in msgs.items():
            inbox.add(uid, raw)
        folders = {
            "INBOX": inbox,
            "[Gmail]/All Mail": FakeFolder(uidvalidity=12),
            "[Gmail]/Sent Mail": FakeFolder(uidvalidity=13),
        }
        client = make_client(folders, email_addr=address)
        client.connect = lambda: None
        # the archive disconnects each client; keep the fake's command log
        servers[address] = {"client": client, "folders": folders, "conn": client._conn}

    def build(mailbox):
        return servers[mailbox.address]["client"]

    monkeypatch.setattr("zylch.email.mailboxes.build_imap_client", build)
    return servers


def _store(env, mailbox_id: str, mid: str, thread: str, minutes: int = 0, **extra):
    when = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    row = {
        "id": mid,
        "thread_id": thread,
        "from_email": "customer@client.test",
        "to_email": OWNER,
        "subject": "order",
        "date": when.isoformat(),
        "date_timestamp": int(when.timestamp()),
        "message_id_header": mid,
    }
    row.update(extra)
    env["store"].store_emails_batch(OWNER, [row], mailbox_id=mailbox_id)


def _archive(thread_id: str):
    return asyncio.run(email_actions.emails_archive({"thread_id": thread_id}, lambda *_: None))


def _archived(db_path: str) -> dict:
    c = sqlite3.connect(db_path)
    try:
        return {
            (r[0], r[1]): r[2] is not None
            for r in c.execute("SELECT mailbox_id, message_id_header, archived_at FROM emails")
        }
    finally:
        c.close()


def _moved(servers, address) -> set:
    return {
        raw.split(b"Message-ID: ")[1].split(b"\r\n")[0].decode()
        for raw in servers[address]["folders"]["[Gmail]/All Mail"].messages.values()
    }


def _touched(servers, address) -> list:
    return [c for c in servers[address]["conn"].commands if c[0] in ("SELECT", "UID")]


def test_a_thread_spanning_both_mailboxes_moves_each_copy_on_its_own_server(env, monkeypatch):
    when = datetime.now(timezone.utc) - timedelta(days=1)
    servers = _servers(
        monkeypatch,
        env,
        {1: build_raw_message("<a1@x>", date=when)},
        {1: build_raw_message("<a2@x>", date=when)},
    )
    prim, second = env["primary"].id, env["second"].id
    _store(env, prim, "<a1@x>", "A")
    _store(env, second, "<a2@x>", "A", 1)

    result = _archive("A")
    assert result["ok"] is True and result["archived"] == 2
    assert sorted(
        (m["mailbox_id"], m["attempted"], m["moved"], m["error"]) for m in result["mailboxes"]
    ) == sorted([(prim, 1, 1, None), (second, 1, 1, None)])
    assert _moved(servers, OWNER) == {"<a1@x>"} and _moved(servers, SECOND) == {"<a2@x>"}
    assert all(_archived(env["db"]).values())
    # the primary's connection never searched or moved the other mailbox's message
    assert not any("<a2@x>" in str(c) for c in _touched(servers, OWNER))
    assert not any("<a1@x>" in str(c) for c in _touched(servers, SECOND))


def test_the_same_message_id_in_both_mailboxes_moves_both_copies(env, monkeypatch):
    when = datetime.now(timezone.utc) - timedelta(days=1)
    shared = build_raw_message("<shared@x>", date=when)
    servers = _servers(monkeypatch, env, {7: shared}, {9: shared})
    prim, second = env["primary"].id, env["second"].id
    _store(env, prim, "<shared@x>", "S")
    _store(env, second, "<shared@x>", "S", 1)

    result = _archive("S")
    assert result["ok"] is True and result["archived"] == 2
    assert _moved(servers, OWNER) == {"<shared@x>"} and _moved(servers, SECOND) == {"<shared@x>"}
    assert _archived(env["db"]) == {(prim, "<shared@x>"): True, (second, "<shared@x>"): True}


def test_a_pec_envelope_moves_by_its_envelope_id(env, monkeypatch):
    from zylch.email.imap_client import _parse_message_bytes

    envelope = _envelope(_inner())
    servers = _servers(monkeypatch, env, {}, {3: envelope})
    parsed = _parse_message_bytes(envelope)
    second = env["second"].id
    _store(
        env,
        second,
        parsed["message_id"],
        "P",
        original_message_id=parsed["original_message_id"],
        pec_markers=parsed["pec_markers"],
    )
    assert parsed["message_id"] == "<env-1@pec-provider.test>"

    result = _archive("P")
    assert result["ok"] is True and result["archived"] == 1
    assert _moved(servers, SECOND) == {
        "<env-1@pec-provider.test>"
    }  # the envelope, not the original
    assert not _touched(servers, OWNER)  # the primary was never opened


def test_a_missing_message_is_a_named_failure_and_its_row_stays_visible(env, monkeypatch):
    when = datetime.now(timezone.utc) - timedelta(days=1)
    servers = _servers(monkeypatch, env, {1: build_raw_message("<here@x>", date=when)}, {})
    prim, second = env["primary"].id, env["second"].id
    _store(env, prim, "<here@x>", "M")
    _store(env, second, "<gone@x>", "M", 1)  # the server no longer holds it

    result = _archive("M")
    assert result["ok"] is False and result["archived"] == 1
    by_mailbox = {m["mailbox_id"]: m for m in result["mailboxes"]}
    assert by_mailbox[prim]["moved"] == 1 and by_mailbox[prim]["error"] is None
    assert by_mailbox[second]["moved"] == 0 and by_mailbox[second]["attempted"] == 1
    assert "<gone@x>" in by_mailbox[second]["error"] and "not found" in by_mailbox[second]["error"]
    archived = _archived(env["db"])
    assert archived[(prim, "<here@x>")] is True and archived[(second, "<gone@x>")] is False
    assert [t["thread_id"] for t in env["store"].list_inbox_threads(OWNER, OWNER)] == [
        "M"
    ]  # still visible
    assert _moved(servers, OWNER) == {"<here@x>"} and _moved(servers, SECOND) == set()


def test_a_mailbox_that_cannot_connect_moves_nothing_and_is_named(env, monkeypatch):
    when = datetime.now(timezone.utc) - timedelta(days=1)
    servers = _servers(
        monkeypatch,
        env,
        {1: build_raw_message("<p@x>", date=when)},
        {1: build_raw_message("<s@x>", date=when)},
    )

    def refuse():
        raise RuntimeError("login refused")

    servers[SECOND]["client"].connect = refuse
    prim, second = env["primary"].id, env["second"].id
    _store(env, prim, "<p@x>", "C")
    _store(env, second, "<s@x>", "C", 1)

    result = _archive("C")
    assert result["ok"] is False and result["archived"] == 1
    by_mailbox = {m["mailbox_id"]: m for m in result["mailboxes"]}
    assert by_mailbox[second]["moved"] == 0 and "login refused" in by_mailbox[second]["error"]
    assert SECOND in by_mailbox[second]["error"]
    assert _archived(env["db"])[(second, "<s@x>")] is False


def test_a_copy_in_sent_or_already_archived_is_at_its_destination(env, monkeypatch):
    """The user's own reply lives in Sent; a message archived from another
    client lives in the archive folder: both rows are stamped, nothing fails."""
    when = datetime.now(timezone.utc) - timedelta(days=1)
    servers = _servers(monkeypatch, env, {1: build_raw_message("<in@x>", date=when)}, {})
    prim = env["primary"].id
    servers[OWNER]["folders"]["[Gmail]/Sent Mail"].add(
        5, build_raw_message("<reply@x>", from_addr=OWNER, date=when)
    )
    servers[OWNER]["folders"]["[Gmail]/All Mail"].add(9, build_raw_message("<old@x>", date=when))
    _store(env, prim, "<in@x>", "R")
    _store(env, prim, "<reply@x>", "R", 1, from_email=OWNER)
    _store(env, prim, "<old@x>", "R", 2)

    result = _archive("R")
    assert result["ok"] is True and result["archived"] == 3
    assert result["mailboxes"] == [{"mailbox_id": prim, "attempted": 3, "moved": 3, "error": None}]
    assert _moved(servers, OWNER) == {"<in@x>", "<old@x>"}  # the Sent copy stays in Sent
    assert all(_archived(env["db"]).values())


def test_a_non_ok_search_is_a_protocol_failure_not_a_missing_message(env, monkeypatch):
    when = datetime.now(timezone.utc) - timedelta(days=1)
    servers = _servers(monkeypatch, env, {1: build_raw_message("<in@x>", date=when)}, {})
    servers[OWNER]["folders"]["INBOX"].search_fails = True
    prim = env["primary"].id
    _store(env, prim, "<in@x>", "F")

    result = _archive("F")
    assert result["ok"] is False and result["archived"] == 0
    error = result["mailboxes"][0]["error"]
    assert "SEARCH" in error and "not found" not in error
    assert _archived(env["db"])[(prim, "<in@x>")] is False
