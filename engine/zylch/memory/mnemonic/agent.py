"""The mnemonic role: one bounded, budgeted decision per event.

The role is the only place a canonical memory decision is made. The outer chat
agent, the task solver and the fact/rule helpers propose observations; what the
memory should become is decided here and checked by the validator.

Milestone 2 stops at the decision. There is no commit module yet, so an
accepted mutation proposal is carried on :class:`MnemonicDecision` and its
result is ``retryable_failure`` — no mutation happened and the event can be
submitted again once milestone 3 installs ``mnemonic/commit.py``. It is not
reported as a refusal: the proposal was safe, the capability is simply absent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Tuple

from zylch.llm.budget import BudgetError
from zylch.memory.response_validation import (
    MemoryResponseError,
    complete_memory_text,
    strict_json_object,
)

from . import prompts
from .authorization import (
    MnemonicAuthorizationError,
    MnemonicRefusal,
    authorize_request,
    dispatch_scope,
    issue_grant,
    revoke_grant,
)
from .contracts import (
    MAX_DECISION_ATTEMPTS,
    MNEMONIC_MAX_TOKENS,
    NO_COMMIT_CAPABILITY,
    REVIEW,
    SKIP,
    Candidate,
    MemoryEvent,
    MnemonicContractError,
)
from .proposals import MnemonicResult, Proposal, Reclassification, WriteTarget
from .validator import Validation, review_reason, validate

logger = logging.getLogger(__name__)

CALL_SITE = "memory.mnemonic"


@dataclass(frozen=True)
class MnemonicDecision:
    """What one event's decision round produced, and what it cost."""

    event_id: str
    result: MnemonicResult
    proposal: Optional[Proposal] = None
    validation: Optional[Validation] = None
    attempts: int = 0

    @property
    def accepted(self) -> bool:
        """A validated mutation proposal, waiting only for a commit capability."""
        return (
            self.proposal is not None
            and self.proposal.mutates
            and self.validation is not None
            and self.validation.ok
        )


# ─── Model text → strict proposal ─────────────────────────────────────


def adapt_response(response: Any) -> Proposal:
    """Turn a complete model response into a strict proposal, or refuse it.

    Every refusal here happens *before* validation, because a malformed answer
    is not a bad proposal — it is no proposal. ``complete_memory_text`` rejects
    an unfinished stop reason (truncation), an unexpected tool call and empty
    content; ``strict_json_object`` rejects empty or malformed JSON and a
    complete object trailed by prose.
    """
    text = complete_memory_text(response)
    payload = strict_json_object(text)
    return _proposal_from(payload)


def _proposal_from(payload: Mapping[str, Any]) -> Proposal:
    try:
        return Proposal(
            action=_upper(payload.get("action")),
            entity_type=_upper(payload.get("entity_type")) or None,
            scope=_lower(payload.get("scope")) or None,
            content=payload.get("content") or "",
            write_set=_write_set(payload.get("write_set")),
            reason=payload.get("reason") or "",
            reclassification=_reclassification(payload.get("reclassification")),
            declared_effects=_effects(payload.get("declared_effects")),
            no_op_target=_single_target(payload.get("no_op_target")),
            confidence=_confidence(payload.get("confidence")),
        )
    except MnemonicContractError as exc:
        raise MemoryResponseError(f"Memory decision breaks its contract: {exc}") from None


def _upper(value: Any) -> str:
    return value.strip().upper() if isinstance(value, str) else ""


def _lower(value: Any) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def _write_set(raw: Any) -> Tuple[WriteTarget, ...]:
    if raw in (None, ""):
        return ()
    if not isinstance(raw, list):
        raise MnemonicContractError("write_set must be a list")
    return tuple(_target(entry, default_role="target") for entry in raw)


def _single_target(raw: Any) -> Optional[WriteTarget]:
    if raw in (None, ""):
        return None
    return _target(raw, default_role="target")


def _target(entry: Any, *, default_role: str) -> WriteTarget:
    if not isinstance(entry, Mapping):
        raise MnemonicContractError("a write target must be an object")
    return WriteTarget(
        blob_id=str(entry.get("blob_id") or ""),
        expected_version=str(entry.get("expected_version") or ""),
        role=_lower(entry.get("role")) or default_role,
    )


def _effects(raw: Any) -> Tuple[str, ...]:
    if raw in (None, ""):
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise MnemonicContractError("declared_effects must be a list of strings")
    return tuple(item.strip() for item in raw if item.strip())


def _reclassification(raw: Any) -> Optional[Reclassification]:
    if raw in (None, ""):
        return None
    if not isinstance(raw, Mapping):
        raise MnemonicContractError("reclassification must be an object")
    return Reclassification(
        from_entity_type=_upper(raw.get("from_entity_type")),
        from_scope=_lower(raw.get("from_scope")),
        to_entity_type=_upper(raw.get("to_entity_type")),
        to_scope=_lower(raw.get("to_scope")),
    )


def _confidence(raw: Any) -> Optional[float]:
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise MnemonicContractError("confidence must be a number") from None


# ─── The decision round ───────────────────────────────────────────────


