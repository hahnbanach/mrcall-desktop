"""A fake imaplib connection, faithful to the response shapes we parse.

The sync path's failure mode was never "the code did the wrong thing
with a message" — it was "the code read a protocol failure as an empty
mailbox". Testing that needs a server that can actually fail: refuse a
SELECT, answer NO to a SEARCH, return nothing for a FETCH. Mocking the
IMAPClient itself would test the mock; this fakes the layer *below* it
so the real IMAPClient parsing, UID handling and error raising run.

Response shapes follow imaplib:

- ``select`` -> ``("OK", [b"<exists>"])`` with UIDVALIDITY / UIDNEXT
  available through ``response()`` (imaplib turns ``* OK [UIDVALIDITY
  12345]`` into an untagged response entry);
- ``uid("SEARCH", None, criteria)`` -> ``("OK", [b"1 2 3"])``;
- ``uid("FETCH", ...)`` -> a list whose message entries are
  ``(prefix_bytes, payload_bytes)`` tuples separated by ``b")"``.
"""

from __future__ import annotations

import re
from datetime import datetime
from email.utils import format_datetime
from typing import Dict, List, Optional


def build_raw_message(
    message_id: str,
    subject: str = "Subject",
    from_addr: str = "sender@example.com",
    to_addr: str = "support@example.com",
    date: Optional[datetime] = None,
    body: str = "Body text",
) -> bytes:
    """Build a minimal but real RFC 822 message."""
    when = format_datetime(date) if date else "Tue, 29 Jul 2026 19:33:00 +0200"
    return (
        f"Message-ID: {message_id}\r\n"
        f"From: Test Sender <{from_addr}>\r\n"
        f"To: {to_addr}\r\n"
        f"Subject: {subject}\r\n"
        f"Date: {when}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"\r\n"
        f"{body}\r\n"
    ).encode("utf-8")


def _message_date(raw: bytes):
    """Date header of a raw message, or None when unparsable."""
    from email.utils import parsedate_to_datetime

    match = re.search(rb"^Date:\s*(.+)$", raw, re.MULTILINE)
    if not match:
        return None
    try:
        return parsedate_to_datetime(match.group(1).decode().strip())
    except (TypeError, ValueError):
        return None


class FakeFolder:
    """One mailbox: a UID space plus the messages living in it."""

    def __init__(self, uidvalidity: int = 1000, messages: Optional[Dict[int, bytes]] = None):
        self.uidvalidity = uidvalidity
        self.messages: Dict[int, bytes] = dict(messages or {})
        # UIDs whose FETCH answers non-OK: a message the server refuses
        # to hand over (hiccup, oversized, transient error).
        self.fetch_errors: set = set()
        # UIDs the server simply omits from the FETCH response: what an
        # expunge between SEARCH and FETCH looks like on the wire.
        self.expunged: set = set()
        # UIDs flagged \Draft, so `NOT DRAFT` can be exercised.
        self.drafts: set = set()
        self.select_fails = False
        self.search_fails = False

    @property
    def uidnext(self) -> int:
        return (max(self.messages) + 1) if self.messages else 1

    def add(self, uid: int, raw: bytes) -> None:
        self.messages[uid] = raw


