"""The ``mailboxes.*`` surface and what M5 adds to ``emails.*`` and ``setup.state``.

Real SQLite storage; the IMAP probe runs against fake clients whose
``connect`` raises the chained exceptions the real client raises, so the
four failure classes are exercised end to end through the handler.
"""

from __future__ import annotations

import asyncio
import imaplib
import secrets
import socket
import sqlite3
import ssl
from datetime import datetime, timedelta, timezone

import pytest

from tests.email.fake_imap import FakeFolder, make_client
from zylch.email import mailboxes
from zylch.email.imap_client import IMAPError
from zylch.rpc import mailboxes as rpc
from zylch.storage import database as dbm

OWNER = "owner@company.test"
SECOND = "pec@pec.company.test"


def _notify(*_a, **_k):
    return None


def _call(handler, params):
    return asyncio.run(handler(params, _notify))


@pytest.fixture
def env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "zylch.db")
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / ".env").write_text(f"EMAIL_ADDRESS={OWNER}\n")
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(profile))
    monkeypatch.setenv("ZYLCH_DB_PATH", db_path)
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    monkeypatch.setenv("EMAIL_PASSWORD", secrets.token_hex(8))
    monkeypatch.setenv("IMAP_HOST", "imap.company.test")
    monkeypatch.delenv("MAILBOX_SECRET_KEY", raising=False)
    monkeypatch.setattr("zylch.cli.utils.get_owner_id", lambda: OWNER)
    monkeypatch.setattr("zylch.api.token_storage.get_provider", lambda _o: "imap")
    monkeypatch.setattr("zylch.api.token_storage.get_email", lambda _o: OWNER)
    dbm.dispose_engine()
    dbm.init_db()
    import zylch.storage.storage as storage_mod

    monkeypatch.setattr(storage_mod, "_generate_email_embedding", lambda email: None)
    from zylch.storage.storage import Storage

    store = Storage()
    monkeypatch.setattr("zylch.storage.storage.Storage.get_instance", lambda: store)
    yield {"db": db_path, "store": store, "profile": profile}
    dbm.dispose_engine()


def _fake_server(monkeypatch, *, failure: str | None = None, inbox_broken: bool = False):
    """Route the handler's probe client to a fake server.

    ``failure`` raises from ``connect`` the way ``IMAPClient.connect`` does
    (an ``IMAPError`` chained from the transport's exception); otherwise
    the fake folders answer LIST/SELECT.
    """
    built = {}

    def build(address, password, hosts):
        inbox = FakeFolder(uidvalidity=5)
        inbox.select_fails = inbox_broken
        client = make_client(
            {"INBOX": inbox, "Sent Mail": FakeFolder(uidvalidity=6)}, email_addr=address
        )
        built["client"] = client
        built["conn"] = client._conn  # the probe disconnects; keep the fake's log
        built["password"] = password
        built["hosts"] = hosts
        if failure is None:
            client.connect = lambda: None  # already wired to the fake
            return client

        def connect():
            if failure == "auth":
                cause = imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials")
            elif failure == "tls":
                cause = ssl.SSLError(1, "TLS handshake failed")
            else:
                cause = socket.gaierror(-2, "Name or service not known")
            try:
                raise cause
            except Exception as e:
                raise IMAPError(f"IMAP connect to {address} failed: {type(e).__name__}: {e}") from e

        client.connect = connect
        return client

    monkeypatch.setattr(rpc, "_probe_client", build)
    return built


# ─── list, presets ────────────────────────────────────────────


def test_list_shows_the_primary_without_secrets_and_presets_include_pec_net(env):
    result = _call(rpc.mailboxes_list, {})
    assert [m["address"] for m in result["mailboxes"]] == [OWNER]
    prim = result["mailboxes"][0]
    assert prim["is_primary"] and prim["configured"] and prim["state"] == "never"
    assert "secret" not in prim and "password" not in prim
    assert prim["imap_host"] == "imap.company.test"

    presets = _call(rpc.mailboxes_presets, {})["presets"]
    pec = next(p for p in presets if p["id"] == "pec.net")
    assert pec["label"] == "PEC.net (Register.it)"
    assert (pec["imap_host"], pec["imap_port"], pec["imap_security"]) == (
        "imap.pec-email.com",
        993,
        "ssl",
    )
    assert (pec["smtp_host"], pec["smtp_port"], pec["smtp_security"]) == (
        "smtp.pec-email.com",
        465,
        "ssl",
    )
    assert pec["username"] == "full_address" and pec["password_label"] == "PEC mailbox password"
    gmail = next(p for p in presets if "gmail.com" in p["domains"])
    assert gmail["imap_host"] == "imap.gmail.com" and "googlemail.com" in gmail["domains"]


