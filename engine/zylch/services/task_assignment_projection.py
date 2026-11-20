"""Visible task ownership with exact inbound coverage and explicit uncertainty."""

import logging
import os
import time
from zylch.email import provider_diagnostics

from . import task_assignment_evidence as evidence
from . import task_assignment_identity as identity
from . import task_assignment_mail as mail
from . import task_assignment_store as store
from . import task_assignment_sent_index as sent_index
from . import task_assignment_trust as trust
from .task_assignment_types import AssignmentError, identifier, thread

logger = logging.getLogger(__name__)


def message_ids(identities: list[str]) -> list[str]:
    return sorted({value[65:] for value in identities if len(value) > 65 and value[64] == ":"})


def _diagnostic(command: str, status: str, root: str, started: float, *, error=None, stage="authority", **metadata) -> None:
    try:
        from zylch.observability_producers import failure, observe

        recorder = provider_diagnostics.current()
        if recorder is not None:
            recorder.flush()
            if recorder.first_fault is not None and (status == "failed" or command == "assignment.projection.terminal"):
                metadata["provider_diagnostic"] = dict(recorder.first_fault)
        facts = {"command": command, "method": "tasks.assignment.project", "root_id": root,
                 "elapsed_ms": max(0, (time.monotonic() - started) * 1000), **metadata}
        if error is not None:
            failure(stage, error, **facts)
        else:
            observe(stage, status, reason="incomplete-input" if status == "failed" else
                    "policy-hold" if status == "held" else "none", **facts)
    except Exception:
        pass


def _diagnostic_result(command: str, root: str, started: float, value: dict, *, stage="authority") -> None:
    status = "failed" if value.get("state") == "unknown" else "held" if value.get("hold_auto_reply") else "result"
    _diagnostic(command, status, root, started, stage=stage, complete=value.get("complete"))


def _read_deadline(started):
    return started + 120


@provider_diagnostics.projection
def project(root: str) -> dict:
    started = time.monotonic()
    deadline = _read_deadline(started)
    value = None
    _diagnostic("assignment.projection.start", "start", root, started, deadline_seconds=max(0, int(round(deadline - started))))
    try:
        with evidence.observation(root, deadline):
            value = _project(root, deadline)
    except Exception as error:
        _diagnostic("assignment.projection.failed" if value is None else "assignment.cleanup.failed",
                    "failed", root, started, error=error)
        if value is None:
            raise
        value.update(
            complete=False, state="unknown", hold_auto_reply=True, reason="SOURCE_UNAVAILABLE"
        )
    _diagnostic_result("assignment.projection.terminal", root, started, value)
    return value

def _early_source_sent(actor, current, observed, root, deadline):
    source = observed["source"]
    provider = source["provider"]
    box = next((box for box in mail.configured(actor, current) if box.id == source["mailbox_id"]), None)
    if box is None:
        raise AssignmentError("Early reply mailbox unavailable")
    with evidence.provider_client(actor, box, root, deadline) as client:
        with client._folder_header_read(provider["folder"], deadline=deadline,
                uids=[provider["uid"]], max_messages=None) as (state, read_selected):
            if state.uidvalidity != provider["uidvalidity"]:
                raise AssignmentError("Early reply source identity changed")
            headers, state = read_selected()
            header = headers.get(provider["uid"])
            if (header is None or header["message_id"] != source["message_id"]
                    or state.uidvalidity != provider["uidvalidity"]):
                raise AssignmentError("Early reply source identity changed")
            return not {"\\Draft", "\\Deleted"}.intersection(header["flags"])


class _EarlyReplies(list):
    def __init__(self, values, force_full_scan):
        super().__init__(values)
        self.force_full_scan = force_full_scan


def _early_replies(actor, current, known, root, deadline):
    own = set(current["members"][actor.uid])
    candidates, mids = {}, set()
    try:
        for row in known:
            senders = mail.addresses(row["from_email"] or "")
            if not senders or not senders <= own:
                continue
            mid = thread(row["message_id_header"])
            if mid == root:
                continue
            source_id = identifier(row["id"])
            if source_id in candidates or mid in mids:
                return []
            candidates[source_id] = mid
            mids.add(mid)
        if len(candidates) > 20:
            return []
    except (AssignmentError, KeyError, TypeError):
        return []
    replies = []
    absent = False
    for source_id in candidates:
        if time.monotonic() >= deadline:
            raise AssignmentError("Ownership evidence deadline exceeded")
        activity = evidence._member_activity(source_id, root, deadline=deadline, local_hint=True)
        if activity.status is evidence._ActivityStatus.ABSENT:
            absent = True
        elif activity.status is evidence._ActivityStatus.NON_WITNESS:
            replies.append(evidence.reply(source_id, root, deadline=deadline))
        else:
            if activity.status is evidence._ActivityStatus.POSITIVE and not _early_source_sent(actor, current, activity.payload, root, deadline):
                raise AssignmentError("Early member source no longer sent")
            replies.append(activity.payload)
    if absent:
        scope = mail.mailbox_digest(actor)
        for box in mail.configured(actor, current):
            entry = sent_index._entry(actor, box, scope, deadline)
            sent_index._acquire(entry.lock, deadline)
            try:
                entry.invalidate()
            finally:
                entry.lock.release()
    return _EarlyReplies(replies if absent or any(not item["complete"] or item["judgement"] == "MEMBER_ACTIVITY_REQUIRES_HUMAN_VERIFICATION" for item in replies) else [], absent)

