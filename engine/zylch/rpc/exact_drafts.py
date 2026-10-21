"""Explicit owner-scoped exact draft inspection, retirement and Sent recording."""

import asyncio
from datetime import datetime
import os
import logging
from typing import Any, Awaitable, Callable

from zylch.services import exact_draft_delivery as delivery
from zylch.services.request_policy import assert_tool_allowed
from zylch.services.exact_draft_transaction import locked_row, session, effect
from zylch.services.task_assignment_types import AssignmentError
from zylch.storage.models import Draft
from zylch.storage.storage import Storage
from zylch.rpc.draft_actions import _owner_id, _discard_refusal

logger = logging.getLogger(__name__)
NotifyFn = Callable[[str, dict[str, Any]], None]


def required(params: dict[str, Any], name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + " is required")
    return value


def profile_binding() -> tuple[str, str]:
    from zylch.auth import get_session

    owner, uid = _owner_id(), os.environ.get("OWNER_ID", "")
    active = get_session()
    if not uid or (active is not None and (active.uid != uid or active.is_expired())):
        raise delivery.EvidenceRefusal("owner_profile_mismatch")
    return owner, uid


def result(draft_id: str, **values: Any) -> dict[str, Any]:
    logger.debug(
        "[rpc:exact-drafts] result ok=%s reason=%s discarded=%s preflight=%s reconciled=%s",
        values.get("ok"),
        values.get("reason"),
        values.get("discarded"),
        values.get("would_discard"),
        values.get("reconciled"),
    )
    return {
        "draft_id": draft_id,
        "engine_owner_uid": os.environ.get("OWNER_ID", ""),
        "owner_id": _owner_id(),
        "automatic_reconciliation": False,
        **values,
    }


async def drafts_inspect(params: dict[str, Any], notify: NotifyFn) -> dict[str, Any]:
    """drafts.inspect(draft_id) -> exact owner row and expected_snapshot."""
    logger.debug("[rpc:drafts.inspect] started")
    draft_id = required(params, "draft_id")
    try:
        owner, _uid = profile_binding()
    except delivery.EvidenceRefusal as error:
        return result(draft_id, ok=False, reason=str(error))
    draft = Storage.get_instance().get_draft(owner, draft_id)
    if draft is None:
        return result(draft_id, ok=False, reason="not_found")
    return result(draft_id, ok=True, draft=draft, expected_snapshot=delivery.snapshot(draft))


async def drafts_discard_exact(params: dict[str, Any], notify: NotifyFn) -> dict[str, Any]:
    """drafts.discard_exact(draft_id, expected_snapshot, dry_run=False) -> guarded preflight or exact deletion acknowledgement."""
    logger.debug("[rpc:drafts.discard_exact] started")
    draft_id = required(params, "draft_id")
    expected = required(params, "expected_snapshot")
    dry_run = params.get("dry_run", False)
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be boolean")
    assert_tool_allowed("delete_draft")
    try:
        owner, uid = profile_binding()
    except delivery.EvidenceRefusal as error:
        return result(draft_id, ok=False, reason=str(error))
    draft = Storage.get_instance().get_draft(owner, draft_id)
    if draft is None:
        return result(draft_id, ok=False, discarded=False, reason="not_found")
    if delivery.snapshot(draft) != expected:
        return result(draft_id, ok=False, discarded=False, reason="stale_snapshot")
    refusal = _discard_refusal(draft)
    if refusal:
        return result(draft_id, ok=False, discarded=False, reason=refusal)
    # Preserve existing assignment and contextual authority before acquiring
    # the private writer (company -> private is the canonical lock order).
    try:
        with effect(owner, draft):
            with locked_row(owner, draft_id, draft):
                if profile_binding() != (owner, uid):
                    raise AssignmentError("Owner profile changed before effect")
                with session() as current:
                    row = (
                        current.query(Draft)
                        .filter(Draft.owner_id == owner, Draft.id == draft_id)
                        .one()
                    )
                    if not dry_run:
                        current.delete(row)
    except (AssignmentError, delivery.EvidenceRefusal):
        return result(draft_id, ok=False, discarded=False, reason="state_or_authority_changed")
    if dry_run:
        return result(
            draft_id, ok=True, discarded=False, would_discard=True, expected_snapshot=expected
        )
    return result(draft_id, ok=True, discarded=True, consumed_snapshot=expected)


async def drafts_reconcile_external(params: dict[str, Any], notify: NotifyFn) -> dict[str, Any]:
    """drafts.reconcile_external(draft_id, sent_message_id) -> independently verified explicit Sent recording."""
    logger.debug("[rpc:drafts.reconcile_external] started")
    draft_id = required(params, "draft_id")
    message_id = required(params, "sent_message_id")
    assert_tool_allowed("update_draft")
    try:
        owner, uid = profile_binding()
    except delivery.EvidenceRefusal as error:
        return result(draft_id, ok=False, reason=str(error))
    draft = Storage.get_instance().get_draft(owner, draft_id)
    if draft is None:
        return result(draft_id, ok=False, reconciled=False, reason="not_found")
    if draft["status"] == "sending":
        return result(draft_id, ok=False, reconciled=False, reason="send_in_flight")
    if draft["status"] == "sent" and draft.get("sent_message_id") != message_id:
        return result(draft_id, ok=False, reconciled=False, reason="conflicting_sent_evidence")
    try:
        sent_at = await asyncio.to_thread(delivery.verify_sent, owner, draft, message_id)
        with locked_row(owner, draft_id, draft):
            if profile_binding() != (owner, uid):
                raise delivery.EvidenceRefusal("owner_profile_mismatch")
            # This records an already completed delivery. Send admission would
            # incorrectly refuse legitimate evidence after a later assignment.
            with session() as current:
                row = (
                    current.query(Draft).filter(Draft.owner_id == owner, Draft.id == draft_id).one()
                )
                idempotent = row.status == "sent"
                if idempotent and row.sent_at != sent_at:
                    raise delivery.EvidenceRefusal("conflicting_sent_evidence")
                if not idempotent:
                    row.status = "sent"
                    row.sent_at = sent_at
                    row.sent_message_id = message_id
                    row.updated_at = datetime.utcnow()
    except delivery.EvidenceRefusal as error:
        return result(draft_id, ok=False, reconciled=False, reason=str(error))
    except AssignmentError:
        return result(draft_id, ok=False, reconciled=False, reason="stale_snapshot")
    return result(
        draft_id,
        ok=True,
        reconciled=True,
        sent_message_id=message_id,
        sent_at=sent_at.isoformat(),
        idempotent=idempotent,
    )


METHODS: dict[str, Callable[[dict[str, Any], NotifyFn], Awaitable[dict[str, Any]]]] = {
    "drafts.inspect": drafts_inspect,
    "drafts.discard_exact": drafts_discard_exact,
    "drafts.reconcile_external": drafts_reconcile_external,
}
