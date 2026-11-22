"""Send one prepared reply on a person's explicit instruction, then retire its review copy.

The exact send service owns transport, Sent verification and the operation
journal; this module adds what the person's instruction needs around it: the
source identity the request is bound to, two exact checks before a new send,
the replay of a stored operation on a retry, and the retirement of the Gmail
review copy after a verified send. Nothing here generates text.
"""

import asyncio
from datetime import datetime, timezone
from email import policy
from email.errors import HeaderParseError
from email.utils import parsedate_to_datetime

from zylch.storage.draft_operations import DraftOperations, OperationConflict

from . import person_request
from .exact_draft_delivery import EvidenceRefusal, snapshot
from .exact_draft_publication_mime import identifier, identifiers, matches
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


def request_for(owner, mailbox_id, draft):
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
    if row.get("mailbox_id") != mailbox_id:
        raise AssignmentError("person_request_source_mismatch")
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
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _sent_sender(value):
    if not value:
        return None
    try:
        header = policy.default.header_factory("From", value)
        if header.defects or len(header.addresses) != 1:
            return None
        address = header.addresses[0]
    except (HeaderParseError, IndexError, ValueError):
        return None
    return address.addr_spec.lower() if address.username and address.domain else None


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
        targets = identifiers(row["in_reply_to"])
        if not targets:
            raise EvidenceRefusal("incomplete_inventory")
        if targets != [target]:
            continue
        sender = _sent_sender(row["from"])
        when = _sent_date(row["date"])
        if sender is None or when is None or created is None or (sender == owner.lower() and when >= created):
            return "reply_already_sent", [
                {"folder": info["folder"], "uidvalidity": info["uidvalidity"], "uid": row["uid"], "date": row["date"]}
            ]
    return None


RETIREMENT_ATTEMPTS = 3


def retirement_ids(retirement_id):
    """The base retirement id, then the ids of the retries it may spawn."""
    from uuid import UUID, uuid5

    return [retirement_id, *(str(uuid5(UUID(retirement_id), f"retire:{n}")) for n in range(1, RETIREMENT_ATTEMPTS + 1))]


def retire(owner, uid, draft_id, root, retirement_id, recheck, mailbox_factory):
    """Move the exact review copy of a sent draft to Trash, with Sent proof.

    A retry reads the retirement's own journal first: an attempt that moved
    the copy and lost its acknowledgment is finished under the same id with
    its stored target, never reported as a missing copy; an attempt stranded
    before dispatch is closed and a new one starts, one per call.
    """
    from zylch.storage.storage import Storage

    from . import exact_draft_retirement as retirement

    draft = Storage.get_instance().get_draft(owner, draft_id)

    def pending(cause, **extra):
        return {
            "version": 1,
            "ok": False,
            "cause": cause,
            "state": "sent-with-cleanup-pending",
            "cleanup_certainty": "not-dispatched",
            "next_action": "retire-sent-mirror",
            **extra,
        }

    if draft is None:
        return pending("draft_not_found")
    try:
        if recheck() != (owner, uid):
            return pending("owner_profile_mismatch")
    except (AssignmentError, EvidenceRefusal) as error:
        return pending(str(error))
    store = DraftOperations()
    ids = retirement_ids(retirement_id)
    found = []
    for attempt in ids:
        entry = store.read(uid, attempt)
        if entry is None:
            break
        found.append((attempt, entry))
    attempt = ids[0]
    if found:
        attempt, latest = found[-1]
        if latest.get("operation_type") != "retire_sent_mirror":
            return pending("retirement_operation_conflict", operation_id=attempt)
        if latest["stage"] in {"completed", "dispatch_possible", "acknowledged"}:
            return retirement.retire(
                owner, uid, draft_id, latest["expected_snapshot"], latest["binding"]["root"], attempt,
                latest["binding"]["target"], True, recheck, mailbox_factory=mailbox_factory,
            )
        if latest["stage"] in {"reserved", "inventoried"} and latest["active"]:
            try:
                store.reconcile(uid, attempt, expected_version=latest["version"], stage="not_dispatched",
                                evidence={"cause": "recovered_before_dispatch"})
            except OperationConflict:
                return pending("retirement_in_progress", operation_id=attempt)
        index = ids.index(attempt)
        if index + 1 >= len(ids):
            return pending("retirement_attempts_exhausted", operation_id=attempt)
        attempt = ids[index + 1]
    try:
        mailbox = mailbox_factory(owner)
    except Exception as error:
        return pending(_inventory_cause(error))
    try:
        rows, inventory = mailbox.inventory()
    except Exception as error:
        return pending(_inventory_cause(error))
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
        owner, uid, draft_id, snapshot(draft), root, attempt, target, True, recheck,
        mailbox_factory=mailbox_factory,
    )


def _inventory_cause(error):
    """The named cause of a failed mailbox read; provider errors get one stable name."""
    if isinstance(error, EvidenceRefusal):
        return str(error)
    return "drafts_inventory_unavailable:provider_observation_unavailable"


def send(owner, uid, mailbox_id, draft_id, operation_id, retirement_id, recheck, *, mailbox_factory=None):
    """One send on a person's instruction; the same operation id never sends twice."""
    from zylch.storage.storage import Storage

    from . import exact_operator_send as exact
    from .exact_draft_retirement_imap import RetirementMailbox

    factory = mailbox_factory or RetirementMailbox
    draft = Storage.get_instance().get_draft(owner, draft_id)
    if draft is None:
        return _held(draft_id, operation_id, "draft_not_found")
    try:
        request = request_for(owner, mailbox_id, draft)
    except (AssignmentError, EvidenceRefusal) as error:
        return _held(draft_id, operation_id, str(error))
    def recheck_source():
        binding = recheck()
        if request_for(owner, mailbox_id, draft) != request:
            raise AssignmentError("person_request_source_mismatch")
        return binding

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
                try:
                    mailbox = factory(owner)
                except Exception as error:
                    return _held(draft_id, operation_id, _inventory_cause(error))
                try:
                    refusal = preflight(owner, uid, draft, bound["root"], bound["target"], mailbox)
                except Exception as error:
                    return _held(draft_id, operation_id, _inventory_cause(error))
                finally:
                    mailbox.close()
                if refusal is not None:
                    cause, handles = refusal
                    return _held(draft_id, operation_id, cause, provider_handles=handles)
            answer = asyncio.run(exact.send(owner, uid, draft_id, expected, operation_id, bound, recheck_source))
    except AssignmentError as error:
        return _held(draft_id, operation_id, str(error))
    if not answer.get("ok"):
        return {**answer, "cleanup": None}
    cleanup = retire(owner, uid, draft_id, bound["root"], retirement_id, recheck_source, factory)
    return {**answer, "cleanup": cleanup}
