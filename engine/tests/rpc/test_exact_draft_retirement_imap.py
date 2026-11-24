"""Real IMAP adapter bounded complete candidate inventories and MOVE."""

from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
import sqlite3
import pytest


def test_real_imap_move_adapter_and_complete_uid_fetch(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from zylch.email import mailboxes
    from zylch.services.exact_draft_retirement_imap import RetirementMailbox

    message = EmailMessage(policy=policy.SMTP)
    message["From"] = "owner@example.test"
    message["To"] = "recipient@example.test"
    message["Subject"] = "Synthetic IMAP adapter fixture"
    message["Message-ID"] = "<adapter-fixture@example.test>"
    message.set_content("Synthetic adapter body")
    raw_message = message.as_bytes()
    path = tmp_path / "provider.db"
    moves = []
    with sqlite3.connect(path) as conn:
        for table in ("copies", "sent", "trash"):
            conn.execute(f"CREATE TABLE {table}(id INTEGER PRIMARY KEY, raw BLOB NOT NULL)")
        conn.execute("INSERT INTO copies(raw) VALUES (?)", (raw_message,))
        conn.execute("INSERT INTO sent(raw) VALUES (?)", (raw_message,))
        for table in ("sent", "trash"):
            conn.executemany(
                f"INSERT INTO {table}(raw) VALUES (?)",
                [(b"Subject: Unrelated\r\n\r\nbody",)] * 1001,
            )

    class Connection:
        untagged_responses = {"UIDVALIDITY": [b"7"]}

        def list(self):
            return "OK", [
                f'(\\{name}) "/" "{name}"'.encode() for name in ("Drafts", "Sent", "Trash")
            ]

        def select(self, folder, readonly=False):
            self.folder = folder.strip('"')
            return "OK", []

        def uid(self, command, *args):
            table = {"Drafts": "copies", "Sent": "sent", "Trash": "trash"}[self.folder]
            with sqlite3.connect(path) as conn:
                rows = conn.execute(f"SELECT id,raw FROM {table} ORDER BY id").fetchall()
            if command == "SEARCH":
                if self.folder in {"Sent", "Trash"}:
                    assert args[1] == "HEADER"
                    header, value = args[2], args[3].strip('"')
                    rows = [
                        (uid, raw)
                        for uid, raw in rows
                        if str(BytesParser(policy=policy.default).parsebytes(raw).get(header) or "")
                        == value
                    ]
                return "OK", [b" ".join(str(uid).encode() for uid, raw in rows)]
            if command == "FETCH":
                assert args[-1] == "(UID FLAGS RFC822.SIZE BODY.PEEK[])"
                raw = next(raw for uid, raw in rows if str(uid).encode() == args[0])
                return "OK", [
                    (
                        b"1 (UID "
                        + args[0]
                        + b" FLAGS () RFC822.SIZE "
                        + str(len(raw)).encode()
                        + b")",
                        raw,
                    )
                ]
            assert command == "MOVE"
            assert self.folder == "Drafts" and args[1] == '"Trash"'
            with sqlite3.connect(path) as conn:
                original = conn.execute("SELECT raw FROM copies WHERE id=?", (args[0],)).fetchone()
                assert original is not None
                destination = conn.execute("INSERT INTO trash(raw) VALUES (?)", original).lastrowid
                assert conn.execute("DELETE FROM copies WHERE id=?", (args[0],)).rowcount == 1
            moves.append(str(args[0]))
            return "OK", [f"[COPYUID 7 {args[0]} {destination}] moved".encode()]

    connection = Connection()
    monkeypatch.setattr(mailboxes, "primary", lambda owner: SimpleNamespace(address=owner))
    monkeypatch.setattr(
        mailboxes,
        "build_imap_client",
        lambda mailbox: SimpleNamespace(
            _ensure_connected=lambda: connection, disconnect=lambda: None
        ),
    )
    mailbox = RetirementMailbox("owner@example.test")
    try:
        drafts, draft_scope = mailbox.inventory()
        assert draft_scope["complete"] and [row["uid"] for row in drafts] == ["1"]
        sent, sent_scope = mailbox.inventory(
            "Sent", search_header="Message-ID", search_value=str(message["Message-ID"])
        )
        assert sent_scope["complete"] and len(sent) == 1
        assert mailbox.inventory(
            "Trash", search_header="Message-ID", search_value=str(message["Message-ID"])
        )[0] == []
        target = {"folder": draft_scope["folder"], "uidvalidity": draft_scope["uidvalidity"], "uid": "1"}
        trash = {"folder": mailbox.folder, "uidvalidity": "7"}
        result = mailbox.move(target, trash)
        assert result["copyuid"] == {"uidvalidity": "7", "uid": "1002"}
        assert mailbox.inventory()[0] == []
        trashed, trash_scope = mailbox.inventory(
            "Trash", search_header="Message-ID", search_value=str(message["Message-ID"])
        )
        assert trash_scope["complete"] and len(trashed) == 1
        assert moves == ["1"]
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT count(*) FROM sent").fetchone()[0] == 1002
            assert conn.execute("SELECT count(*) FROM trash").fetchone()[0] == 1002
    finally:
        mailbox.close()


@pytest.mark.parametrize("failure", ["aggregate-bytes", "wrong-uid", "truncated"])
def test_inventory_bounds_and_complete_uid_coverage(failure):
    from zylch.services.exact_draft_publication_imap import ReviewMailbox
    from zylch.services.exact_draft_delivery import EvidenceRefusal

    raw = b"Content-Type: text/plain\r\n\r\n" + b"x" * 1800000

    class Connection:
        untagged_responses = {"UIDVALIDITY": [b"7"]}

        def list(self):
            return "OK", [b'(\\Drafts) "/" "Drafts"']

        def select(self, folder, readonly=False):
            return "OK", []

        def uid(self, command, *args):
            if command == "SEARCH":
                return "OK", [b"1 2 3 4 5"]
            actual = b"99" if failure == "wrong-uid" else args[0]
            size = len(raw) + int(failure == "truncated")
            return "OK", [
                (b"1 (UID " + actual + b" FLAGS () RFC822.SIZE " + str(size).encode() + b")", raw)
            ]

    mailbox = object.__new__(ReviewMailbox)
    mailbox.conn = Connection()
    with pytest.raises(
        EvidenceRefusal,
        match="inventory_byte_limit" if failure == "aggregate-bytes" else "incomplete_inventory",
    ):
        mailbox.inventory()