#: Judgements of a member's own message that keep a thread for people.
_HOLDING = frozenset({"NONAUTOMATIC_MEMBER_REPLY_CANDIDATE", "INTERNAL_MEMBER_CORRESPONDENCE",
                      "OWN_SENT_EXTERNAL_FOLLOWUP", "MEMBER_ACTIVITY_REQUIRES_HUMAN_VERIFICATION"})


def _member_hold_seconds():
    """Length of the member-activity hold from MEMBER_ACTIVITY_HOLD_HOURS.

    Default 72. ``0`` or a negative value keeps the hold without a limit: the
    answer is then None.
    """
    raw = (os.environ.get("MEMBER_ACTIVITY_HOLD_HOURS") or "72").strip()
    try:
        hours = int(raw)
    except ValueError:
        hours = 72
    return None if hours <= 0 else hours * 3600


def _member_hold_lapsed(actor, known, replies, aliases) -> bool:
    """Whether the member-activity hold of this thread has run out.

    A member's own message keeps a thread for people. The hold ends when the
    newest message from outside the company is older than the limit and newer
    than every holding member message: the customer wrote last and nobody
    answered in time. While a member wrote last the hold stays. An automatic
    message from outside, such as an out-of-office reply, is not the customer
    writing. A missing time keeps the hold.
    """
    limit = _member_hold_seconds()
    if limit is None:
        return False
    holding = {item.get("source_id") for item in replies if item["judgement"] in _HOLDING}
    if not holding or not all(isinstance(value, str) for value in holding):
        return False
    times = mail.timestamps(actor, [row["id"] for row in known])
    outside = [times.get(row["id"]) for row in known
               if not mail.addresses(row["from_email"] or "") <= aliases]
    members = [times.get(value) for value in holding]
    if None in outside or None in members:
        return False
    written = [stamp for stamp, automatic in outside if not automatic]
    if not written:
        return False
    newest = max(written)
    return max(stamp for stamp, _ in members) < newest and time.time() - newest > limit


