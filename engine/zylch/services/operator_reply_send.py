"""Send one prepared reply on a person's explicit instruction, then retire its review copy.

The exact send service owns transport, Sent verification and the operation
journal; this module adds what the person's instruction needs around it: the
source identity the request is bound to, two exact checks before a new send,
the replay of a stored operation on a retry, and the retirement of the Gmail
review copy after a verified send. Nothing here generates text.
"""

import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from zylch.storage.draft_operations import DraftOperations

from . import person_request
from .exact_draft_delivery import EvidenceRefusal, addresses, snapshot
from .exact_draft_publication_mime import identifier, matches
from .exact_draft_retirement_evidence import handle, related
from .task_assignment_types import AssignmentError

SENT_SEARCH_LIMIT = 200


def _held(draft_id, operation_id, cause, **extra):
    return {
        "version": 1,
        "ok": False,
        "draft_id": draft_id,
        "operation_id": operation_id,
        "state": "send-held",
        "effect_certainty": "not-dispatched",
        "cleanup_certainty": "not-dispatched",
        "achieved_stages": ["engine-saved"],
        "cause": cause,
        "next_action": "inspect-draft",
        "audit_reason": "explicit_operator_request",
        **extra,
    }


def request_for(owner, draft):
    """The person's source: the one stored ordinary row the draft replies to."""
    from sqlalchemy import select

    from zylch.storage import database as db
    from zylch.storage.models import Email

    target = identifier(draft.get("in_reply_to") or "")
    with db.get_engine().connect() as conn:
        rows = list(
            conn.execute(
                select(Email.__table__)
                .where(Email.owner_id == owner, Email.message_id_header == target)
                .limit(2)
            ).mappings()
        )
    if len(rows) != 1:
        raise AssignmentError("exact_source_required")
    row = dict(rows[0])
    if draft.get("thread_id") not in (None, row.get("thread_id")):
        raise AssignmentError("exact_source_required")
    return person_request.from_row(owner, row)


def _created(draft):
    value = draft.get("created_at")
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _sent_date(value):
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def preflight(owner, uid, draft, root, target, mailbox):
    """The two exact checks before a new send; None when the send may proceed.

    A review copy on the root that is not this draft exactly means two texts
    exist. A message from the mailbox in Sent that replies to the same source
    and is dated at or after the draft's creation means the reply already
    left from Gmail; a matching message whose From or Date cannot be read
    counts the same way.
    """
    rows, inventory = mailbox.inventory()
    for row in related(rows, draft, root):
        if not matches(row, draft, owner, uid, require_draft=False):
            return "review_copy_differs_from_draft", [handle(row, inventory)]
    created = _created(draft)
    sent, info = mailbox.headers("Sent", "In-Reply-To", target, limit=SENT_SEARCH_LIMIT)
    for row in sent:
        sender = addresses([row["from"]]) if row["from"] else []
        if sender and sender != [owner.lower()]:
            continue
        when = _sent_date(row["date"])
        if not sender or when is None or created is None or when >= created:
            return "reply_already_sent", [
                {"folder": info["folder"], "uidvalidity": info["uidvalidity"], "uid": row["uid"], "date": row["date"]}
            ]
    return None


def retire(owner, uid, draft_id, root, retirement_id, recheck, mailbox_factory):
    """Move the exact review copy of a sent draft to Trash, with Sent proof."""
    from zylch.storage.storage import Storage

    from . import exact_draft_retirement as retirement

    draft = Storage.get_instance().get_draft(owner, draft_id)

    def pending(cause):
        return {
            "version": 1,
            "ok": False,
            "cause": cause,
            "state": "sent-with-cleanup-pending",
            "cleanup_certainty": "not-dispatched",
            "next_action": "retire-sent-mirror",
        }

    if draft is None:
        return pending("draft_not_found")
    mailbox = mailbox_factory(owner)
    try:
        rows, inventory = mailbox.inventory()
    except EvidenceRefusal as error:
        return pending(str(error))
    finally:
        mailbox.close()
    copies = related(rows, draft, root)
    if not copies:
        return {
            "version": 1,
            "ok": True,
            "cause": "no_review_copy",
            "state": "sent",
            "cleanup_certainty": "verified",
            "next_action": "resume-existing-draft",
        }
    if len(copies) != 1:
        return pending("residual_copy_conflict")
    target = handle(copies[0], inventory)
    return retirement.retire(
        owner, uid, draft_id, snapshot(draft), root, retirement_id, target, True, recheck,
        mailbox_factory=mailbox_factory,
    )


def send(owner, uid, draft_id, operation_id, retirement_id, recheck, *, mailbox_factory=None):
    """One send on a person's instruction; the same operation id never sends twice."""
    from zylch.storage.storage import Storage

    from . import exact_operator_send as exact
    from .exact_draft_retirement_imap import RetirementMailbox

    factory = mailbox_factory or RetirementMailbox
    draft = Storage.get_instance().get_draft(owner, draft_id)
    if draft is None:
        return _held(draft_id, operation_id, "draft_not_found")
    try:
        request = request_for(owner, draft)
    except (AssignmentError, EvidenceRefusal) as error:
        return _held(draft_id, operation_id, str(error))
    try:
        with person_request.scope(request):
            try:
                selected = exact.inspect(owner, uid, draft_id)
            except (EvidenceRefusal, AssignmentError) as error:
                return _held(draft_id, operation_id, str(error))
            previous = DraftOperations().read(uid, operation_id)
            if previous is not None:
                expected = previous["expected_snapshot"]
                bound = {key: value for key, value in previous["binding"].items() if key != "transport"}
            else:
                expected, bound = selected["expected_snapshot"], selected["binding"]
                mailbox = factory(owner)
                try:
                    refusal = preflight(owner, uid, draft, bound["root"], bound["target"], mailbox)
                except EvidenceRefusal as error:
                    return _held(draft_id, operation_id, str(error))
                finally:
                    mailbox.close()
                if refusal is not None:
                    cause, handles = refusal
                    return _held(draft_id, operation_id, cause, provider_handles=handles)
            answer = asyncio.run(exact.send(owner, uid, draft_id, expected, operation_id, bound, recheck))
    except AssignmentError as error:
        return _held(draft_id, operation_id, str(error))
    if not answer.get("ok"):
        return {**answer, "cleanup": None}
    cleanup = retire(owner, uid, draft_id, bound["root"], retirement_id, recheck, factory)
    return {**answer, "cleanup": cleanup}
