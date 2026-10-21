"""Independent read-only Sent evidence and full-row snapshot identity.

Only explicit reconciliation uses this verifier; automatic reconciliation is
intentionally unavailable until real provider header preservation is proven.
"""

from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
import hashlib
import json
import logging
import os
import re
from html.parser import HTMLParser
from typing import Any

logger = logging.getLogger(__name__)


class EvidenceRefusal(ValueError):
    def __init__(self, reason: str) -> None:
        logger.debug("[exact-draft-evidence] refused reason=%s", reason)
        super().__init__(reason)


def snapshot(draft: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(draft, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def addresses(values: list[str] | str | None) -> list[str]:
    if not isinstance(values, list):
        values = [values or ""]
    return sorted(address.lower() for _, address in getaddresses(values) if address)


def message_ids(value: str | None) -> list[str]:
    return re.findall(r"<[^<>\s]+>", value or "")


def one(message: EmailMessage, name: str) -> str:
    values = message.get_all(name, [])
    if len(values) != 1:
        raise EvidenceRefusal("invalid_sent_headers")
    return str(values[0]).strip()


def simple_html_text(value: str) -> str:
    """Conservative alternative equivalence; rich/hidden/link markup refuses."""

    class Parser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if attrs or tag not in {
                "html",
                "body",
                "p",
                "div",
                "span",
                "br",
                "b",
                "strong",
                "i",
                "em",
                "u",
                "ul",
                "ol",
                "li",
            }:
                raise EvidenceRefusal("ambiguous_body")
            if tag in {"p", "div", "br", "li"}:
                self.parts.append("\n")

        def handle_endtag(self, tag: str) -> None:
            if tag not in {
                "html",
                "body",
                "p",
                "div",
                "span",
                "br",
                "b",
                "strong",
                "i",
                "em",
                "u",
                "ul",
                "ol",
                "li",
            }:
                raise EvidenceRefusal("ambiguous_body")
            if tag in {"p", "div", "li"}:
                self.parts.append("\n")

        def handle_data(self, text: str) -> None:
            self.parts.append(text)

    parser = Parser()
    parser.feed(value)
    parser.close()
    return " ".join("".join(parser.parts).split())


def verify_message(
    raw: bytes, draft: dict[str, Any], sent_message_id: str, owner_uid: str, mailbox_address: str
) -> datetime:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    if one(message, "Message-ID") != sent_message_id:
        raise EvidenceRefusal("message_id_mismatch")
    if (
        one(message, "X-CS-Engine-Draft-ID") != draft["id"]
        or one(message, "X-CS-Engine-Owner-UID") != owner_uid
    ):
        raise EvidenceRefusal("mirror_identity_mismatch")
    if addresses([one(message, "From")]) != [mailbox_address.lower()]:
        raise EvidenceRefusal("sender_mismatch")
    for header, field in (("To", "to_addresses"), ("Cc", "cc_addresses"), ("Bcc", "bcc_addresses")):
        if addresses([str(value) for value in message.get_all(header, [])]) != addresses(
            draft.get(field)
        ):
            raise EvidenceRefusal("recipients_mismatch")
    # Gmail can fold an unstructured Subject immediately after its colon,
    # leaving leading folding whitespace in the parsed value.
    if one(message, "Subject") != (draft.get("subject") or "").strip():
        raise EvidenceRefusal("subject_mismatch")
    for header, field in (("In-Reply-To", "in_reply_to"), ("References", "references")):
        expected = draft.get(field) or ""
        if isinstance(expected, list):
            expected = " ".join(expected)
        if message_ids(" ".join(str(x) for x in message.get_all(header, []))) != message_ids(
            expected
        ):
            raise EvidenceRefusal("thread_mismatch")
    # Do not silently bless attachments not represented in the evidence contract.
    if draft.get("attachment_paths") or list(message.iter_attachments()):
        raise EvidenceRefusal("attachments_unverified")
    subtype = "html" if draft.get("body_format") == "html" else "plain"
    part = message.get_body(preferencelist=(subtype,))
    if part is None or part.get_content_type() != "text/" + subtype:
        raise EvidenceRefusal("body_mismatch")

    def normalize(text: str) -> str:
        return text.replace("\r\n", "\n").rstrip("\n")

    if normalize(part.get_content()) != normalize(draft.get("body") or ""):
        raise EvidenceRefusal("body_mismatch")
    # A provider may emit multipart/alternative. Every material body must
    # agree; selecting one matching subtype can hide an edited other version.
    bodies = [value for value in message.walk() if not value.is_multipart()]
    if any(value.get_content_type() not in {"text/plain", "text/html"} for value in bodies):
        raise EvidenceRefusal("ambiguous_body")
    if len(bodies) > 1:
        if len(bodies) != 2 or {value.get_content_type() for value in bodies} != {
            "text/plain",
            "text/html",
        }:
            raise EvidenceRefusal("ambiguous_body")
        plain = next(
            value.get_content() for value in bodies if value.get_content_type() == "text/plain"
        )
        html = next(
            value.get_content() for value in bodies if value.get_content_type() == "text/html"
        )
        if " ".join(plain.split()) != simple_html_text(html):
            raise EvidenceRefusal("ambiguous_body")
    try:
        date = parsedate_to_datetime(one(message, "Date"))
        if date.tzinfo is None:
            raise ValueError()
    except (ValueError, TypeError, OverflowError):
        raise EvidenceRefusal("sent_date_unavailable") from None
    logger.debug("[exact-draft-evidence] complete message verification succeeded")
    return date.astimezone(timezone.utc).replace(tzinfo=None)


def verify_sent(owner: str, draft: dict[str, Any], sent_message_id: str) -> datetime:
    from zylch.email import mailboxes

    logger.debug("[exact-draft-evidence] independent Sent verification started")
    if not isinstance(sent_message_id, str) or not re.fullmatch(r"<[^<>\s\"\\]+>", sent_message_id):
        raise EvidenceRefusal("invalid_message_id")
    uid = os.environ.get("OWNER_ID", "")
    if not uid:
        raise EvidenceRefusal("owner_uid_unavailable")
    mailbox = mailboxes.primary(owner)
    if mailbox is None or mailbox.address.lower() != owner.lower():
        raise EvidenceRefusal("mailbox_unavailable")
    client = mailboxes.build_imap_client(mailbox)
    try:
        conn = client._ensure_connected()
        folder = client._find_sent_folder()
        if not folder or conn.select(folder, readonly=True)[0] != "OK":
            raise EvidenceRefusal("sent_folder_unavailable")
        status, result = conn.uid(
            "SEARCH", None, "HEADER", "Message-ID", '"' + sent_message_id + '"'
        )
        if status != "OK":
            raise EvidenceRefusal("sent_search_failed")
        candidates = result[0].split() if result and isinstance(result[0], bytes) else []
        if len(candidates) > 50:
            raise EvidenceRefusal("ambiguous_sent_evidence")
        logger.debug("[exact-draft-evidence] Sent search candidate_count=%d", len(candidates))
        matches: list[bytes] = []
        for candidate in candidates:
            status, parts = conn.uid("FETCH", candidate, "(BODY.PEEK[])")
            if status != "OK":
                raise EvidenceRefusal("sent_fetch_failed")
            payloads = [
                part[1] for part in parts if isinstance(part, tuple) and isinstance(part[1], bytes)
            ]
            if len(payloads) != 1:
                raise EvidenceRefusal("sent_fetch_failed")
            raw = payloads[0]
            message = BytesParser(policy=policy.default).parsebytes(raw)
            if message.get_all("Message-ID", []) == [sent_message_id]:
                matches.append(raw)
        if len(matches) != 1:
            raise EvidenceRefusal(
                "ambiguous_sent_evidence" if matches else "sent_message_not_found"
            )
        return verify_message(matches[0], draft, sent_message_id, uid, mailbox.address)
    finally:
        client.disconnect()