# ─── test: the four failure classes and ok ────────────────────


@pytest.mark.parametrize(
    "failure,status", [("auth", "auth"), ("dns", "unreachable"), ("tls", "tls")]
)
def test_probe_classifies_connect_failures_and_never_echoes_the_password(
    env, monkeypatch, failure, status
):
    _fake_server(monkeypatch, failure=failure)
    password = secrets.token_urlsafe(12)
    result = _call(rpc.mailboxes_test, {"address": SECOND, "password": password})
    assert result["ok"] is False and result["status"] == status
    assert password not in result["message"] and result["message"]


def test_probe_reports_a_folder_that_cannot_be_opened_and_ok_otherwise(env, monkeypatch):
    _fake_server(monkeypatch, inbox_broken=True)
    result = _call(rpc.mailboxes_test, {"address": SECOND, "password": "x" * 12})
    assert result["ok"] is False and result["status"] == "folder" and "INBOX" in result["message"]

    built = _fake_server(monkeypatch)
    result = _call(
        rpc.mailboxes_test,
        {"address": SECOND, "password": "x" * 12, "imap_host": "imap.pec-email.com"},
    )
    assert result == {
        "ok": True,
        "status": "ok",
        "message": 'Connected; folders checked: INBOX, "Sent Mail"',
    }
    assert built["hosts"]["imap_host"] == "imap.pec-email.com"
    selects = [c for c in built["conn"].commands if c[0] == "SELECT"]
    assert selects and all(c[2] is True for c in selects)  # read-only, always
    assert _call(rpc.mailboxes_list, {})["mailboxes"][-1]["address"] == OWNER  # nothing stored


def test_test_requires_address_and_password(env):
    with pytest.raises(ValueError):
        _call(rpc.mailboxes_test, {"password": "x"})
    with pytest.raises(ValueError):
        _call(rpc.mailboxes_test, {"address": SECOND})


# ─── add, duplicate, revive, remove ───────────────────────────


def test_add_tests_first_writes_the_key_before_the_row_and_refuses_duplicates(env, monkeypatch):
    from zylch.services.settings_io import read_env

    _fake_server(monkeypatch, failure="auth")
    password = secrets.token_urlsafe(12)
    refused = _call(rpc.mailboxes_add, {"address": SECOND, "password": password})
    assert refused["ok"] is False and refused["status"] == "auth"
    assert mailboxes.by_address(OWNER, SECOND) is None  # nothing stored on a failed test

    _fake_server(monkeypatch)
    added = _call(rpc.mailboxes_add, {"address": SECOND, "password": password, "preset": "pec.net"})
    assert added["ok"] is True and added["mailbox"]["address"] == SECOND
    assert added["mailbox"]["configured"] and not added["mailbox"]["is_primary"]
    assert "secret" not in added["mailbox"]
    assert read_env()["MAILBOX_SECRET_KEY"]  # the key is in .env
    stored = (
        sqlite3.connect(env["db"])
        .execute("SELECT secret FROM mailboxes WHERE address = ?", (SECOND,))
        .fetchone()[0]
    )
    assert stored and password not in stored

    again = _call(rpc.mailboxes_add, {"address": SECOND, "password": password})
    assert again["ok"] is False and again["status"] == "duplicate"
    primary_again = _call(rpc.mailboxes_add, {"address": OWNER, "password": password})
    assert primary_again["ok"] is False and primary_again["status"] == "duplicate"


