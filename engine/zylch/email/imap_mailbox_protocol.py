"""Complete exact-message observations on the existing primary IMAP client."""

from __future__ import annotations

import base64
import binascii
from email import policy
from email.parser import BytesParser
import hashlib
import json
import re
import time
from typing import Any

from zylch.services.exact_draft_delivery import EvidenceRefusal
from zylch.services.exact_draft_retirement_imap import RetirementMailbox

from .mailbox_errors import MailboxProviderError


def _rfc_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"<[^<>\s]+@[^<>\s]+>", value):
        raise MailboxProviderError("mailbox_message_id_invalid", non_dispatch=True)
    return value


def _quote(value: str) -> str:
    if not isinstance(value, str) or any(c in value for c in "\r\n\x00"):
        raise MailboxProviderError("mailbox_identity_invalid", non_dispatch=True)
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _fetch_attributes(metadata: bytes) -> dict[bytes, Any]:
    """Parse a bounded imaplib FETCH metadata response, never its MIME literal.

    imaplib separates BODY[] literal bytes from the surrounding metadata. The
    literal's {size} marker is an opaque value here. Quoted strings decode only
    IMAP's two quoted escapes; parentheses inside a string remain ordinary data.
    """
    try:
        if len(metadata) > 65536:
            raise ValueError
        prefix = re.match(rb"(?:\* )?[1-9][0-9]*(?: FETCH)? \(", metadata, re.I)
        if prefix is None:
            raise ValueError
        position = prefix.end()
        count = 0

        def spaces():
            nonlocal position
            start = position
            while position < len(metadata) and metadata[position] == 32:
                position += 1
            return position != start

        def atom():
            nonlocal position
            start = position
            while position < len(metadata) and metadata[position] not in b' ()"':
                if metadata[position] < 33 or metadata[position] == 127 or metadata[position] in b"{%*":
                    raise ValueError
                position += 1
            if position == start:
                raise ValueError
            return metadata[start:position]

        def value(depth=0):
            nonlocal position, count
            count += 1
            if count > 4096 or depth > 8 or position >= len(metadata):
                raise ValueError
            if metadata[position] == 40:
                position += 1
                result = []
                if position < len(metadata) and metadata[position] == 41:
                    position += 1
                    return result
                while True:
                    result.append(value(depth + 1))
                    separated = spaces()
                    if position >= len(metadata):
                        raise ValueError
                    if metadata[position] == 41:
                        position += 1
                        return result
                    if not separated:
                        raise ValueError
            if metadata[position] == 34:
                position += 1
                result = bytearray()
                while position < len(metadata):
                    item = metadata[position]
                    position += 1
                    if item == 34:
                        return bytes(result)
                    if item == 92:
                        if position >= len(metadata) or metadata[position] not in (34, 92):
                            raise ValueError
                        item = metadata[position]
                        position += 1
                    if item in (0, 10, 13):
                        raise ValueError
                    result.append(item)
                raise ValueError
            if metadata[position] == 123:
                start = position
                while position < len(metadata) and metadata[position] != 125:
                    position += 1
                if position >= len(metadata):
                    raise ValueError
                size = metadata[start + 1:position]
                position += 1
                if not size.isdigit():
                    raise ValueError
                return ("literal", int(size))
            return atom()

        attributes = {}
        while position < len(metadata) and metadata[position] != 41:
            name = atom().upper()
            if name in attributes or not spaces():
                raise ValueError
            attributes[name] = value()
            separated = spaces()
            if position < len(metadata) and metadata[position] != 41 and not separated:
                raise ValueError
        if position >= len(metadata) or metadata[position] != 41:
            raise ValueError
        position += 1
        spaces()
        if position != len(metadata):
            raise ValueError
        return attributes
    except (ValueError, TypeError, IndexError):
        raise MailboxProviderError("imap_inventory_incomplete") from None


