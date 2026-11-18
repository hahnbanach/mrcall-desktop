"""Complete primary-mailbox Drafts inventory and one explicit APPEND."""

import hashlib
import json
import re
from typing import Any

from .exact_draft_delivery import EvidenceRefusal
from .exact_draft_publication_mime import observation


class ReviewMailbox:
    def __init__(self, owner: str) -> None:
        from zylch.email import mailboxes

        mailbox = mailboxes.primary(owner)
        if mailbox is None or mailbox.address.lower() != owner.lower():
            raise EvidenceRefusal("mailbox_unavailable")
        self.client = mailboxes.build_imap_client(mailbox)
        self.conn = self.client._ensure_connected()
        self.folder = None

    def close(self) -> None:
        self.client.disconnect()

    def inventory(
        self,
        special_use: str = "Drafts",
        *,
        search_header: str | None = None,
        search_value: str | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        status, folders = self.conn.list()
        if status != "OK" or not isinstance(folders, list):
            raise EvidenceRefusal("drafts_folder_unavailable")
        candidates = []
        for folder in folders:
            match = re.fullmatch(rb'\(([^)]*)\) (?:"[^"]*"|NIL) (.+)', folder or b"")
            if match and ("\\" + special_use.lower()).encode("ascii") in match[1].lower().split():
                candidates.append(match[2].decode("ascii"))
        if len(candidates) != 1:
            raise EvidenceRefusal("drafts_folder_unavailable")
        self.folder = candidates[0]
        if self.conn.select(self.folder, readonly=True)[0] != "OK":
            raise EvidenceRefusal("drafts_folder_unavailable")
        values = self.conn.untagged_responses.get("UIDVALIDITY", [])
        if len(values) != 1 or not values[0].isdigit():
            raise EvidenceRefusal("uidvalidity_unavailable")
        validity = values[0].decode("ascii")
        search = ("ALL",)
        if search_header is not None:
            if (
                search_header not in {"Message-ID", "X-CS-Engine-Draft-ID"}
                or not search_value
                or any(c in search_value for c in "\r\n")
            ):
                raise EvidenceRefusal("invalid_inventory_query")
            quoted = '"' + search_value.replace("\\", "\\\\").replace('"', '\\"') + '"'
            search = ("HEADER", search_header, quoted)
        status, data = self.conn.uid("SEARCH", None, *search)
        if (
            status != "OK"
            or not isinstance(data, list)
            or len(data) != 1
            or not isinstance(data[0], bytes)
        ):
            raise EvidenceRefusal("incomplete_inventory")
        uids = data[0].split()
        if (
            len(uids) > 1000
            or len(set(uids)) != len(uids)
            or any(not uid.isdigit() for uid in uids)
        ):
            raise EvidenceRefusal("incomplete_inventory")
        rows = []
        total_bytes = 0
        for uid in uids:
            status, parts = self.conn.uid("FETCH", uid, "(UID FLAGS RFC822.SIZE BODY.PEEK[])")
            payloads = [part for part in parts or [] if isinstance(part, tuple)]
            if status != "OK" or len(payloads) != 1:
                raise EvidenceRefusal("incomplete_inventory")
            meta, raw = payloads[0]
            actual = re.search(rb"\bUID (\d+)\b", meta)
            size = re.search(rb"\bRFC822.SIZE (\d+)\b", meta)
            flags = re.search(rb"\bFLAGS \(([^)]*)\)", meta)
            if (
                not actual
                or actual[1] != uid
                or not size
                or not flags
                or not isinstance(raw, bytes)
                or len(raw) != int(size[1])
                or len(raw) > 2097152
            ):
                raise EvidenceRefusal("incomplete_inventory")
            total_bytes += len(raw)
            if total_bytes > 8388608:
                raise EvidenceRefusal("inventory_byte_limit")
            rows.append(observation(raw, uid.decode(), flags[1].decode("ascii").split()))
        status, final = self.conn.uid("SEARCH", None, *search)
        if status != "OK" or final != data:
            raise EvidenceRefusal("inventory_changed")
        digest = hashlib.sha256(
            json.dumps([(r["uid"], r["raw_fingerprint"], r["flags"]) for r in rows]).encode()
        ).hexdigest()
        return rows, {
            "complete": True,
            "search": list(search),
            "folder": self.folder,
            "uidvalidity": validity,
            "digest": digest,
        }

    def append(self, raw: bytes) -> dict[str, Any]:
        status, _data = self.conn.append(self.folder, "(\\Draft)", None, raw)
        if status != "OK":
            raise EvidenceRefusal("append_unconfirmed")
        return {"acknowledged": True}
