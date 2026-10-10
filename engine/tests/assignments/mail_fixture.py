"""Real IMAP protocol bytes and private SQLite rows for task acceptance."""

import re
import uuid
from datetime import datetime
from email.message import EmailMessage
from email import message_from_bytes
from zylch.email import mailboxes
from zylch.email.imap_client import IMAPClient, _parse_message_bytes
from zylch.storage import database as db
from zylch.storage.models import Email

ROOT = "<customer-root@example.test>"
REPLY = "<alice-reply@example.test>"


class MailFixture:
    def __init__(self, monkeypatch):
        self.messages = {"INBOX": {}, '"Archive"': {}, '"Sent"': {}}
        self.calls, self.fail_search, self.fail_fetch = [], False, False
        self.uidvalidity, self.closed, self.selected, self.next_uid = 11, 0, None, 1
        self.box = mailboxes.ensure_primary_mailbox()
        monkeypatch.setattr(mailboxes, "build_imap_client", self.client)
        self.root_id = self.add(ROOT, "customer@example.test", "alice@example.test")
        self.reply_id = self.add(
            REPLY, "alice@example.test", "customer@example.test", folder='"Sent"', reply=ROOT
        )

    def client(self, mailbox):
        client = IMAPClient(mailbox.address, "fixture-only")
        client._conn = self
        return client

    def add(
        self,
        mid,
        sender,
        recipient,
        *,
        folder='"Archive"',
        reply=None,
        date="Thu, 08 Oct 2026 10:00:00 +0000",
        body="A real reply",
        headers=None,
        store=True,
    ):
        message = EmailMessage()
        message["Message-ID"], message["From"], message["To"] = mid, sender, recipient
        if date:
            message["Date"] = date
        if reply:
            message["In-Reply-To"], message["References"] = reply, ROOT
        for name, value in (headers or {}).items():
            message[name] = value
        message.set_content(body)
        uid, source_id = self.next_uid, str(uuid.uuid4())
        self.next_uid += 1
        raw = message.as_bytes()
        self.messages[folder][uid] = raw
        if store:
            parsed = _parse_message_bytes(raw)
            with db.get_session() as session:
                session.add(
                    Email(
                        id=source_id,
                        owner_id="alice@example.test",
                        mailbox_id=self.box,
                        gmail_id=mid,
                        thread_id=parsed["thread_id"],
                        message_id_header=mid,
                        from_email=sender,
                        to_email=recipient,
                        references=parsed["references"],
                        in_reply_to=parsed["in_reply_to"],
                        date=datetime(2026, 10, 8, 10),
                        body_plain=body,
                    )
                )
        return source_id

    def replace_reply(self, **kwargs):
        with db.get_session() as session:
            session.query(Email).filter(Email.id == self.reply_id).delete()
        self.messages['"Sent"'].clear()
        self.reply_id = self.add(
            REPLY,
            kwargs.pop("sender", "alice@example.test"),
            kwargs.pop("recipient", "customer@example.test"),
            folder='"Sent"',
            reply=kwargs.pop("reply", ROOT),
            **kwargs,
        )

    def noop(self):
        return "OK", []

    def logout(self):
        self.closed += 1
        return "BYE", []

    def list(self):
        return "OK", [b'(\\Sent) "/" "Sent"', b'(\\Archive) "/" "Archive"']

    def select(self, folder, readonly=False):
        assert readonly
        self.selected = folder
        self.calls.append(("EXAMINE", folder))
        return "OK", [str(len(self.messages[folder])).encode()]

    def response(self, code):
        return code, [str(self.uidvalidity if code == "UIDVALIDITY" else self.next_uid).encode()]

    def uid(self, command, *args):
        self.calls.append((command, self.selected, args))
        if command == "SEARCH":
            if self.fail_search:
                return "NO", [b"fixture unavailable"]
            criteria = args[-1]
            targets = re.findall(r'"(<[^" ]+>)"', criteria)
            result = []
            for uid, raw in self.messages[self.selected].items():
                msg = message_from_bytes(raw)
                fields = (
                    ["Message-ID"]
                    if "OR" not in criteria
                    else ["Message-ID", "References", "In-Reply-To"]
                )
                if any(target in str(msg.get(field, "")) for target in targets for field in fields):
                    result.append(str(uid).encode())
            return "OK", [b" ".join(result)]
        if command == "FETCH":
            if self.fail_fetch:
                return "NO", []
            result = []
            for value in args[0].split(","):
                uid = int(value)
                raw = self.messages[self.selected].get(uid)
                if raw is None:
                    continue
                assert "BODY.PEEK" in args[1]
                if "HEADER.FIELDS" in args[1]:
                    raw = (
                        "Message-ID: " + str(message_from_bytes(raw)["Message-ID"]) + "\r\n\r\n"
                    ).encode()
                result.append((f"1 (UID {uid} BODY[] {{{len(raw)}}}".encode(), raw))
            return "OK", result
        raise AssertionError(command)
