"""Deterministic review MIME and conservative full-message identity checks."""

from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
import hashlib
import re
from typing import Any
from uuid import UUID

from .exact_draft_delivery import EvidenceRefusal, addresses, one


def identifier(value: str) -> str:
    unfolded = re.sub(r"\r?\n[ \t]+", " ", str(value)).strip()
    if not re.fullmatch(r"<[^<>\s]+>", unfolded):
        raise EvidenceRefusal("invalid_thread_identifier")
    if policy.default.header_factory("Message-ID", unfolded).defects:
        raise EvidenceRefusal("invalid_thread_identifier")
    return unfolded


def identifiers(value: str) -> list[str]:
    return [identifier(part) for part in str(value).split()]


def validate(owner: str, uid: str, draft: dict[str, Any], root: str) -> dict[str, Any]:
    root = identifier(root)
    target = identifier(draft.get("in_reply_to") or "")
    refs = draft.get("references") or [target]
    if not isinstance(refs, list) or not refs:
        raise EvidenceRefusal("invalid_thread_identifier")
    refs = [identifier(value) for value in refs]
    if (
        str(UUID(draft["id"])) != draft["id"]
        or draft.get("owner_id") != owner
        or draft.get("status") != "draft"
        or not uid
        or refs[0] != root
        or draft.get("thread_id") not in (None, root)
    ):
        raise EvidenceRefusal("draft_binding_mismatch")
    if (
        not draft.get("body")
        or not addresses(draft.get("to_addresses"))
        or draft.get("attachment_paths")
        or draft.get("bcc_addresses")
        or draft.get("body_format") not in (None, "plain", "markdown", "html")
        or (draft.get("body_format") == "html" and re.search(r"<[A-Za-z!/][^>]*>", draft["body"]))
    ):
        raise EvidenceRefusal("unsupported_draft_content")
    binding = draft.get("reply_binding")
    if binding is not None and (binding.get("root") != root or binding.get("target") != target):
        raise EvidenceRefusal("draft_binding_mismatch")
    return {
        "root": root,
        "target": target,
        "references": refs,
        "source": binding.get("source") if binding else None,
        "recipients": addresses(draft["to_addresses"]),
        "cc": addresses(draft.get("cc_addresses")),
    }


def render(owner: str, uid: str, draft: dict[str, Any], operation_id: str) -> bytes:
    message = EmailMessage(policy=policy.SMTP)
    message["From"] = owner
    message["To"] = ", ".join(draft["to_addresses"])
    if draft.get("cc_addresses"):
        message["Cc"] = ", ".join(draft["cc_addresses"])
    message["Subject"] = draft.get("subject") or ""
    message["In-Reply-To"] = identifier(draft["in_reply_to"])
    message["References"] = " ".join(draft.get("references") or [draft["in_reply_to"]])
    message["X-CS-Engine-Draft-ID"] = draft["id"]
    message["X-CS-Engine-Owner-UID"] = uid
    message["X-CS-Draft-Operation-ID"] = operation_id
    message.set_content(draft["body"], cte="quoted-printable")
    return message.as_bytes()


def observation(raw: bytes, uid: str, flags: list[str]) -> dict[str, Any]:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    if message.defects or any(part.defects for part in message.walk()):
        raise EvidenceRefusal("incomplete_inventory")
    for name in (
        "Message-ID",
        "Date",
        "From",
        "To",
        "Cc",
        "Bcc",
        "Subject",
        "In-Reply-To",
        "References",
        "X-CS-Engine-Draft-ID",
        "X-CS-Engine-Owner-UID",
        "X-CS-Draft-Operation-ID",
        "Content-Type",
        "Content-Disposition",
        "Content-Transfer-Encoding",
        "MIME-Version",
    ):
        values = message.get_all(name, [])
        if len(values) > 1 or any(getattr(value, "defects", ()) for value in values):
            raise EvidenceRefusal("ambiguous_inventory_headers")
    target = identifier(message["In-Reply-To"]) if message.get("In-Reply-To") else None
    refs = identifiers(message["References"]) if message.get("References") else []
    return {
        "uid": uid,
        "raw_fingerprint": hashlib.sha256(raw).hexdigest(),
        "root": refs[0] if refs else target,
        "flags": flags,
        "message": message,
    }


def matches(
    row: dict[str, Any],
    draft: dict[str, Any],
    owner: str,
    uid: str,
    operation_id: str | None = None,
    *,
    require_draft: bool = True,
    require_identity: bool = True,
) -> bool:
    message = row["message"]
    try:
        if (
            message.is_multipart()
            or message.get_filename() is not None
            or any(
                part.defects or any(getattr(value, "defects", ()) for value in part.values())
                for part in message.walk()
            )
            or any(
                len(message.get_all(name, [])) > 1
                for name in (
                    "Content-Type",
                    "Content-Disposition",
                    "Content-Transfer-Encoding",
                    "MIME-Version",
                )
            )
            or message.get_content_type() != "text/plain"
            or message.get_content_disposition() is not None
            or (require_draft and "\\Draft" not in row["flags"])
            or (
                require_identity
                and (
                    one(message, "X-CS-Engine-Draft-ID") != draft["id"]
                    or one(message, "X-CS-Engine-Owner-UID") != uid
                )
            )
            or addresses(one(message, "From")) != [owner.lower()]
            or one(message, "Subject") != (draft.get("subject") or "").strip()
            or identifier(one(message, "In-Reply-To")) != identifier(draft["in_reply_to"])
            or identifiers(one(message, "References"))
            != (draft.get("references") or [draft["in_reply_to"]])
        ):
            return False
        for name, field in (
            ("To", "to_addresses"),
            ("Cc", "cc_addresses"),
            ("Bcc", "bcc_addresses"),
        ):
            if addresses(str(message.get(name) or "")) != addresses(draft.get(field)):
                return False
        if operation_id is not None and one(message, "X-CS-Draft-Operation-ID") != operation_id:
            return False

        def normalize(text: str) -> str:
            return text.replace("\r\n", "\n").rstrip("\n")

        return normalize(message.get_content()) == normalize(draft["body"])
    except (EvidenceRefusal, ValueError, TypeError, LookupError):
        return False
