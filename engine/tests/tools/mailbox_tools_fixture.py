"""Native mailbox boundary and real SQLite receipts for draft-tool regression tests."""
from __future__ import annotations

from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from hashlib import sha256
from threading import RLock

import pytest

OWNER = "owner@company.test"


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Override retired parent SaaS cleanup while retaining all parent profile fixtures."""
    yield


def message(raw):
    return BytesParser(policy=policy.default).parsebytes(raw)


class NativeState:
    """Simulate native container operations, not the service's receipt decisions."""
    def __init__(self):
        self.lock = RLock()
        self.drafts, self.sent_rows, self.trashed = {}, [], {}
        self.create_calls, self.update_calls, self.send_calls, self.trash_calls = [], [], [], []
        self.sent_visible, self.sent_error = True, None
        self.before_send = None
        self.before_update = None
        self.refusal = None
        self.lose_ack = False
        self.transport_error = None
        self.update_error = None
        self.unknown_accepted = False

    def client(self, owner):
        assert owner == OWNER, "Synthetic provider accessed a different mailbox"
        return NativeClient(self)

    def native(self, draft):
        identifier = draft.get("provider_draft_id")
        with self.lock:
            return self.drafts[identifier]

    def edit(self, draft, **fields):
        """A separate client saves the same native container without service bookkeeping."""
        from zylch.services.mailbox_draft_mime import update_raw
        with self.lock:
            row = self.native(draft)
            row["raw"] = update_raw(row["raw"], fields)

    def sent_message(self, index=0):
        return message(self.sent_rows[index]["raw"])


class NativeClient:
    def __init__(self, state):
        self.state = state

    def close(self):
        pass

    def list_drafts(self):
        with self.state.lock:
            return [dict(row) for row in self.state.drafts.values()]

    def get_draft(self, identifier):
        with self.state.lock:
            row = self.state.drafts.get(identifier)
            return {**row, "identity": {"id": identifier, "message_id": row["message_id"],
                "raw_sha256": sha256(row["raw"]).hexdigest()}} if row is not None else None

    def find_drafts(self, message_id):
        return [row for row in self.list_drafts() if str(message(row["raw"])["Message-ID"]) == message_id]

    def thread_for_message(self, message_id):
        return "synthetic-native-thread"

    def create_draft(self, raw, thread_id=None):
        with self.state.lock:
            identifier = "native-draft-" + str(len(self.state.create_calls) + 1) + "-container"
            self.state.create_calls.append(raw)
            row = {"id": identifier, "message_id": "native-message-" + identifier,
                   "thread_id": thread_id or "thread-" + identifier, "raw": raw}
            self.state.drafts[identifier] = row
            return dict(row)

    def update_draft(self, identifier, raw, **kwargs):
        with self.state.lock:
            self.state.update_calls.append((identifier, raw))
        if self.state.before_update is not None:
            self.state.before_update()
        with self.state.lock:
            if self.state.update_error is not None:
                raise self.state.update_error
            old = self.state.drafts.pop(identifier)
            self.state.trashed[old["message_id"]] = {**old, "labels": ["TRASH"]}
            new_id = "replacement-" + str(len(self.state.update_calls))
            self.state.drafts[new_id] = {**old, "id": new_id, "message_id": "message-" + new_id, "raw": raw}
            return self.get_draft(new_id)

    def send_draft(self, identifier, raw, **kwargs):
        with self.state.lock:
            self.state.send_calls.append((identifier, raw))
        if self.state.before_send is not None:
            self.state.before_send()
        if self.state.refusal is not None:
            raise self.state.refusal
        if self.state.transport_error is not None and not self.state.unknown_accepted:
            raise self.state.transport_error
        with self.state.lock:
            if identifier not in self.state.drafts:
                from zylch.email.mailbox_errors import MailboxProviderError
                error = MailboxProviderError("named_draft_not_found", non_dispatch=True)
                error.non_dispatch = True
                raise error
            row = {"message_id": "native-sent-" + str(len(self.state.sent_rows) + 1),
                   "thread_id": "synthetic-native-thread", "raw": raw, "labels": ["SENT"]}
            self.state.sent_rows.append(row)
        if self.state.transport_error is not None:
            raise self.state.transport_error
        if self.state.lose_ack:
            raise TimeoutError("Synthetic lost send acknowledgement")
        return {"message_id": row["message_id"]}

    def sent(self, message_id):
        if self.state.sent_error is not None:
            raise self.state.sent_error
        if not self.state.sent_visible:
            return []
        with self.state.lock:
            return [dict(row) for row in self.state.sent_rows
                    if str(message(row["raw"])["Message-ID"]) == message_id]

    def trash_draft(self, identifier, **kwargs):
        with self.state.lock:
            self.state.trash_calls.append(identifier)
            row = self.state.drafts.pop(identifier)
            row["labels"] = ["TRASH"]
            self.state.trashed[row["message_id"]] = row
            return {"ok": True, "state": "trashed", "message_id": row["message_id"], "labels": ["TRASH"]}

    def retire_sent_draft(self, identifier, **kwargs):
        with self.state.lock:
            if identifier not in self.state.drafts:
                return {"ok": True, "state": "absent"}
        return self.trash_draft(identifier, **kwargs)

    def recover_trash(self, identity):
        with self.state.lock:
            row = self.state.trashed.get(identity["message_id"])
            return {"ok": row is not None and identity["id"] not in self.state.drafts,
                    "state": "trashed"}

    def get_message(self, message_id):
        with self.state.lock:
            row = self.state.trashed.get(message_id)
            return dict(row) if row is not None else None


@dataclass
class MailboxFixture:
    storage: object
    state: NativeState
    db_path: str

    def draft(self, **fields):
        values = {"to": ["customer@example.test"], "subject": "Synthetic request", "body": "Saved body."}
        values.update(fields)
        return self.storage.create_draft(OWNER, **values)

    def tool(self):
        from zylch.tools.gmail_tools import SendDraftTool
        return SendDraftTool(None, self.storage, OWNER)

    def service(self):
        from zylch.services.mailbox_drafts import MailboxDrafts
        return MailboxDrafts(OWNER)

    def send_receipts(self):
        from sqlalchemy import select
        from zylch.storage.mailbox_operations import RECEIPTS
        from zylch.storage.database import get_engine
        with get_engine().connect() as conn:
            return [dict(row) for row in conn.execute(select(RECEIPTS).where(
                RECEIPTS.c.owner == OWNER, RECEIPTS.c.kind == "send")).mappings()]

    def no_private_drafts(self):
        from zylch.storage.database import get_session
        from zylch.storage.models import Draft
        with get_session() as session:
            assert session.query(Draft).count() == 0


@pytest.fixture
def mailbox(tmp_path, monkeypatch):
    from zylch.storage import database as db
    from zylch.storage.storage import Storage
    # Parent _isolate_profile_dir remains active: no --confcutdir and no SaaS fixture.
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "mailbox-tools.db"))
    monkeypatch.setenv("EMAIL_ADDRESS", OWNER)
    monkeypatch.setenv("OWNER_ID", "mailbox-tools-owner")
    db.dispose_engine()
    db.init_db()
    state = NativeState()
    monkeypatch.setattr("zylch.email.imap_mailbox.IMAPMailbox", state.client)
    yield MailboxFixture(Storage.get_instance(), state, str(tmp_path / "mailbox-tools.db"))
    db.dispose_engine()