def decide(
    event: MemoryEvent,
    candidates: Sequence[Candidate],
    *,
    client: Any = None,
) -> MnemonicDecision:
    """Authorize, dispatch, adapt and validate — at most three bounded rounds.

    A rejected proposal is re-decided with the validator's reasons appended, up
    to :data:`MAX_DECISION_ATTEMPTS`, each round paying its own ordinary
    reservation. It never falls through to CREATE: a decision that cannot be
    validated becomes ``review_needed``, which is visible and costs nothing
    further.
    """
    try:
        authorize_request(event)
    except MnemonicRefusal as exc:
        # Refused before a grant exists: no reservation, no provider call.
        return MnemonicDecision(
            event_id=event.event_id,
            result=MnemonicResult.review_needed(event.event_id, str(exc)),
        )

    if client is None:
        client = _default_client()

    grant = issue_grant(event)
    conversation: list[dict] = [
        {"role": "user", "content": prompts.user_message(event, candidates)}
    ]
    proposal: Optional[Proposal] = None
    validation: Optional[Validation] = None
    errors: Tuple[str, ...] = ()
    attempts = 0

    try:
        while attempts < MAX_DECISION_ATTEMPTS:
            if event.cancellation.cancelled:
                return _failure(
                    event, attempts, event.cancellation.reason or "event cancelled", proposal
                )
            attempts += 1
            try:
                response = _dispatch(client, conversation, grant)
            except MnemonicAuthorizationError as exc:
                return MnemonicDecision(
                    event_id=event.event_id,
                    result=MnemonicResult.review_needed(event.event_id, str(exc)),
                    attempts=attempts - 1,
                )
            except BudgetError as exc:
                return _failure(event, attempts - 1, f"paid decision unavailable: {exc}", proposal)

            try:
                proposal = adapt_response(response)
            except MemoryResponseError as exc:
                proposal, errors = None, (str(exc),)
                logger.info(f"[mnemonic] unusable response event={event.event_id}: {exc}")
                conversation = _retry_turn(conversation, response, errors)
                continue

            validation = validate(event, proposal, candidates)
            if validation.ok:
                break
            errors = validation.errors
            logger.info(
                f"[mnemonic] rejected event={event.event_id} action={proposal.action} "
                f"reasons={len(errors)}"
            )
            conversation = _retry_turn(conversation, response, errors)
        else:
            return MnemonicDecision(
                event_id=event.event_id,
                result=MnemonicResult.review_needed(
                    event.event_id,
                    "; ".join(errors) or "no valid decision after the bounded attempts",
                    proposal=proposal,
                    attempts=attempts,
                ),
                proposal=proposal,
                validation=validation,
                attempts=attempts,
            )
    finally:
        revoke_grant(grant)

    return _accepted(event, proposal, validation, attempts)


def _accepted(
    event: MemoryEvent,
    proposal: Proposal,
    validation: Validation,
    attempts: int,
) -> MnemonicDecision:
    if proposal.action == SKIP:
        result = MnemonicResult.skipped(
            event.event_id,
            proposal.reason or "nothing durable to record",
            proposal=proposal,
            attempts=attempts,
        )
    elif proposal.action == REVIEW:
        result = MnemonicResult.review_needed(
            event.event_id,
            proposal.reason or "the decision asked for human review",
            proposal=proposal,
            attempts=attempts,
        )
    else:
        # Validated, safe, and nothing wrote it: milestone 3 owns the commit.
        result = MnemonicResult.retryable_failure(
            event.event_id, NO_COMMIT_CAPABILITY, proposal=proposal, attempts=attempts
        )
    return MnemonicDecision(
        event_id=event.event_id,
        result=result,
        proposal=proposal,
        validation=validation,
        attempts=attempts,
    )


def _failure(
    event: MemoryEvent, attempts: int, reason: str, proposal: Optional[Proposal]
) -> MnemonicDecision:
    return MnemonicDecision(
        event_id=event.event_id,
        result=MnemonicResult.retryable_failure(
            event.event_id, reason, proposal=proposal, attempts=attempts
        ),
        proposal=proposal,
        attempts=attempts,
    )


def _dispatch(client: Any, conversation: Sequence[dict], grant) -> Any:
    """One paid decision call, inside the grant's scope.

    The usage tag is set for spend attribution only. Admission is decided by
    the dispatch scope in ``check_dispatch``, so a call relabelled ``chat`` or
    left untagged inside this scope is checked exactly the same way.
    """
    from zylch.llm.usage import call_site

    with dispatch_scope(grant), call_site(CALL_SITE):
        return client.create_message_sync(
            system=prompts.system_blocks(),
            messages=list(conversation),
            max_tokens=MNEMONIC_MAX_TOKENS,
        )


def _retry_turn(conversation: list, response: Any, errors: Sequence[str]) -> list:
    """Re-ask with the reasons, keeping the original observation turn first.

    The rejected answer is replayed verbatim so the round is a correction and
    not a fresh guess — and the event turn is never rewritten, so the original
    observation still governs.
    """
    reply = ""
    for block in getattr(response, "content", None) or ():
        if getattr(block, "type", None) == "text":
            reply += getattr(block, "text", "")
    return [
        conversation[0],
        {"role": "assistant", "content": reply or "(unusable response)"},
        {
            "role": "user",
            "content": (
                "That decision was refused for these reasons:\n- "
                + "\n- ".join(errors)
                + "\n\nReturn one corrected JSON object. Do not fall back to CREATE to avoid "
                "the problem, and return REVIEW if you cannot decide safely."
            ),
        },
    ]


def _default_client():
    from zylch.llm import routed_model
    from zylch.llm.client import make_llm_client

    return make_llm_client(model=routed_model("MODEL_MEMORY_EXTRACT"))


__all__ = [
    "CALL_SITE",
    "MnemonicDecision",
    "adapt_response",
    "decide",
    "review_reason",
]