def test_remove_refuses_the_primary_and_re_add_revives_the_row_with_its_rows(env, monkeypatch):
    _fake_server(monkeypatch)
    store = env["store"]
    prim = mailboxes.primary(OWNER)
    refused = _call(rpc.mailboxes_remove, {"mailbox_id": prim.id})
    assert refused["ok"] is False and refused["status"] == "primary"
    assert _call(rpc.mailboxes_remove, {"mailbox_id": "no-such"})["status"] == "unknown"

    added = _call(rpc.mailboxes_add, {"address": SECOND, "password": secrets.token_urlsafe(12)})
    mailbox_id = added["mailbox"]["id"]
    when = datetime.now(timezone.utc) - timedelta(days=1)
    store.store_emails_batch(
        OWNER,
        [
            {
                "id": "<pec-1@x>",
                "thread_id": "<pec-1@x>",
                "from_email": "customer@client.test",
                "to_email": SECOND,
                "subject": "hello",
                "date": when.isoformat(),
                "date_timestamp": int(when.timestamp()),
                "message_id_header": "<pec-1@x>",
            }
        ],
        mailbox_id=mailbox_id,
    )
    assert [m["mailbox_ids"] for m in store.list_inbox_threads(OWNER, OWNER)] == [[mailbox_id]]

    removed = _call(rpc.mailboxes_remove, {"mailbox_id": mailbox_id})
    assert removed["ok"] is True
    assert [m["address"] for m in _call(rpc.mailboxes_list, {})["mailboxes"]] == [OWNER]
    assert store.list_inbox_threads(OWNER, OWNER) == []  # hidden, not deleted
    assert sqlite3.connect(env["db"]).execute("SELECT COUNT(*) FROM emails").fetchone() == (1,)

    revived = _call(rpc.mailboxes_add, {"address": SECOND, "password": secrets.token_urlsafe(12)})
    assert revived["mailbox"]["id"] == mailbox_id  # same row, same id
    assert [m["mailbox_ids"] for m in store.list_inbox_threads(OWNER, OWNER)] == [[mailbox_id]]


def test_update_re_tests_on_change_and_refuses_the_primary(env, monkeypatch):
    built = _fake_server(monkeypatch)
    password = secrets.token_urlsafe(12)
    mailbox_id = _call(rpc.mailboxes_add, {"address": SECOND, "password": password})["mailbox"][
        "id"
    ]

    prim = mailboxes.primary(OWNER)
    assert (
        _call(rpc.mailboxes_update, {"mailbox_id": prim.id, "imap_host": "x"})["status"]
        == "primary"
    )
    assert _call(rpc.mailboxes_update, {"mailbox_id": "no-such"})["status"] == "unknown"

    # a host change is tested with the stored password before it is written
    updated = _call(rpc.mailboxes_update, {"mailbox_id": mailbox_id, "imap_host": "imap2.pec.test"})
    assert updated["ok"] is True and updated["mailbox"]["imap_host"] == "imap2.pec.test"
    assert built["password"] == password and built["hosts"]["imap_host"] == "imap2.pec.test"

    # a failing test leaves the row as it was
    _fake_server(monkeypatch, failure="auth")
    refused = _call(rpc.mailboxes_update, {"mailbox_id": mailbox_id, "password": "wrong-pass-xx"})
    assert refused["ok"] is False and refused["status"] == "auth"
    assert mailboxes.by_id(OWNER, mailbox_id).imap_host == "imap2.pec.test"
    client = mailboxes.build_imap_client(mailboxes.by_id(OWNER, mailbox_id))
    assert client.password == password  # the old password still decrypts

    # a new password that tests fine is stored
    built = _fake_server(monkeypatch)
    new_password = secrets.token_urlsafe(12)
    assert (
        _call(rpc.mailboxes_update, {"mailbox_id": mailbox_id, "password": new_password})["ok"]
        is True
    )
    assert built["password"] == new_password
    assert mailboxes.build_imap_client(mailboxes.by_id(OWNER, mailbox_id)).password == new_password


# ─── emails.* fields and setup.state ──────────────────────────


def _row(mid, thread, sender, to, minutes, **extra):
    when = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    row = {
        "id": mid,
        "thread_id": thread,
        "from_email": sender,
        "to_email": to,
        "subject": "invoice",
        "body_plain": "invoice",
        "snippet": "invoice",
        "date": when.isoformat(),
        "date_timestamp": int(when.timestamp()),
        "message_id_header": mid,
    }
    row.update(extra)
    return row


