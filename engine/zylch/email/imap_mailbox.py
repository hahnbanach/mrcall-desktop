"""Mailbox drafts over the platform's existing app-password IMAP/SMTP path."""

from __future__ import annotations

from contextlib import nullcontext
from email import policy
from email.parser import BytesParser
import hashlib
import json
import re
import time
from typing import Any

from zylch.services.exact_draft_delivery import EvidenceRefusal
from zylch.services.exact_draft_retirement_imap import RetirementMailbox

from .imap_mailbox_protocol import IMAPProtocol, _quote, _rfc_id
from .mailbox_errors import MailboxProviderError


def _mime_signature(raw: bytes, *, sending: bool = False):
    message = BytesParser(policy=policy.default).parsebytes(raw)
    ignored = {"message-id", "date"} if sending else set()
    headers = sorted((name.lower(), str(value)) for name, value in message.items()
                     if name.lower() not in ignored and not name.lower().startswith("received")
                     and name.lower() not in {"return-path", "delivered-to", "x-received"})
    parts = [(part.get_content_type(), part.get_content_disposition(), part.get_filename(),
              str(part.get("Content-ID") or ""), None if part.is_multipart() else part.get_payload(decode=True))
             for part in message.walk()]
    return headers, parts


class IMAPMailbox(IMAPProtocol):
    """Exact current-message handles, one APPEND/DATA and recoverable UID MOVE."""

    def __init__(self, owner: str, *, client=None, mailbox_id: str | None = None) -> None:
        self.owner = owner.strip().lower()
        self.client = None
        self.folder = None
        self._closed = False
        self._deadline = time.monotonic() + 120
        self._scope = None
        try:
            if client is None:
                from . import mailboxes

                mailbox = mailboxes.primary(self.owner)
                if mailbox is None or mailbox.address.strip().lower() != self.owner:
                    raise MailboxProviderError("mailbox_unavailable", non_dispatch=True)
                mailbox_id = mailbox.id
                client = mailboxes.build_imap_client(mailbox)
            if (str(client.email_addr).strip().lower() != self.owner or not mailbox_id):
                raise MailboxProviderError("mailbox_owner_mismatch", non_dispatch=True)
            self.client = client
            material = [self.owner, mailbox_id, str(client.imap_host).lower(), int(client.imap_port)]
            self.binding = hashlib.sha256(json.dumps(material, separators=(",", ":")).encode()).hexdigest()
            self._scope = client.provider_deadline(self._deadline) if hasattr(client, "provider_deadline") else nullcontext()
            self._scope.__enter__()
            self.conn = client._ensure_connected()
            capabilities = {c.decode().upper() if isinstance(c, bytes) else str(c).upper()
                            for c in getattr(self.conn, "capabilities", [])}
            self.gmail_extensions = "X-GM-EXT-1" in capabilities
            self.can_move = "MOVE" in capabilities
        except MailboxProviderError:
            self.close()
            raise
        except Exception:
            self.close()
            raise MailboxProviderError("mailbox_connection_unavailable", non_dispatch=True) from None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._scope is not None:
                scope, self._scope = self._scope, None
                try:
                    # The client's final deadline check still uses its socket.
                    # Complete that scope before logout closes the descriptor.
                    scope.__exit__(None, None, None)
                except Exception:
                    raise MailboxProviderError("imap_observation_unavailable") from None
        finally:
            if self.client is not None:
                self.client.disconnect()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def list_drafts(self) -> list[dict[str, Any]]:
        return [row for row in self._inventory("Drafts")
                if not {"SENT", "TRASH"}.intersection(row["labels"]) and "\\Deleted" not in row["flags"]]

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        return self._draft(draft_id)

    def find_drafts(self, message_id: str) -> list[dict[str, Any]]:
        wanted = _rfc_id(message_id)
        return [row for row in self._inventory("Drafts", "HEADER", "Message-ID", _quote(wanted))
                if self._header(row["raw"], "Message-ID") == wanted
                and not {"SENT", "TRASH"}.intersection(row["labels"]) and "\\Deleted" not in row["flags"]]

    def sent(self, message_id: str) -> list[dict[str, Any]]:
        wanted = _rfc_id(message_id)
        return [row for row in self._inventory("Sent", "HEADER", "Message-ID", _quote(wanted))
                if self._header(row["raw"], "Message-ID") == wanted]

    def thread_for_message(self, message_id: str) -> None:
        _rfc_id(message_id)
        # IMAP threading is conveyed in MIME In-Reply-To/References, not an API
        # container parameter. Source authority is checked by the service.
        return None

    def conversation(self, message_id: str) -> list[dict[str, Any]]:
        wanted = _rfc_id(message_id)
        quote = _quote(wanted)
        if self.gmail_extensions:
            source = [row for row in self._inventory("All", "HEADER", "Message-ID", quote)
                      if self._header(row["raw"], "Message-ID") == wanted]
            if len(source) != 1:
                raise MailboxProviderError("imap_source_inventory_incomplete")
            rows = self._inventory("All", "X-GM-THRID", source[0]["thread_id"])
            if (any(row["thread_id"] != source[0]["thread_id"] for row in rows)
                    or sum(self._header(row["raw"], "Message-ID") == wanted for row in rows) != 1):
                raise MailboxProviderError("imap_source_inventory_incomplete")
            return rows
        criteria = "(OR HEADER Message-ID " + quote + " OR HEADER References " + quote + " HEADER In-Reply-To " + quote + ")"
        rows = self._inventory("All", criteria)
        selected = []
        for row in rows:
            message = BytesParser(policy=policy.default).parsebytes(row["raw"], headersonly=True)
            refs = str(message.get("References") or "").split()
            if (self._header(row["raw"], "Message-ID") == wanted
                    or self._header(row["raw"], "In-Reply-To") == wanted or wanted in refs):
                selected.append(row)
        if sum(self._header(row["raw"], "Message-ID") == wanted for row in selected) != 1:
            raise MailboxProviderError("imap_source_inventory_incomplete")
        return selected

    def create_draft(self, raw: bytes, thread_id=None) -> dict[str, Any]:
        if not isinstance(raw, bytes) or not raw or len(raw) > self.MAX_MESSAGE_BYTES:
            raise MailboxProviderError("mailbox_message_invalid", non_dispatch=True)
        message_id = _rfc_id(self._header(raw, "Message-ID"))
        self._select("Drafts")
        # An existing identity is never an invitation to APPEND another copy.
        if self.find_drafts(message_id):
            raise MailboxProviderError("imap_message_id_already_exists", non_dispatch=True)
        self._select("Drafts")
        self.conn.untagged_responses.pop("APPENDUID", None)
        status, data = self._call("append", self.folder, "(\\Draft)", None, raw)
        if status != "OK":
            raise MailboxProviderError("imap_append_refused", non_dispatch=True)
        append_responses = list(data or []) + list(self.conn.untagged_responses.get("APPENDUID", []))
        found = self.find_drafts(message_id)
        if len(found) != 1:
            raise MailboxProviderError("imap_append_unconfirmed")
        if _mime_signature(found[0]["raw"]) != _mime_signature(raw):
            raise MailboxProviderError("imap_append_readback_differs")
        mappings = []
        for item in append_responses:
            if isinstance(item, bytes):
                match = re.search(rb"(?:APPENDUID )?(\d+) (\d+)(?=\]|$)", item)
                if b"APPENDUID" in item and not match:
                    raise MailboxProviderError("imap_appenduid_invalid")
                if match:
                    mappings.append(tuple(value.decode() for value in match.groups()))
        expected = (found[0]["identity"]["uidvalidity"], found[0]["identity"]["uid"])
        if mappings and set(mappings) != {expected}:
            raise MailboxProviderError("imap_appenduid_mismatch")
        return found[0]

    def update_draft(self, draft_id: str, raw: bytes, thread_id=None, *, expected_identity=None) -> dict[str, Any]:
        if not isinstance(raw, bytes) or not raw or len(raw) > self.MAX_MESSAGE_BYTES:
            raise MailboxProviderError("mailbox_message_invalid", non_dispatch=True)
        current = self.get_draft(draft_id)
        if current is None:
            raise MailboxProviderError("named_draft_not_found", non_dispatch=True)
        self._expected(current, expected_identity)
        new_id = _rfc_id(self._header(raw, "Message-ID"))
        if new_id == current["identity"]["rfc_message_id"]:
            raise MailboxProviderError("imap_replacement_message_id_reused", non_dispatch=True)
        self.trash_draft(draft_id, expected_identity=current["identity"])
        try:
            return self.create_draft(raw, thread_id=thread_id)
        except MailboxProviderError as error:
            # The old draft has moved. An APPEND rejection is not evidence that
            # the whole replacement had no effect; recovery retains its fence.
            error.non_dispatch = False
            error.progress = {"old_draft_retired": True, "old_identity": current["identity"]}
            raise

    def recover_trash(self, identity: dict[str, Any]) -> dict[str, Any]:
        decoded = self._snapshot(identity)
        original = self._token({"k": "d", "f": decoded["f"], "v": decoded["v"], "u": decoded["u"]})
        if self.get_draft(original) is not None:
            return {"ok": False, "state": "present", "cause": "imap_trash_unconfirmed"}
        matches = self._trashed(identity)
        if len(matches) != 1:
            return {"ok": False, "state": "unconfirmed", "cause": "imap_trash_unconfirmed"}
        return {"ok": True, "state": "trashed", "verified": True,
                "identity": matches[0]["identity"], "message_id": matches[0]["message_id"]}

    def trash_draft(self, draft_id: str, *, expected_identity=None) -> dict[str, Any]:
        current = self.get_draft(draft_id)
        if current is None:
            raise MailboxProviderError("named_draft_not_found", non_dispatch=True)
        self._expected(current, expected_identity)
        if not self.can_move:
            raise MailboxProviderError("imap_exact_move_unsupported", non_dispatch=True)
        identity = current["identity"]
        trash_validity = self._select("Trash")
        trash = {"folder": self.folder, "uidvalidity": trash_validity}
        target = {"folder": identity["folder"], "uidvalidity": identity["uidvalidity"], "uid": identity["uid"]}
        self.conn.untagged_responses.pop("COPYUID", None)
        try:
            self._check()
            result = RetirementMailbox.move(self, target, trash)
            self._check()
        except EvidenceRefusal:
            raise MailboxProviderError("imap_move_unconfirmed") from None
        except Exception:
            raise MailboxProviderError("imap_move_unconfirmed") from None
        proof = self.recover_trash(identity)
        if not proof["ok"]:
            raise MailboxProviderError("imap_trash_unconfirmed")
        copied = result.get("copyuid")
        if copied and (copied["uidvalidity"] != proof["identity"]["uidvalidity"]
                       or copied["uid"] != proof["identity"]["uid"]):
            raise MailboxProviderError("imap_copyuid_mismatch")
        return {**proof, "id": draft_id, "status": "trashed", "copyuid": copied}

    def retire_sent_draft(self, draft_id: str, *, expected_identity=None) -> dict[str, Any]:
        current = self.get_draft(draft_id)
        if current is None:
            return {"ok": True, "state": "absent", "verified": True}
        self._expected(current, expected_identity)
        return self.trash_draft(draft_id, expected_identity=expected_identity)

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        decoded = self._decode(message_id, "m")
        identity = {"binding": self.binding, "folder": decoded["f"], "uidvalidity": decoded["v"],
                    "uid": decoded["u"], "raw_sha256": decoded["h"],
                    "rfc_message_id": decoded["r"], "gmail_message_id": decoded["g"]}
        for special in ("Drafts", "Sent", "Trash", "All"):
            validity = self._select(special)
            if self.folder != decoded["f"]:
                continue
            if validity != decoded["v"]:
                raise MailboxProviderError("imap_uidvalidity_or_folder_changed")
            rows = self._inventory(special, "UID", decoded["u"])
            if rows:
                if len(rows) != 1 or not self._matches(rows[0], identity):
                    raise MailboxProviderError("imap_message_identity_changed")
                return rows[0]
            break
        # MOVE changes the per-folder UID, but the immutable provider message
        # and raw digest permit read-only recovery in Trash, never reassociation
        # to another current draft.
        matches = self._trashed(identity)
        if len(matches) > 1:
            raise MailboxProviderError("imap_message_identity_ambiguous")
        return matches[0] if matches else None

    def send_draft(self, draft_id: str, raw: bytes, *, expected_identity=None) -> dict[str, Any]:
        current = self.get_draft(draft_id)
        if current is None:
            raise MailboxProviderError("named_draft_not_found", non_dispatch=True)
        self._expected(current, expected_identity)
        if _mime_signature(raw, sending=True) != _mime_signature(current["raw"], sending=True):
            raise MailboxProviderError("imap_draft_changed_before_send", non_dispatch=True)
        if self._header(raw, "Message-ID") == current["identity"]["rfc_message_id"]:
            raise MailboxProviderError("imap_send_message_id_reused", non_dispatch=True)
        return self.send_message(raw)

    def send_message(self, raw: bytes) -> dict[str, Any]:
        from .imap_mailbox_smtp import send_raw

        return send_raw(self.client, raw)
