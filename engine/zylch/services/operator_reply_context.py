import hashlib
import json
from datetime import datetime

from sqlalchemy import select

from .operator_reply_operations import ReplyRefusal


_FIELDS = ("id", "mailbox_id", "thread_id", "message_id_header", "references", "from_email", "to_email", "cc_email", "subject", "date", "body_plain", "body_html", "has_attachments", "attachment_filenames", "original_message_id", "pec_markers")


def snapshot(rows, actor, thread_key):
    from zylch.workers.thread_presenter import strip_quoted
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ReplyRefusal("bounded_thread_correspondence_required")
    frozen, seen = [], set()
    for row in rows:
        if (not isinstance(row, dict) or row.get("mailbox_id") != actor.mailbox_id
                or row.get("thread_id") != thread_key or not isinstance(row.get("id"), str)
                or not row["id"] or row["id"] in seen
                or row.get("original_message_id") or row.get("pec_markers")):
            raise ReplyRefusal("exact_ordinary_thread_correspondence_required")
        seen.add(row["id"])
        frozen.append({key: value.isoformat() if isinstance(value, datetime) else value
                       for key in _FIELDS for value in [row.get(key)]})
    frozen.sort(key=lambda row: (row.get("date") or "", row["id"]))
    raw = json.dumps(frozen, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(raw.encode()) > 196608:
        raise ReplyRefusal("generation_context_too_large")
    messages = [{key: row.get(key) for key in
                ("id", "mailbox_id", "from_email", "to_email", "cc_email", "subject", "date", "has_attachments", "attachment_filenames")}
                | {"body_plain": strip_quoted(row.get("body_plain") or "", cap=None)} for row in frozen]
    return {"coverage": "partial_synced_history", "emails": messages,
            "snapshot_hash": hashlib.sha256(raw.encode()).hexdigest()}


def read_locked(session, actor, thread_key):
    from zylch.storage.models import Email
    rows = session.execute(select(Email.__table__).where(
        Email.owner_id == actor.mailbox_address, Email.mailbox_id == actor.mailbox_id,
        Email.thread_id == thread_key).limit(101)).mappings().all()
    return snapshot([dict(row) for row in rows], actor, thread_key)


def check_locked(session, actor, source, expected):
    if expected is not None and read_locked(session, actor, source["thread_id"]) != expected:
        raise ReplyRefusal("correspondence_changed_before_private_commit")