def test_lists_carry_mailbox_ids_and_filter_by_mailbox(env, monkeypatch):
    from zylch.rpc import methods

    _fake_server(monkeypatch)
    store = env["store"]
    prim = mailboxes.primary(OWNER)
    second_id = _call(rpc.mailboxes_add, {"address": SECOND, "password": "p" * 12})["mailbox"]["id"]
    store.store_emails_batch(OWNER, [_row("<a1>", "A", "c@x", OWNER, 0)], mailbox_id=prim.id)
    store.store_emails_batch(OWNER, [_row("<a2>", "A", "c@x", SECOND, 1)], mailbox_id=second_id)
    store.store_emails_batch(
        OWNER,
        [
            _row(
                "<b1>",
                "B",
                "d@x",
                SECOND,
                2,
                original_message_id="<orig-b@x>",
                pec_markers={"kind": "transport"},
            )
        ],
        mailbox_id=second_id,
    )

    inbox = _call(methods.emails_list_inbox, {})["threads"]
    assert {t["thread_id"]: t["mailbox_ids"] for t in inbox} == {
        "A": sorted([prim.id, second_id]),
        "B": [second_id],
    }
    only_primary = _call(methods.emails_list_inbox, {"mailbox_id": prim.id})["threads"]
    assert [(t["thread_id"], t["mailbox_ids"]) for t in only_primary] == [("A", [prim.id])]
    searched = _call(
        methods.emails_search, {"query": "invoice", "folder": "all", "mailbox_id": second_id}
    )["threads"]
    assert {t["thread_id"] for t in searched} == {"A", "B"}

    rows = _call(methods.emails_list_by_thread, {"thread_id": "B"})["emails"]
    assert rows[0]["mailbox_id"] == second_id and rows[0]["mailbox_address"] == SECOND
    assert rows[0]["original_message_id"] == "<orig-b@x>"
    assert rows[0]["pec_markers"] == {"kind": "transport"}
    rows = _call(methods.emails_list_by_thread, {"thread_id": "A"})["emails"]
    assert [(r["mailbox_address"], r["original_message_id"], r["pec_markers"]) for r in rows] == [
        (OWNER, None, None),
        (SECOND, None, None),
    ]


def test_setup_state_counts_exclude_removed_mailboxes_and_break_down_per_mailbox(env, monkeypatch):
    from zylch.rpc import setup

    _fake_server(monkeypatch)
    store = env["store"]
    prim = mailboxes.primary(OWNER)
    second_id = _call(rpc.mailboxes_add, {"address": SECOND, "password": "p" * 12})["mailbox"]["id"]
    store.store_emails_batch(OWNER, [_row("<a1>", "A", "c@x", OWNER, 0)], mailbox_id=prim.id)
    store.store_emails_batch(OWNER, [_row("<b1>", "B", "d@x", SECOND, 1)], mailbox_id=second_id)
    store.store_emails_batch(OWNER, [_row("<b2>", "B", "d@x", SECOND, 2)], mailbox_id=second_id)
    b2 = (
        sqlite3.connect(env["db"])
        .execute("SELECT id FROM emails WHERE gmail_id = '<b2>'")
        .fetchone()[0]
    )
    store.mark_email_processed(OWNER, b2)  # one of the second mailbox's rows

    state = _call(setup.setup_state, {})
    assert state["emails_count"] == 3 and state["emails_pending_analysis"] == 2
    assert [(m["address"], m["emails_count"]) for m in state["mailboxes"]] == [
        (OWNER, 1),
        (SECOND, 2),
    ]

    _call(rpc.mailboxes_remove, {"mailbox_id": second_id})
    state = _call(setup.setup_state, {})
    assert state["emails_count"] == 1 and state["emails_pending_analysis"] == 1
    assert [m["address"] for m in state["mailboxes"]] == [OWNER]
    assert store.get_email_stats(OWNER)["total_emails"] == 1


