"""Compatibility reads and explicit retirement of the old paired-copy routes."""
import os

from .draft_queries import _owner_id, drafts_get


def required(params, name):
    value = params.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + " is required")
    return value


def profile_binding():
    from zylch.auth import get_session
    from zylch.services.exact_draft_delivery import EvidenceRefusal
    owner, uid = _owner_id(), os.environ.get("OWNER_ID", "")
    active = get_session()
    if not uid or active is not None and (active.uid != uid or active.is_expired()):
        raise EvidenceRefusal("owner_profile_mismatch")
    return owner, uid


def retired(params):
    return {"ok": False, "cause": "legacy_private_draft_route_retired",
            "reason": "legacy_private_draft_route_retired", "draft_id": params.get("draft_id"),
            "effect_certainty": "not-dispatched", "next_action": "use-mailbox-draft-operations"}


async def drafts_inspect(params, notify):
    """drafts.inspect(draft_id) -> compatibility read of the actual mailbox draft."""
    return await drafts_get(params, notify)


async def drafts_discard_exact(params, notify):
    """drafts.discard_exact(draft_id?, expected_snapshot?, dry_run=False) -> retired route refusal."""
    return retired(params)


async def drafts_reconcile_external(params, notify):
    """drafts.reconcile_external(draft_id?, sent_message_id?) -> retired route refusal."""
    return retired(params)


async def drafts_publish_review(params, notify):
    """drafts.publish_review(draft_id?, expected_snapshot?, thread_id?, operation_id?) -> retired route refusal."""
    return retired(params)


async def drafts_retire_sent_mirror(params, notify):
    """drafts.retire_sent_mirror(draft_id?, expected_snapshot?, thread_id?, operation_id?, target?, commit=False) -> retired route refusal."""
    return retired(params)


async def drafts_operator_send_inspect(params, notify):
    """drafts.operator_send_inspect(draft_id?) -> retired route refusal."""
    return retired(params)


async def drafts_send_operator(params, notify):
    """drafts.send_operator(draft_id?, expected_snapshot?, operation_id?, binding?, reason?, version?) -> retired route refusal."""
    return retired(params)


async def drafts_operation_status(params, notify):
    """drafts.operation_status(operation_id) -> retained owner-scoped legacy operation evidence."""
    from zylch.storage.draft_operations import DraftOperations
    operation_id = required(params, "operation_id")
    try:
        _, uid = profile_binding()
    except ValueError as error:
        return {"ok": False, "cause": str(error), "operation": None}
    value = DraftOperations().read(uid, operation_id)
    return {"ok": value is not None, "operation": value}


METHODS = {"drafts.inspect": drafts_inspect, "drafts.discard_exact": drafts_discard_exact,
           "drafts.reconcile_external": drafts_reconcile_external,
           "drafts.publish_review": drafts_publish_review,
           "drafts.retire_sent_mirror": drafts_retire_sent_mirror,
           "drafts.operator_send_inspect": drafts_operator_send_inspect,
           "drafts.send_operator": drafts_send_operator,
           "drafts.operation_status": drafts_operation_status}
