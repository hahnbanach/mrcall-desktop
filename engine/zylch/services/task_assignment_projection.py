"""Visible task ownership with exact inbound coverage and explicit uncertainty."""

import logging
import time

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


def project(root: str) -> dict:
    deadline = time.monotonic() + 120
    value = None
    try:
        with evidence.observation(root, deadline):
            value = _project(root, deadline)
        return value
    except Exception:
        if value is None:
            raise
        value.update(complete=False, state="unknown", hold_auto_reply=True, reason="SOURCE_UNAVAILABLE")
        return value


def _early_source_sent(actor, current, observed, root, deadline):
    source = observed["source"]
    provider = source["provider"]
    box = next((box for box in mail.configured(actor, current) if box.id == source["mailbox_id"]), None)
    if box is None:
        raise AssignmentError("Early reply mailbox unavailable")
    with evidence.provider_client(actor, box, root, deadline) as client:
        state = client.examine_existing(provider["folder"], deadline=deadline)
        if state.uidvalidity != provider["uidvalidity"]:
            raise AssignmentError("Early reply source identity changed")
        headers, state = client.folder_headers(provider["folder"], deadline=deadline, uids=[provider["uid"]],
                                               max_messages=max(state.exists, mail.MAX_MESSAGES))
        header = headers.get(provider["uid"])
        if (header is None or header["message_id"] != source["message_id"]
                or state.uidvalidity != provider["uidvalidity"]):
            raise AssignmentError("Early reply source identity changed")
        return "\\Draft" not in header["flags"]


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
    for source_id in candidates:
        if time.monotonic() >= deadline:
            raise AssignmentError("Ownership evidence deadline exceeded")
        observed = evidence.reply(source_id, root, deadline=deadline)
        replies.append(observed)
        if not observed["complete"]:
            return replies
        if observed["judgement"] in {
            "NONAUTOMATIC_MEMBER_REPLY_CANDIDATE", "INTERNAL_MEMBER_CORRESPONDENCE", "OWN_SENT_EXTERNAL_FOLLOWUP"
        }:
            return replies if _early_source_sent(actor, current, observed, root, deadline) else []
    return []


def _project(root: str, deadline: float) -> dict:
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
                if not replies or any(not item["complete"] for item in replies):
                    discovered = sent_index.candidates(actor, current, known, root, deadline=deadline)
                    discovery_unknown = any("source_id" not in item and not item["complete"] for item in discovered)
                    for item in discovered:
                        if time.monotonic() >= deadline:
                            raise AssignmentError("Ownership evidence deadline exceeded")
                        if "source_id" in item:
                            # Signed-source confirmation retains the same live checks.
                            replies.append(evidence.reply(item["source_id"], root, deadline=deadline))
                        else:
                            replies.append(item)
                        if (not discovery_unknown and all(reply["complete"] for reply in replies)
                                and replies[-1]["judgement"] in {"NONAUTOMATIC_MEMBER_REPLY_CANDIDATE", "INTERNAL_MEMBER_CORRESPONDENCE", "OWN_SENT_EXTERNAL_FOLLOWUP"}):
                            break
                if time.monotonic() >= deadline:
                    raise AssignmentError("Ownership evidence deadline exceeded")
                value["reply_evidence"] = replies
                if any(not item["complete"] for item in replies):
                    value["reason"] = "REPLY_SOURCE_UNAVAILABLE"
                elif any(item["judgement"] in {"NONAUTOMATIC_MEMBER_REPLY_CANDIDATE", "INTERNAL_MEMBER_CORRESPONDENCE", "OWN_SENT_EXTERNAL_FOLLOWUP"} for item in replies):
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
        logger.warning("[tasks.assignment] projection held type=%s", type(error).__name__)
        value.update(
            complete=False, state="unknown", hold_auto_reply=True, reason="SOURCE_UNAVAILABLE"
        )
    return value