def test_get_email_by_id_disambiguates_by_mailbox(env, monkeypatch):
    _fake_server(monkeypatch)
    store = env["store"]
    prim = mailboxes.primary(OWNER)
    second_id = _call(rpc.mailboxes_add, {"address": SECOND, "password": "p" * 12})["mailbox"]["id"]
    store.store_emails_batch(OWNER, [_row("<m@x>", "T", "c@x", OWNER, 0)], mailbox_id=prim.id)
    store.store_emails_batch(OWNER, [_row("<m@x>", "T", "c@x", SECOND, 1)], mailbox_id=second_id)

    assert store.get_email_by_id(OWNER, "<m@x>", mailbox_id=second_id)["mailbox_id"] == second_id
    assert (
        store.get_email_by_id(OWNER, "<m@x>")["mailbox_id"] == prim.id
    )  # copies: the first stored
    store.store_emails_batch(
        OWNER,
        [_row("<m@x>", "T", "c@x", SECOND, 2, message_id_header="<other@x>")],
        mailbox_id=second_id,
    )
    with pytest.raises(ValueError):
        store.get_email_by_id(OWNER, "<m@x>")


def test_reply_threads_on_the_pec_original():
    from zylch.agents.emailer_agent import reply_threading

    assert reply_threading(
        {
            "message_id_header": "<env@pec>",
            "original_message_id": "<orig@x>",
            "references": ["<r@x>"],
        }
    ) == (
        "<orig@x>",
        ["<r@x>", "<orig@x>"],
    )
    assert reply_threading({"message_id_header": "<plain@x>", "original_message_id": None}) == (
        "<plain@x>",
        ["<plain@x>"],
    )


def test_addresses_are_one_account_whatever_their_casing(env, monkeypatch):
    _fake_server(monkeypatch)
    password = secrets.token_urlsafe(12)
    added = _call(rpc.mailboxes_add, {"address": " PEC@Pec.Company.test ", "password": password})
    assert added["ok"] is True and added["mailbox"]["address"] == SECOND  # stored lower-cased
    again = _call(rpc.mailboxes_add, {"address": "pec@pec.company.test", "password": password})
    assert again["ok"] is False and again["status"] == "duplicate"
    primary_cased = _call(
        rpc.mailboxes_add, {"address": "Owner@Company.test", "password": password}
    )
    assert primary_cased["ok"] is False and primary_cased["status"] == "duplicate"
    assert mailboxes.by_address(OWNER, "PEC@PEC.COMPANY.TEST").id == added["mailbox"]["id"]

    _call(rpc.mailboxes_remove, {"mailbox_id": added["mailbox"]["id"]})
    revived = _call(rpc.mailboxes_add, {"address": "Pec@pec.company.TEST", "password": password})
    assert revived["mailbox"]["id"] == added["mailbox"]["id"]  # revived, not duplicated
    assert [m["address"] for m in _call(rpc.mailboxes_list, {})["mailboxes"]] == [OWNER, SECOND]


def test_a_concurrent_insert_of_the_same_address_answers_duplicate_without_the_secret(
    env, monkeypatch
):
    from sqlalchemy.exc import IntegrityError

    _fake_server(monkeypatch)

    def racing(*_a, **_k):
        raise IntegrityError(
            "INSERT INTO mailboxes ...", {"secret": "gAAAA-ciphertext"}, Exception("UNIQUE")
        )

    monkeypatch.setattr("zylch.email.mailboxes.add_mailbox", racing)
    result = _call(rpc.mailboxes_add, {"address": SECOND, "password": secrets.token_urlsafe(12)})
    assert result["ok"] is False and result["status"] == "duplicate"
    assert "gAAAA" not in result["message"] and "INSERT" not in result["message"]


def test_client_for_row_refuses_a_removed_mailbox(env, monkeypatch):
    from zylch.email.mailbox_secrets import MailboxSecretError

    _fake_server(monkeypatch)
    mailbox_id = _call(rpc.mailboxes_add, {"address": SECOND, "password": "p" * 12})["mailbox"][
        "id"
    ]
    assert mailboxes.client_for_row(OWNER, {"mailbox_id": mailbox_id}).email_addr == SECOND
    _call(rpc.mailboxes_remove, {"mailbox_id": mailbox_id})
    with pytest.raises(MailboxSecretError):
        mailboxes.client_for_row(OWNER, {"mailbox_id": mailbox_id})
    assert mailboxes.client_for_row(OWNER, {}).email_addr == OWNER  # no mailbox: the primary
