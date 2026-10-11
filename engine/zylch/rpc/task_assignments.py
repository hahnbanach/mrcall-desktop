"""Strict versioned company-assigned task RPC; ordinary tasks stay private."""

import asyncio

from zylch.services import task_assignment_evidence as evidence
from zylch.services import task_assignment_identity as identity
from zylch.services import task_assignment_projection as projection
from zylch.services import task_assignment_store as store
from zylch.services.task_assignment_types import AssignmentError, thread


def _envelope(value: dict, actor, space: str) -> dict:
    identity.recheck(actor, space)
    if value.get("space_id") != space:
        raise AssignmentError("Assignment company binding changed")
    return {"version": 1, "actor_uid": actor.uid, **value}


async def listing(params, notify):
    """tasks.assignment.list() -> authenticated complete company task rows."""
    actor, space, _ = evidence.admission()
    return _envelope(store.listing(), actor, space)


async def get(params, notify):
    """tasks.assignment.get(thread_key) -> authenticated task and retained audit."""
    actor, space, _ = evidence.admission()
    return _envelope(store.get(thread(params["thread_key"])), actor, space)


def _preview(params):
    root = thread(params["thread_key"])
    extras = {}
    if params["operation"] == "close":
        if params.get("source_id") is not None:
            raise AssignmentError("Close cannot confirm a reply source", -32602)
        evidence.require_source_owner(root)
        snapshot = evidence.close_snapshot(root)
        extras = {
            "covered_inbound": snapshot["covered_inbound"],
            "source_snapshot": {
                "digest": snapshot["digest"],
                "observed_at": snapshot["observed_at"],
            },
        }
    elif params.get("source_id") is not None:
        source = evidence.reply(params["source_id"], root)
        if not source["complete"] or source["judgement"] != "NONAUTOMATIC_MEMBER_REPLY_CANDIDATE":
            raise AssignmentError("Exact nonautomatic member reply evidence required")
        extras = {
            "source_confirmation": {"source_id": params["source_id"], "digest": source["digest"]}
        }
    return store.preview(
        params["operation"],
        root,
        params["expected_revision"],
        assignee_uid=params.get("assignee_uid"),
        task_id=params.get("task_id"),
        reason=params.get("reason", ""),
        handled_ref=params.get("handled_ref"),
        **extras,
    )


async def preview(params, notify):
    """tasks.assignment.preview(operation, thread_key, expected_revision, assignee_uid?, task_id?, reason?, handled_ref?, source_id?) -> exact unsigned versioned intent."""
    return await asyncio.to_thread(_preview, params)


async def commit(params, notify):
    """tasks.assignment.commit(intent, grant) -> exact acknowledged assignment receipt."""
    result = await asyncio.to_thread(
        store.commit, params["intent"], params["grant"], evidence=evidence.LiveEvidence()
    )
    return {"version": 1, **result}


async def project(params, notify):
    """tasks.assignment.project(thread_key) -> held/assigned/closed exact-identity projection."""
    return await asyncio.to_thread(projection.project, thread(params["thread_key"]))


async def reply_evidence(params, notify):
    """tasks.assignment.reply_evidence(source_id, thread_key) -> owner-scoped live Sent evidence without mail content."""
    return await asyncio.to_thread(
        evidence.reply, params["source_id"], thread(params["thread_key"])
    )


METHODS = {
    "tasks.assignment.list": listing,
    "tasks.assignment.get": get,
    "tasks.assignment.preview": preview,
    "tasks.assignment.commit": commit,
    "tasks.assignment.project": project,
    "tasks.assignment.reply_evidence": reply_evidence,
}
