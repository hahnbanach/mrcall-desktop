"""Visible task ownership with exact inbound coverage and explicit uncertainty."""

import logging

from . import task_assignment_evidence as evidence
from . import task_assignment_identity as identity
from . import task_assignment_mail as mail
from . import task_assignment_store as store
from .task_assignment_types import AssignmentError, thread

logger = logging.getLogger(__name__)


def message_ids(identities: list[str]) -> list[str]:
    return sorted({value[65:] for value in identities if len(value) > 65 and value[64] == ":"})


def project(root: str) -> dict:
    thread(root)
    actor, space, current = evidence.admission()
    stored = store.get(root)
    task = stored["task"]
    value = {
        "version": 1,
        "actor_uid": actor.uid,
        "space_id": space,
        "thread_key": root,
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
        "reason": "SOURCE_UNAVAILABLE",
    }
    try:
        if task and task["state"] == "closed" and task["creator_uid"] != actor.uid:
            value["reason"] = "SOURCE_OWNER_REQUIRED"
            return value
        snapshot = evidence.snapshot(root)
        value["current_inbound"] = snapshot["covered_inbound"]
        value["current_message_ids"] = message_ids(snapshot["covered_inbound"])
        if task:
            if task["state"] == "assigned":
                state = "assigned"
            elif set(snapshot["covered_inbound"]) - set(task["covered_inbound"]):
                state = "later-inbound"
            else:
                state = "closed"
            value.update(
                complete=True,
                state=state,
                hold_auto_reply=state != "later-inbound",
                reason={
                    "assigned": "HUMAN_ASSIGNMENT_ACTIVE",
                    "closed": "HANDLED_ACKNOWLEDGED",
                    "later-inbound": "NEW_INBOUND_AFTER_CLOSE",
                }[state],
            )
        else:
            aliases = set(current["members"][actor.uid])
            sources = [
                row
                for row in mail.rows(actor, root)
                if mail.addresses(row["from_email"] or "") <= aliases
                and row["message_id_header"] != root
            ]
            if len(sources) > 20:
                raise AssignmentError("Reply candidates exceed bounds")
            replies = [evidence.reply(row["id"], root) for row in sources]
            value["reply_evidence"] = replies
            if any(not item["complete"] for item in replies):
                value["reason"] = "REPLY_SOURCE_UNAVAILABLE"
            elif any(
                item["judgement"] == "NONAUTOMATIC_MEMBER_REPLY_CANDIDATE" for item in replies
            ):
                value.update(state="needs-assignment", reason="NEEDS_HUMAN_VERIFICATION")
            else:
                value.update(
                    complete=True,
                    state="normal",
                    hold_auto_reply=False,
                    reason="NO_HUMAN_ASSIGNMENT",
                )
        identity.recheck(actor, space)
        latest = store.get(root)
        if latest["task"] != task:
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
