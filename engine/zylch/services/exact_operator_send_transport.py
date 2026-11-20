"""Canonical identity of the ordinary prepared plain-text transport message."""

import hashlib
import json
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

from .exact_draft_delivery import addresses, one
from .exact_draft_publication_mime import identifier, identifiers, observation


def digest(message):
    message = BytesParser(policy=policy.default).parsebytes(message.as_bytes())
    observation(message.as_bytes(), "prepared", [])
    value = {
        "message_id": identifier(one(message, "Message-ID")),
        "date": parsedate_to_datetime(one(message, "Date")).isoformat(),
        "from": addresses(one(message, "From")),
        "to": addresses(one(message, "To")),
        "cc": addresses(str(message.get("Cc") or "")),
        "bcc": addresses(str(message.get("Bcc") or "")),
        "subject": one(message, "Subject"),
        "target": identifier(one(message, "In-Reply-To")),
        "references": identifiers(one(message, "References")),
        "content_type": message.get_content_type(),
        "charset": message.get_content_charset(),
        "disposition": message.get_content_disposition(),
        "filename": message.get_filename(),
        "body": message.get_content().replace("\r\n", "\n"),
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def prepare(client, draft):
    message, recipients = client.prepare_message(
        to=", ".join(draft["to_addresses"]),
        subject=draft.get("subject") or "",
        body=draft["body"],
        cc=draft.get("cc_addresses"),
        bcc=draft.get("bcc_addresses"),
        in_reply_to=draft.get("in_reply_to"),
        references=" ".join(draft.get("references") or []),
        attachment_paths=draft.get("attachment_paths"),
    )
    return {
        "message_id": str(message["Message-ID"]),
        "date": str(message["Date"]),
        "mime_digest": digest(message),
        "recipients": sorted(recipients),
    }