class IMAPProtocol(RetirementMailbox):
    MAX_MESSAGES = 10000
    MAX_MESSAGE_BYTES = 64 * 1024 * 1024
    MAX_INVENTORY_BYTES = 128 * 1024 * 1024

    def _check(self) -> None:
        if time.monotonic() >= self._deadline:
            raise MailboxProviderError("imap_observation_timeout")

    def _call(self, operation: str, *args, **kwargs):
        self._check()
        try:
            result = getattr(self.conn, operation)(*args, **kwargs)
        except Exception:
            raise MailboxProviderError("imap_provider_unavailable") from None
        self._check()
        return result

    def _select(self, special_use: str) -> str:
        self._check()
        try:
            validity = super()._select(special_use)
        except EvidenceRefusal:
            raise MailboxProviderError("imap_" + special_use.lower() + "_folder_unavailable") from None
        except Exception:
            raise MailboxProviderError("imap_provider_unavailable") from None
        self._check()
        return validity

    def _token(self, value: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(
            {"b": self.binding, **value}, sort_keys=True, separators=(",", ":")
        ).encode()).rstrip(b"=").decode("ascii")

    def _decode(self, token: str, kind: str = "d") -> dict[str, str]:
        try:
            if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,2048}", token):
                raise ValueError
            value = json.loads(base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True))
            required = {"b", "k", "f", "v", "u"}
            if kind == "m":
                required |= {"h", "r", "g"}
            if (not isinstance(value, dict) or set(value) != required or value.get("k") != kind
                    or value.get("b") != self.binding or any(not isinstance(v, str) for v in value.values())
                    or not all(re.fullmatch(r"[1-9][0-9]{0,9}", value[n]) and int(value[n]) <= 4294967295 for n in ("v", "u"))
                    or any(c in value["f"] for c in "\r\n\x00")):
                raise ValueError
            if kind == "m" and (not re.fullmatch(r"[a-f0-9]{64}", value["h"]) or value["g"] and not value["g"].isdigit()):
                raise ValueError
            if self._token({key: item for key, item in value.items() if key != "b"}) != token:
                raise ValueError
            return value
        except (ValueError, TypeError, UnicodeError, binascii.Error):
            raise MailboxProviderError("imap_draft_identity_invalid", non_dispatch=True) from None

    def _search(self, *criteria: str) -> list[str]:
        status, data = self._call("uid", "SEARCH", None, *criteria)
        if status != "OK" or not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], bytes):
            raise MailboxProviderError("imap_inventory_incomplete")
        values = data[0].split()
        if (len(values) > self.MAX_MESSAGES or len(set(values)) != len(values)
                or any(not re.fullmatch(rb"[1-9][0-9]{0,9}", uid) or int(uid) > 4294967295 for uid in values)):
            raise MailboxProviderError("imap_inventory_exceeds_bound")
        return sorted((uid.decode("ascii") for uid in values), key=int)

    @staticmethod
    def _header(raw: bytes, name: str) -> str:
        message = BytesParser(policy=policy.default).parsebytes(raw, headersonly=True)
        values = message.get_all(name, [])
        return str(values[0]).strip() if len(values) == 1 and not getattr(values[0], "defects", []) else ""

    def _fetch(self, uid: str, validity: str, folder: str, special_use: str) -> dict[str, Any]:
        fields = "UID FLAGS RFC822.SIZE BODY.PEEK[]"
        if self.gmail_extensions:
            fields += " X-GM-MSGID X-GM-THRID X-GM-LABELS"
        status, parts = self._call("uid", "FETCH", uid, "(" + fields + ")")
        payloads = [part for part in parts or [] if isinstance(part, tuple)]
        if status != "OK" or len(payloads) != 1 or len(payloads[0]) != 2:
            raise MailboxProviderError("imap_inventory_incomplete")
        meta, raw = payloads[0]
        if not isinstance(meta, bytes) or not isinstance(raw, bytes):
            raise MailboxProviderError("imap_inventory_incomplete")
        suffix = [part for part in parts or [] if isinstance(part, bytes)]
        attributes = _fetch_attributes(meta + b" " + b" ".join(suffix))
        actual, size, flags = (attributes.get(name) for name in (b"UID", b"RFC822.SIZE", b"FLAGS"))
        if (actual != uid.encode() or not isinstance(size, bytes) or not size.isdigit()
                or not isinstance(flags, list) or any(not isinstance(item, bytes) or not item.isascii() for item in flags)
                or int(size) != len(raw) or len(raw) > self.MAX_MESSAGE_BYTES):
            raise MailboxProviderError("imap_inventory_incomplete")
        labels = {special_use.upper()}
        observed_labels = attributes.get(b"X-GM-LABELS")
        if ((self.gmail_extensions or observed_labels is not None)
                and (not isinstance(observed_labels, list)
                     or any(not isinstance(item, bytes) for item in observed_labels))):
            raise MailboxProviderError("imap_inventory_incomplete")
        mapping = {b"\\sent": "SENT", b"\\draft": "DRAFT", b"\\drafts": "DRAFT",
                   b"\\trash": "TRASH", b"\\spam": "SPAM"}
        for label in observed_labels or []:
            if label.lower() in mapping:
                labels.add(mapping[label.lower()])
        if special_use == "Drafts":
            labels.discard("DRAFTS")
            labels.add("DRAFT")
        gm, thread = attributes.get(b"X-GM-MSGID"), attributes.get(b"X-GM-THRID")
        if self.gmail_extensions and any(not isinstance(item, bytes) or not item.isdigit()
                                         or not 0 < int(item) < 2**64 for item in (gm, thread)):
            raise MailboxProviderError("imap_inventory_incomplete")
        message_id = self._header(raw, "Message-ID")
        location = {"k": "d", "f": folder, "v": validity, "u": uid}
        identity = {"binding": self.binding, "folder": folder, "uidvalidity": validity, "uid": uid,
                    "raw_sha256": hashlib.sha256(raw).hexdigest(), "rfc_message_id": message_id,
                    "gmail_message_id": gm.decode() if gm else ""}
        return {"id": self._token(location), "message_id": self._token({**location, "k": "m",
                "h": identity["raw_sha256"], "r": message_id, "g": identity["gmail_message_id"]}),
                "thread_id": thread.decode() if thread else None, "labels": sorted(labels),
                "flags": [item.decode("ascii") for item in flags], "raw": raw, "identity": identity}

    def _inventory(self, special_use: str, *criteria: str) -> list[dict[str, Any]]:
        validity = self._select(special_use)
        folder = self.folder
        uids = self._search(*(criteria or ("ALL",)))
        rows = []
        total = 0
        for uid in uids:
            row = self._fetch(uid, validity, folder, special_use)
            total += len(row["raw"])
            if total > self.MAX_INVENTORY_BYTES:
                raise MailboxProviderError("imap_inventory_exceeds_bound")
            rows.append(row)
        if self._select(special_use) != validity or self.folder != folder or self._search(*(criteria or ("ALL",))) != uids:
            raise MailboxProviderError("imap_inventory_changed")
        return rows

    def _draft(self, token: str) -> dict[str, Any] | None:
        location = self._decode(token)
        validity = self._select("Drafts")
        if self.folder != location["f"] or validity != location["v"]:
            raise MailboxProviderError("imap_uidvalidity_or_folder_changed", non_dispatch=True)
        rows = self._inventory("Drafts", "UID", location["u"])
        if not rows:
            return None
        row = rows[0]
        if len(rows) != 1 or row["id"] != token:
            raise MailboxProviderError("imap_identity_mismatch", non_dispatch=True)
        if {"SENT", "TRASH"}.intersection(row["labels"]) or "\\Deleted" in row["flags"]:
            return None
        return row

    def _expected(self, actual: dict[str, Any], expected: dict[str, Any] | None) -> None:
        if expected is not None and any(expected.get(key) != value for key, value in actual["identity"].items()):
            raise MailboxProviderError("imap_draft_identity_changed", non_dispatch=True)

    def _snapshot(self, identity: dict[str, Any]) -> dict[str, str]:
        required = {"binding", "folder", "uidvalidity", "uid", "raw_sha256", "rfc_message_id", "gmail_message_id"}
        if not isinstance(identity, dict) or not required.issubset(identity):
            raise MailboxProviderError("imap_draft_identity_invalid", non_dispatch=True)
        token = self._token({"k": "m", "f": identity["folder"], "v": identity["uidvalidity"],
                             "u": identity["uid"], "h": identity["raw_sha256"],
                             "r": identity["rfc_message_id"], "g": identity["gmail_message_id"]})
        decoded = self._decode(token, "m")
        if identity["binding"] != self.binding:
            raise MailboxProviderError("imap_draft_identity_invalid", non_dispatch=True)
        return decoded

    @staticmethod
    def _matches(row: dict[str, Any], identity: dict[str, Any]) -> bool:
        actual = row["identity"]
        return all(actual[key] == identity[key] for key in ("binding", "raw_sha256", "rfc_message_id", "gmail_message_id"))

    def _trashed(self, identity: dict[str, Any]) -> list[dict[str, Any]]:
        decoded = self._snapshot(identity)
        if decoded["g"] and self.gmail_extensions:
            rows = self._inventory("Trash", "X-GM-MSGID", decoded["g"])
        elif decoded["r"]:
            rows = self._inventory("Trash", "HEADER", "Message-ID", _quote(decoded["r"]))
        else:
            # Do not turn an identity-free full-folder scan into attribution.
            raise MailboxProviderError("imap_trash_identity_unavailable")
        return [row for row in rows if self._matches(row, identity)]
