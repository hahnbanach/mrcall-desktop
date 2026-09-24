"""One account rule as a memory event: how the rule store submits it.

The rule store (:mod:`zylch.services.prefs_store`) decides deterministically
what may enter the rule namespaces — shape, exact duplicates, the substring
supersession candidate. Everything past that is a semantic write, and this is
where it becomes one: a STYLE event on the caller's entry, the supersession or
refinement target pinned as the hint and named as the requested write, the
mnemonic role deciding, the rewrite retaining what it replaces. The outcome a
submission that wrote nothing maps to is here too, so the store reports every
result as itself and never as a save.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def submit_rule(owner_id: str, content: str, entry, *, target: Optional[Dict[str, Any]], explicit: bool):
    """One STYLE event through the harness. Returns the result, or a refusal dict."""
    from zylch.memory.company_key import require_company_key
    from zylch.memory.mnemonic import submit
    from zylch.memory.mnemonic.approval import RequestedWrite
    from zylch.memory.mnemonic.contracts import (
        ACCOUNT_SCOPE,
        CREATE,
        OPERATOR_DELEGATED,
        STYLE,
        UPDATE,
        MemoryEvent,
        SubjectHint,
    )
    from zylch.memory.mnemonic.entry import EntryRefused, entry_for

    try:
        entry = entry or entry_for(fallback=content)
    except EntryRefused as exc:
        return {"action": "refused", "blob_id": target["id"] if target else None, "reason": str(exc)}
    try:
        company_key = require_company_key()
    except RuntimeError as exc:
        return {"action": "error", "blob_id": target["id"] if target else None, "reason": str(exc)}
    event = MemoryEvent(
        owner_id=owner_id,
        company_key=company_key,
        caller_class=OPERATOR_DELEGATED,
        origin=entry.origin,
        source_kind=entry.source_kind,
        source_id=entry.source_id,
        source_revision=entry.source_revision,
        observation=entry.observation,
        subject_hint=SubjectHint(entity_type=STYLE, target_blob_id=target["id"] if target else None),
        explicit_request=explicit,
        stage=entry.stage,
        cancellation=entry.cancellation,
    ).with_model_arguments({"content": content})
    requested = (
        RequestedWrite(
            action=UPDATE,
            blob_id=target["id"],
            entity_type=STYLE,
            scope=ACCOUNT_SCOPE,
            subject_is_authoritative=True,
        )
        if target
        else RequestedWrite(action=CREATE, entity_type=STYLE, scope=ACCOUNT_SCOPE)
    )
    return submit(event, requested=requested)


def not_written(result, blob_id: Optional[str], writer: str) -> Dict[str, Any]:
    """The outcome dict for a submission that wrote nothing."""
    if result.outcome == "skipped":
        target = result.proposal.no_op_target if result.proposal else None
        logger.info(f"[prefs] rule from writer={writer} already recorded: {result.reason}")
        return {
            "action": "duplicate",
            "blob_id": target.blob_id if target else blob_id,
            "reason": result.reason,
        }
    if result.outcome == "review_needed":
        logger.info(f"[prefs] rule from writer={writer} needs review: {result.reason}")
        return {"action": "review", "blob_id": blob_id, "reason": result.reason}
    logger.warning(f"[prefs] rule from writer={writer} not written: {result.reason}")
    return {"action": "error", "blob_id": blob_id, "reason": result.reason}


__all__ = ["not_written", "submit_rule"]
