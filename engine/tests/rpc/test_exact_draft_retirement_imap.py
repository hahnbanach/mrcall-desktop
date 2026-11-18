"""Real IMAP adapter bounded complete candidate inventories and MOVE."""

from email import policy
from email.parser import BytesParser
import sqlite3
import pytest
from tests.rpc.test_exact_draft_retirement import (
    setup as recovery_setup,
    invoke,
    move_count,
    RecoveryMailbox,
    OWNER,
)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    yield from recovery_setup.__wrapped__(tmp_path, monkeypatch)


def test_real_imap_move_adapter_and_complete_uid_fetch(setup, monkeypatch):
    from types import SimpleNamespace
    from zylch.email import mailboxes
    from zylch.services.exact_draft_retirement_imap import RetirementMailbox

    row, path = setup
    with sqlite3.connect(path / "provider.db") as conn:
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
            with sqlite3.connect(path / "provider.db") as conn:
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
            acknowledgment = RecoveryMailbox(OWNER).move({"uid": args[0]}, {})
            return "OK", [f"[COPYUID 7 1 {acknowledgment['copyuid']['uid']}] moved".encode()]

    connection = Connection()
    monkeypatch.setattr(mailboxes, "primary", lambda owner: SimpleNamespace(address=owner))
    monkeypatch.setattr(
        mailboxes,
        "build_imap_client",
        lambda mailbox: SimpleNamespace(
            _ensure_connected=lambda: connection, disconnect=lambda: None
        ),
    )
    preview = invoke(row, factory=RetirementMailbox)
    assert preview["ok"]
    assert invoke(row, preview["target"], True, factory=RetirementMailbox)["ok"]
    assert move_count(path) == 1


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