def _project(root: str, deadline: float) -> dict:
    started = time.monotonic()
    thread(root)
    actor, space, current = evidence.admission()
    stored = store.get(root, deadline=deadline)
    task = stored["task"]
    value = {
        "version": 1,
        "actor_uid": actor.uid,
        "space_id": space,
        "thread_key": root,
        "authoritative_thread_key": stored["authoritative_thread_key"],
        "component_thread_keys": stored["component_thread_keys"],
        "component_scope_present": stored["component_scope_present"],
        "source_owner_uid": task["creator_uid"] if task else actor.uid,
        "complete": False,
        "state": "unknown",
        "hold_auto_reply": True,
        "task": task,
        "events": stored["events"],
        "covered_inbound": task["covered_inbound"] if task else [],
        "current_inbound": [],
        "current_message_ids": [],
        "covered_message_ids": message_ids(task["covered_inbound"]) if task else [],
        "reply_evidence": [],
        "route_digest": None,
        "reason": "SOURCE_UNAVAILABLE",
    }
    try:
        value["route_digest"] = trust.delivery_routes_digest(space)
        if not stored["complete"]:
            if task is None:
                # Store lookup conservatively withholds component authority.
                # Distinguish only the typed, reproducible graph contradiction;
                # every other incomplete source retains its ordinary handling.
                try:
                    mail.component(actor, root, deadline=deadline)
                except mail.RFCAncestryConflict:
                    value.update(state="conflict", reason="RFC_ANCESTRY_CONFLICT")
                except AssignmentError:
                    pass
                if value["state"] != "conflict":
                    observed = evidence.malformed_own_sent(root, deadline=deadline)
                    if observed["complete"]:
                        value.update(state="needs-assignment", reason="NEEDS_HUMAN_VERIFICATION",
                                     authority_complete=False, hold_scope="exact_observed_message",
                                     reply_evidence=[observed])
            identity.recheck(actor, space)
            if trust.delivery_routes_digest(space) != value["route_digest"]:
                raise AssignmentError("Delivery routes changed during projection")
            latest = store.get(root, deadline=deadline)
            if latest["task"] != task or latest["complete"] != stored["complete"]:
                value.update(state="conflict", reason="ASSIGNMENT_CHANGED", task=latest["task"], events=latest["events"],
                             source_owner_uid=latest["task"]["creator_uid"] if latest["task"] else actor.uid)
            if time.monotonic() >= deadline:
                raise AssignmentError("Ownership evidence deadline exceeded")
            return value
        if task and task["state"] == "closed" and task["creator_uid"] != actor.uid:
            value["reason"] = "SOURCE_OWNER_REQUIRED"
            return value
        if task and task["state"] == "closed":
            # Only closed work needs fresh provider-backed inbound coverage.
            snapshot = evidence.snapshot(root, deadline=deadline)
            value["current_inbound"] = snapshot["covered_inbound"]
            value["current_message_ids"] = message_ids(snapshot["covered_inbound"])
            state = "later-inbound" if set(snapshot["covered_inbound"]) - set(task["covered_inbound"]) else "closed"
            value.update(complete=True, state=state, hold_auto_reply=state != "later-inbound",
                         reason="NEW_INBOUND_AFTER_CLOSE" if state == "later-inbound" else "HANDLED_ACKNOWLEDGED")
        else:
            known = mail.rows(actor, root, deadline=deadline)
            aliases = {alias for group in current["members"].values() for alias in group}
            value["current_message_ids"] = sorted({row["message_id_header"] for row in known
                                                   if not mail.addresses(row["from_email"] or "") <= aliases})
            if task:
                # Active company ownership is authoritative even without closure IO.
                value.update(complete=True, state="assigned", hold_auto_reply=True,
                             reason="HUMAN_ASSIGNMENT_ACTIVE")
            else:
                replies = _early_replies(actor, current, known, root, deadline)
                full = getattr(replies, "force_full_scan", False) or not replies or any(not item["complete"] for item in replies)
                # A hold ends only on the complete Sent membership: a newer
                # member message can sit in Sent before the archive holds it.
                recheck = not full and _member_hold_lapsed(actor, known, replies, aliases)
                if full or recheck:
                    discovered = sent_index.candidates(actor, current, known, root, deadline=deadline)
                    seen = {item.get("source_id") for item in replies} if recheck else set()
                    for item in discovered:
                        if time.monotonic() >= deadline:
                            raise AssignmentError("Ownership evidence deadline exceeded")
                        if "source_id" in item and item["source_id"] in seen:
                            continue
                        if "source_id" in item:
                            # Signed-source confirmation retains the same live checks.
                            activity = evidence._member_activity(item["source_id"], root, deadline=deadline)
                            replies.append(evidence.reply(item["source_id"], root, deadline=deadline)
                                           if activity.status is evidence._ActivityStatus.NON_WITNESS else activity.payload)
                        else:
                            replies.append(item)

                if time.monotonic() >= deadline:
                    raise AssignmentError("Ownership evidence deadline exceeded")
                value["reply_evidence"] = replies
                if any(not item["complete"] for item in replies):
                    value["reason"] = "REPLY_SOURCE_UNAVAILABLE"
                elif any(item["judgement"] in _HOLDING for item in replies):
                    # Only after the complete Sent membership, read above.
                    if (full or recheck) and _member_hold_lapsed(actor, known, replies, aliases):
                        logger.info("[tasks.assignment] member hold expired")
                        value.update(complete=True, state="normal", hold_auto_reply=False,
                                     reason="MEMBER_ACTIVITY_HOLD_EXPIRED")
                    else:
                        value.update(state="needs-assignment", reason="NEEDS_HUMAN_VERIFICATION")
                else:
                    value.update(complete=True, state="normal", hold_auto_reply=False,
                                 reason="NO_HUMAN_ASSIGNMENT")
        identity.recheck(actor, space)
        if trust.delivery_routes_digest(space) != value["route_digest"]:
            raise AssignmentError("Delivery routes changed during projection")
        latest = store.get(root, deadline=deadline)
        if (not latest["complete"] or latest["task"] != task or latest["authoritative_thread_key"] != stored["authoritative_thread_key"]
                or latest["component_thread_keys"] != stored["component_thread_keys"]):
            value.update(
                complete=False, state="conflict", hold_auto_reply=True, reason="ASSIGNMENT_CHANGED"
            )
            value["task"], value["events"] = latest["task"], latest["events"]
    except Exception as error:
        _diagnostic("assignment.source.failed", "failed", root, started, error=error)
        logger.warning("[tasks.assignment] projection held type=%s", type(error).__name__)
        value.update(
            complete=False, state="unknown", hold_auto_reply=True, reason="SOURCE_UNAVAILABLE"
        )
    return value