class FakeIMAPConn:
    """Minimal imaplib.IMAP4_SSL stand-in covering the commands we issue."""

    def __init__(self, folders: Dict[str, FakeFolder]):
        self.folders = folders
        self.selected: Optional[str] = None
        self.readonly: Optional[bool] = None
        self._pending_codes: Dict[str, List[bytes]] = {}
        # Every command issued, for assertions about read-only-ness.
        self.commands: List[tuple] = []

    # -- helpers ---------------------------------------------------
    def _folder(self, name: str) -> Optional[FakeFolder]:
        key = name.strip('"')
        for candidate, folder in self.folders.items():
            if candidate.strip('"') == key:
                return folder
        return None

    # -- imaplib surface -------------------------------------------
    def noop(self):
        return "OK", [b"NOOP completed"]

    def logout(self):
        return "BYE", [b""]

    def select(self, mailbox="INBOX", readonly=False):
        self.commands.append(("SELECT", mailbox, readonly))
        folder = self._folder(mailbox)
        if folder is None or folder.select_fails:
            self._pending_codes = {}
            return "NO", [b"[NONEXISTENT] Unknown Mailbox"]
        self.selected = mailbox
        self.readonly = readonly
        self._pending_codes = {
            "UIDVALIDITY": [str(folder.uidvalidity).encode()],
            "UIDNEXT": [str(folder.uidnext).encode()],
        }
        return "OK", [str(len(folder.messages)).encode()]

    def response(self, code):
        return code, self._pending_codes.pop(code, [None])

    def list(self):
        lines = []
        for name in self.folders:
            flags = "\\HasNoChildren"
            if name.strip('"').lower().endswith("sent mail"):
                flags += " \\Sent"
            if name.strip('"').lower().endswith("all mail"):
                flags += " \\All"
            lines.append(f'({flags}) "/" "{name.strip(chr(34))}"'.encode())
        return "OK", lines

    def uid(self, command, *args):
        self.commands.append(("UID", command) + tuple(args))
        folder = self._folder(self.selected or "")
        if folder is None:
            return "NO", [b"No mailbox selected"]

        if command.upper() == "SEARCH":
            if folder.search_fails:
                return "NO", [b"SEARCH failed: server error"]
            criteria = args[-1]
            uids = self._apply_criteria(folder, criteria)
            return "OK", [" ".join(str(u) for u in uids).encode()]

        if command.upper() == "FETCH":
            uid_set, items = args[0], args[1]
            wanted = [int(tok) for tok in str(uid_set).split(",") if tok]
            if any(uid in folder.fetch_errors for uid in wanted):
                return "NO", [b"FETCH failed: server error"]
            headers_only = "HEADER.FIELDS" in items
            data: List = []
            for uid in wanted:
                raw = folder.messages.get(uid)
                if raw is None or uid in folder.expunged:
                    continue
                if headers_only:
                    match = re.search(rb"^Message-ID:.*$", raw, re.MULTILINE)
                    payload = (match.group(0) if match else b"") + b"\r\n\r\n"
                    label = b"BODY[HEADER.FIELDS (MESSAGE-ID)]"
                else:
                    payload = raw
                    label = b"BODY[]"
                prefix = b"%d (UID %d %s {%d}" % (uid, uid, label, len(payload))
                data.append((prefix, payload))
                data.append(b")")
            if not data:
                return "OK", [None]
            return "OK", data

        return "NO", [b"Unsupported"]

    # -- search criteria -------------------------------------------
    def _apply_criteria(self, folder: FakeFolder, criteria) -> List[int]:
        """Evaluate the criteria shapes the sync path actually builds.

        ``(SINCE "dd-Mon-yyyy" NOT DRAFT)`` and
        ``(OR UID n:* SINCE "dd-Mon-yyyy" NOT DRAFT)``.

        SINCE is evaluated for real, against each message's Date header.
        That matters: if the fake treated SINCE as "everything", a test
        claiming the UID cursor found a message would actually be
        watching the date window find it, and the cursor could be
        completely broken without any test noticing.
        """
        text = criteria.decode() if isinstance(criteria, bytes) else str(criteria)
        all_uids = sorted(folder.messages)

        uid_match = re.search(r"UID\s+(\d+):\*", text)
        since_match = re.search(r'SINCE\s+"([^"]+)"', text)

        selected: set = set()
        if uid_match:
            low = int(uid_match.group(1))
            in_range = [u for u in all_uids if u >= low]
            # IMAP's `n:*` always yields the highest UID even when it is
            # below n. Reproduce that quirk: it is exactly the kind of
            # detail a cursor implementation has to survive.
            if not in_range and all_uids:
                in_range = [all_uids[-1]]
            selected.update(in_range)
        if since_match:
            floor = datetime.strptime(since_match.group(1), "%d-%b-%Y").date()
            for uid in all_uids:
                when = _message_date(folder.messages[uid])
                if when is not None and when.date() >= floor:
                    selected.add(uid)
        if not uid_match and not since_match:
            selected.update(all_uids)

        if "NOT DRAFT" in text.upper():
            selected -= folder.drafts

        return sorted(selected)


def make_client(folders: Dict[str, FakeFolder], email_addr: str = "support@example.com"):
    """An IMAPClient wired to a FakeIMAPConn (no sockets, no auth)."""
    from zylch.email.imap_client import IMAPClient

    client = IMAPClient(email_addr=email_addr, password="not-a-real-password")
    client._conn = FakeIMAPConn(folders)
    return client
