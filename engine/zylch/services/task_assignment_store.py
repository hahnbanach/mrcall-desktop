"""Authenticated company task persistence with exact approval and atomic CAS."""

import logging
import time
import uuid
from typing import Any, Protocol

from sqlalchemy import insert, select, update

from zylch.services import project_store
from zylch.storage.assigned_task_models import AssignedTask, AssignedTaskEvent, AssignedTaskReceipt

from . import task_assignment_approval as approval
from . import task_assignment_identity as identity
from . import task_assignment_trust as trust
from .task_assignment_types import AssignmentError, digest, thread, validate_intent

logger = logging.getLogger(__name__)
T, E, R = AssignedTask.__table__, AssignedTaskEvent.__table__, AssignedTaskReceipt.__table__


class Evidence(Protocol):
    def prepare(self, intent: dict) -> Any: ...
    def validate_locked(self, conn: Any, intent: dict, prepared: Any) -> None: ...


def _admit(actor: identity.Actor, space: str, conn: Any) -> dict:
    from .task_assignment_enrollment import require_managed

    require_managed(conn, space)
    current = identity.recheck(actor, space)
    from zylch.storage.join_fence_model import MemoryJoinFence

    fence = MemoryJoinFence.__table__
    if conn.execute(
        select(fence.c.id).where(fence.c.phase.in_(("fenced", "accepted"))).limit(1)
    ).first():
        raise AssignmentError("Company join is in progress")
    return current


def listing() -> dict:
    actor = identity.actor()
    with project_store.connection() as (conn, space):
        _admit(actor, space, conn)
        items = [
            dict(r)
            for r in conn.execute(
                select(T).where(T.c.space_id == space).order_by(T.c.thread_key)
            ).mappings()
        ]
        return {"complete": True, "space_id": space, "items": items}


def get(thread_key: str) -> dict:
    thread(thread_key)
    actor = identity.actor()
    with project_store.connection() as (conn, space):
        _admit(actor, space, conn)
        row = (
            conn.execute(select(T).where(T.c.space_id == space, T.c.thread_key == thread_key))
            .mappings()
            .one_or_none()
        )
        events = (
            []
            if row is None
            else [
                dict(r)
                for r in conn.execute(
                    select(E).where(E.c.task_id == row["id"]).order_by(E.c.revision)
                ).mappings()
            ]
        )
        return {
            "complete": True,
            "space_id": space,
            "task": dict(row) if row else None,
            "events": events,
        }


def preview(
    operation: str,
    thread_key: str,
    expected_revision: int,
    assignee_uid: str | None = None,
    task_id: str | None = None,
    reason: str = "",
    handled_ref: str | None = None,
    covered_inbound: list[str] | None = None,
    source_confirmation: dict | None = None,
    source_snapshot: dict | None = None,
) -> dict:
    thread(thread_key)
    actor = identity.actor()
    now = int(time.time())
    with project_store.connection() as (conn, space):
        current = _admit(actor, space, conn)
        if assignee_uid is not None:
            trust.member(current, assignee_uid)
        old = (
            conn.execute(select(T).where(T.c.space_id == space, T.c.thread_key == thread_key))
            .mappings()
            .one_or_none()
        )
        intent = {
            "version": 1,
            "operation": operation,
            "operation_id": str(uuid.uuid4()),
            "actor_uid": actor.uid,
            "space_id": space,
            "thread_key": thread_key,
            "task_id": task_id or (old["id"] if old else str(uuid.uuid4())),
            "expected_revision": expected_revision,
            "assignee_uid": assignee_uid,
            "reason": reason,
            "handled_ref": handled_ref,
            "covered_inbound": covered_inbound if covered_inbound is not None else [],
            "source_confirmation": source_confirmation,
            "source_snapshot": source_snapshot,
            "created_at": now,
            "expires_at": now + 300,
        }
        validate_intent(intent)
        _check_old(old, intent)
        logger.debug("[tasks.assignment] preview(operation=%s) -> prepared", operation)
        return intent


def _check_old(old: Any, intent: dict) -> None:
    revision = old["revision"] if old else 0
    if revision != intent["expected_revision"] or (old and old["id"] != intent["task_id"]):
        raise AssignmentError("Assignment revision conflict", -32061)
    if intent["operation"] == "assign":
        if old and old["state"] != "closed":
            raise AssignmentError("Thread is already assigned", -32061)
    elif not old or old["state"] != "assigned":
        raise AssignmentError("No active assignment to change", -32061)


