"""Review copies of a person's prepared replies: publication, recovery, journal.

A prepared reply is on no surface a person uses until its review copy sits in
the mailbox's Drafts folder. The exact publication service writes that copy
once per thread root and journals the attempt under an operation id. This
module decides, from the journal, what one more call may do: publish a first
time, confirm an earlier copy, close an attempt a restart stranded before any
copy was written, or start one new attempt. It never generates text and
never sends.
"""

import threading
from uuid import UUID, uuid5

from zylch.storage.draft_operations import DraftOperations, OperationConflict

from .exact_draft_delivery import snapshot

ATTEMPTS = 5
_running = set()
_lock = threading.Lock()


def attempt_ids(operation_id):
    """The base operation id, then the ids of the retries it may spawn."""
    return [operation_id, *(str(uuid5(UUID(operation_id), f"publish:{n}")) for n in range(1, ATTEMPTS + 1))]


def _handle(row, inventory):
    return {
        "folder": inventory["folder"],
        "uidvalidity": inventory["uidvalidity"],
        "uid": row["uid"],
        "raw_fingerprint": row["raw_fingerprint"],
    }


def conflicts(owner, root, *, mailbox_factory=None):
    """Handles of the Drafts messages already on this root; one such copy stops a new reply."""
    from .exact_draft_publication_imap import ReviewMailbox

    mailbox = (mailbox_factory or ReviewMailbox)(owner)
    try:
        rows, inventory = mailbox.inventory()
    finally:
        mailbox.close()
    return [_handle(row, inventory) for row in rows if row["root"] == root]


def entries(uid, operation_id):
    """The journal entries of this operation's attempts, in attempt order."""
    store = DraftOperations()
    found = []
    for attempt in attempt_ids(operation_id):
        entry = store.read(uid, attempt)
        if entry is None:
            break
        found.append((attempt, entry))
    return found


def status(uid, operation_id):
    found = entries(uid, operation_id)
    if not found:
        return None
    attempt, entry = found[-1]
    return {"operation_id": attempt, "stage": entry["stage"], "active": entry["active"],
            "attempt": len(found), "handles": (entry.get("verification") or {}).get("handles", [])}


def _root(draft):
    refs = draft.get("references") or []
    return draft.get("thread_id") or (refs[0] if refs else draft.get("in_reply_to"))


def _outcome(draft, attempt, cause, *, uncertain=False, **extra):
    from .exact_draft_publication import outcome

    return outcome(draft["id"], attempt, _root(draft), snapshot(draft), reason=cause, uncertain=uncertain) | extra


def _run(owner, uid, draft, attempt, recheck, mailbox_factory):
    from . import exact_draft_publication as publication

    with _lock:
        _running.add(attempt)
    try:
        kwargs = {"mailbox_factory": mailbox_factory} if mailbox_factory is not None else {}
        return publication.publish(owner, uid, draft["id"], snapshot(draft), _root(draft), attempt, recheck, **kwargs)
    finally:
        with _lock:
            _running.discard(attempt)


def publish(owner, uid, draft, operation_id, recheck, *, mailbox_factory=None):
    """Publish or recover the review copy of one saved draft, one new attempt at most.

    The newest existing attempt decides: none, publish under the base id; a
    completed or dispatched entry, confirm or report under the same id, with
    no second append; an entry stranded before dispatch and not running in
    this process, close it and start the next attempt; a final failed
    attempt, start the next one; no attempt left, report exhaustion.
    """
    if draft.get("status") != "draft":
        return _outcome(draft, operation_id, "draft_not_pending", draft_status=draft.get("status"))
    ids = attempt_ids(operation_id)
    found = entries(uid, operation_id)
    if not found:
        return _run(owner, uid, draft, ids[0], recheck, mailbox_factory)
    attempt, latest = found[-1]
    stage = latest["stage"]
    if stage in {"completed", "dispatch_possible", "acknowledged"}:
        result = _run(owner, uid, draft, attempt, recheck, mailbox_factory)
        if result.get("cause") == "publication_outcome_unresolved":
            # A completed entry is inactive and blocks nothing; a dispatched
            # one stays active and blocks every exact effect on the thread.
            result = {**result, "blocking_thread": bool(latest["active"])}
        return result
    if stage in {"reserved", "inventoried"} and latest["active"]:
        with _lock:
            running = attempt in _running
        if running:
            return _outcome(draft, attempt, "publication_in_progress", uncertain=True)
        try:
            DraftOperations().reconcile(uid, attempt, expected_version=latest["version"],
                                        stage="not_dispatched", evidence={"cause": "recovered_before_dispatch"})
        except OperationConflict:
            return _outcome(draft, attempt, "publication_in_progress", uncertain=True)
    index = ids.index(attempt)
    if index + 1 >= len(ids):
        return _outcome(draft, attempt, "publication_attempts_exhausted")
    return _run(owner, uid, draft, ids[index + 1], recheck, mailbox_factory)
