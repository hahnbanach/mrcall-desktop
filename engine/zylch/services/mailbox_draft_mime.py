"""Mailbox draft handles and lossless MIME presentation for the mail clients."""

import hashlib
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, getaddresses, make_msgid


class MailboxDraftError(ValueError):
    def __init__(self, cause, **details):
        super().__init__(cause)
        self.cause, self.details = cause, details


def handle(owner, native_id):
    if not isinstance(native_id, str) or not native_id or ":" in native_id:
        raise MailboxDraftError("invalid_native_draft_id")
    return "gmail:" + hashlib.sha256(owner.lower().encode()).hexdigest() + ":" + native_id


def native_id(owner, draft_id):
    prefix = "gmail:" + hashlib.sha256(owner.lower().encode()).hexdigest() + ":"
    if not isinstance(draft_id, str) or not draft_id.startswith(prefix):
        raise MailboxDraftError("draft_mailbox_mismatch", draft_id=draft_id)
    result = draft_id.removeprefix(prefix)
    if not result or ":" in result or any(c.isspace() for c in result):
        raise MailboxDraftError("invalid_native_draft_id")
    return result


def addresses(value):
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)) or any(not isinstance(v, str) for v in value):
        raise MailboxDraftError("invalid_recipients")
    if any("\r" in v or "\n" in v for v in value):
        raise MailboxDraftError("invalid_recipients")
    result = [addr for _, addr in getaddresses(value)]
    if any(not addr or "@" not in addr for addr in result):
        raise MailboxDraftError("invalid_recipients")
    return result


def references(value):
    from .task_assignment_mail import references as parsed
    return parsed(" ".join(value) if isinstance(value, (list, tuple)) else value or "")


def parse(raw):
    if not isinstance(raw, bytes):
        raise MailboxDraftError("mailbox_mime_unavailable")
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    if msg.defects or any(part.defects for part in msg.walk()):
        raise MailboxDraftError("malformed_mailbox_mime")
    return msg


def attachments(msg):
    return [
        {"name": part.get_filename() or "", "content_type": part.get_content_type()}
        for part in msg.walk()
        if not part.is_multipart() and (
            part.get_filename() is not None or part.get_content_disposition() == "attachment"
            or part.get_content_type() not in {"text/plain", "text/html"}
        )
    ]


def row(owner, draft, *, provenance=None):
    msg = parse(draft["raw"])
    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part is None and not msg.is_multipart() and msg.get_content_type() in {"text/plain", "text/html"}:
        body_part = msg
    body = body_part.get_content() if body_part is not None else ""
    refs = references(str(msg.get("References") or ""))
    target = str(msg.get("In-Reply-To") or "").strip() or None
    root = refs[0] if refs else target
    identifier = handle(owner, draft["id"])
    result = {
        "id": identifier, "owner_id": owner, "mailbox_id": owner,
        "status": "draft", "subject": str(msg.get("Subject") or ""),
        "body": body, "body_format": "html" if body_part is not None and
        body_part.get_content_type() == "text/html" else "plain",
        "in_reply_to": target, "references": refs, "thread_id": root,
        "created_at": str(msg.get("Date") or ""), "updated_at": None,
        "attachments": attachments(msg),
        "body_editable": not msg.is_multipart() and msg.get_content_type() == "text/plain",
        "provider": "gmail", "provider_draft_id": draft["id"],
        "provider_message_id": draft["message_id"],
        "provider_thread_id": draft["thread_id"],
        "message_id_header": str(msg.get("Message-ID") or ""),
    }
    for header in ("To", "Cc", "Bcc"):
        values = addresses([str(v) for v in msg.get_all(header, [])])
        result[header.lower()] = result[header.lower() + "_addresses"] = values
    if provenance:
        result["operation_id"] = provenance["id"]
        result["source_id"] = provenance["source"]
    return result


def build(owner, *, to, subject, body, cc=None, bcc=None, in_reply_to=None,
          references=None, body_format="plain", message_id=None, **_):
    msg = EmailMessage(policy=policy.SMTP)
    msg["From"] = owner
    for header, values in (("To", to), ("Cc", cc), ("Bcc", bcc)):
        clean = addresses(values)
        if clean:
            msg[header] = ", ".join(clean)
    msg["Subject"] = subject or ""
    msg["Date"] = formatdate(localtime=False, usegmt=True)
    msg["Message-ID"] = message_id or make_msgid(domain=owner.split("@")[-1])
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = " ".join(globals()["references"](references))
    if body_format not in {"plain", "html"} or not isinstance(body, str):
        raise MailboxDraftError("unsupported_draft_body")
    msg.set_content(body, subtype=body_format)
    return msg.as_bytes()


def sending_raw(owner, raw, message_id):
    msg = parse(raw)
    if attachments(msg):
        raise MailboxDraftError("draft_attachments_not_supported")
    if [address.lower() for address in addresses(str(msg.get("From") or ""))] != [owner.lower()]:
        raise MailboxDraftError("draft_sender_mismatch")
    if not any(addresses(str(msg.get(key) or "")) for key in ("To", "Cc", "Bcc")):
        raise MailboxDraftError("draft_recipients_required")
    for field, value in (("Message-ID", message_id), ("Date", formatdate(usegmt=True))):
        while field in msg:
            del msg[field]
        msg[field] = value
    return msg.as_bytes(policy=policy.SMTP)


def update_raw(raw, fields):
    """Patch only requested fields; omitted MIME alternatives stay intact."""
    msg = parse(raw)
    if attachments(msg):
        raise MailboxDraftError("draft_attachments_not_supported")
    for name in ("To", "Cc", "Bcc", "Subject"):
        key = name.lower()
        if key not in fields:
            continue
        while name in msg:
            del msg[name]
        value = fields[key] if key == "subject" else ", ".join(addresses(fields[key]))
        if value:
            msg[name] = value
    if "body" in fields or "body_format" in fields:
        if msg.is_multipart():
            raise MailboxDraftError("rich_draft_body_edit_in_gmail")
        body = fields.get("body", msg.get_content())
        subtype = fields.get("body_format", "html" if msg.get_content_type() == "text/html" else "plain")
        if subtype not in {"plain", "html"} or not isinstance(body, str):
            raise MailboxDraftError("unsupported_draft_body")
        msg.set_content(body, subtype=subtype)
    return msg.as_bytes(policy=policy.SMTP)