def _replay(conn: Any, intent: dict, nonce: str) -> dict | None:
    old = (
        conn.execute(select(R).where(R.c.operation_id == intent["operation_id"]))
        .mappings()
        .one_or_none()
    )
    if old is not None:
        if old["payload_digest"] != digest(intent) or old["nonce"] != nonce:
            raise AssignmentError("Conflicting assignment operation replay")
        return dict(old["receipt"])
    if conn.execute(select(R.c.operation_id).where(R.c.nonce == nonce)).first():
        raise AssignmentError("Assignment approval nonce was already consumed")
    return None


def commit(intent: dict, grant: dict, *, evidence: Evidence | None = None) -> dict:
    from zylch.services.request_policy import is_read_only

    if is_read_only():
        raise AssignmentError("Read-only requests cannot commit assignments")
    validate_intent(intent, fresh=False)
    actor = identity.actor()
    if intent["actor_uid"] != actor.uid:
        raise AssignmentError("Assignment actor does not match verified identity")
    with project_store.connection(intent["space_id"]) as (conn, space):
        current = _admit(actor, space, conn)
        nonce = approval.verify(intent, grant, current)
        replay = _replay(conn, intent, nonce)
        if replay is not None:
            return replay
    validate_intent(intent)
    required = intent["operation"] == "close" or intent["source_confirmation"] is not None
    if required and evidence is None:
        raise AssignmentError("Current verified source evidence is required")
    prepared = evidence.prepare(intent) if required else None
    with project_store.connection(intent["space_id"], write=True) as (conn, space):
        current = _admit(actor, space, conn)
        nonce = approval.verify(intent, grant, current)
        replay = _replay(conn, intent, nonce)
        if replay is not None:
            return replay
        validate_intent(intent)
        if intent["assignee_uid"] is not None:
            trust.member(current, intent["assignee_uid"])
        old = (
            conn.execute(
                select(T).where(T.c.space_id == space, T.c.thread_key == intent["thread_key"])
            )
            .mappings()
            .one_or_none()
        )
        _check_old(old, intent)
        if required:
            evidence.validate_locked(conn, intent, prepared)
        now = int(time.time())
        closed = intent["operation"] == "close"
        revision = intent["expected_revision"] + 1
        values = {
            "id": intent["task_id"],
            "space_id": space,
            "thread_key": intent["thread_key"],
            "revision": revision,
            "state": "closed" if closed else "assigned",
            "assignee_uid": old["assignee_uid"] if closed else intent["assignee_uid"],
            "creator_uid": old["creator_uid"] if old else actor.uid,
            "covered_inbound": intent["covered_inbound"] if closed else [],
            "source_confirmation": intent["source_confirmation"],
            "closed_at": now if closed else None,
            "close_reason": intent["reason"] if closed else None,
            "handled_ref": intent["handled_ref"] if closed else None,
            "updated_at": now,
        }
        if old is None:
            conn.execute(insert(T).values(**values))
        else:
            conn.execute(update(T).where(T.c.id == old["id"]).values(**values))
        conn.execute(
            insert(E).values(
                operation_id=intent["operation_id"],
                task_id=intent["task_id"],
                space_id=space,
                revision=revision,
                actor_uid=actor.uid,
                approval_issuer=current["issuer"],
                approver_os_uid=0,
                operation=intent["operation"],
                intent=intent,
                created_at=now,
            )
        )
        receipt = {
            "acknowledged": True,
            "operation_id": intent["operation_id"],
            "task_id": intent["task_id"],
            "space_id": space,
            "revision": revision,
            "state": values["state"],
            "assignee_uid": values["assignee_uid"],
            "covered_inbound": values["covered_inbound"],
            "handled_ref": values["handled_ref"],
            "payload_digest": digest(intent),
            "approval_issuer": current["issuer"],
            "approver_os_uid": 0,
            "basis": (
                "handled_close"
                if closed
                else ("supervised_reply" if intent["source_confirmation"] else "explicit_manual")
            ),
        }
        conn.execute(
            insert(R).values(
                operation_id=intent["operation_id"],
                nonce=nonce,
                payload_digest=digest(intent),
                receipt=receipt,
            )
        )
        logger.debug(
            "[tasks.assignment] commit(operation=%s) -> acknowledged revision=%s",
            intent["operation"],
            revision,
        )
        return receipt
