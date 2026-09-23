"""The fresh, exact acceptance a changed final mutation must carry.

The harness already has an approval: ``APPROVAL_TOOLS`` stops ``create_memory``,
``update_memory`` and their siblings before the tool runs, and refuses outright
when no approval channel exists. That gate sees the **request** — a blob id and
some new prose, or a query and some new prose. It cannot see the mutation,
because the mutation does not exist yet: the mnemonic role has not decided.

This module is the second gate. Between a validated proposal and the
transaction that writes it, a proposal that **changed** what the caller asked
for — a different action, a different subject, a different scope, or an effect
that absorbs or removes another memory — is shown to a human in full and may
proceed only on an acceptance that names this exact proposal.

**What makes the acceptance exact.** Three name-keyed shortcuts auto-approve in
production today: ``cs --allow`` answers every notification for an allowed tool
name, the engine remembers a ``chat.approve(mode="session")`` grant per
conversation and tool name, and the Desktop card offers "Allow for session".
None of them can be defeated by choosing a new tool name, because all three key
on whatever name is chosen. So the acceptance is not a boolean: it is a
**single-use nonce** issued with the card, which the accepting surface must echo
back together with the proposal digest it saw. An auto-approver returns "yes"
and nothing else, so it fails the check structurally rather than by policy.

**What invalidates it.** The nonce is generated per request and compared against
the request in flight, so an answer to an earlier card is not an answer to this
one — a replayed acceptance and a remembered one fail the same check. The echoed
digest must also equal the digest of the proposal about to be written, and
:func:`~zylch.memory.mnemonic.digests.proposal_digest` covers the write set's
expected versions — so a CAS re-read that lands on a different version, or a
re-decision that revises the prose, no longer matches the acceptance a human gave
and asks again. A denial, a timeout, a cancelled turn and an edited card are all
refusals, not weaker acceptances.

A caller with no channel — a headless run, a scheduled operator, an RPC client
that offers no approval route — gets ``review_needed`` and no write. There is
nobody to ask, and the harness does not decide on a human's behalf.
"""

from __future__ import annotations

import logging
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, Tuple

from .contracts import MemoryEvent, MnemonicContractError
from .digests import input_digest, proposal_digest
from .proposals import Proposal

logger = logging.getLogger(__name__)


# ─── Why a proposal needs a fresh acceptance ──────────────────────────
# Each flag is a structural difference between what the caller asked for and
# what the role decided. They are reported to the human as the reason the card
# appeared, so they are written to be read by one.

CHANGED_ACTION = "changed_action"
CHANGED_SUBJECT = "changed_subject"
CHANGED_SCOPE = "changed_scope"
DESTRUCTIVE_EFFECTS = "destructive_effects"
UNNAMED_SUBJECT = "unnamed_subject"

FLAG_REASONS: Dict[str, str] = {
    CHANGED_ACTION: "the action is not the one this call asked for",
    CHANGED_SUBJECT: "it writes to a memory other than the one this call named",
    CHANGED_SCOPE: "it files the memory under a different scope or family",
    DESTRUCTIVE_EFFECTS: "it absorbs, re-points or removes another memory",
    UNNAMED_SUBJECT: "this call named no memory, so the target was chosen for it",
}


@dataclass(frozen=True)
class RequestedWrite:
    """What the calling tool actually asked for, as its own arguments stated it.

    The adapter fills this in from the tool call, never from the proposal. It is
    the *baseline* the final mutation is compared against, so a legacy argument
    that carried no authority must be recorded as carrying none: a solve
    ``query`` selects nothing and leaves :attr:`blob_id` empty, which is what
    makes every solve update a mutation whose subject the caller did not choose.
    """

    action: str
    blob_id: Optional[str] = None
    entity_type: Optional[str] = None
    scope: Optional[str] = None
    # True when the caller named a concrete blob it intends to write. A tool
    # that only described what to look for did not.
    subject_is_authoritative: bool = False


def flags_for(requested: RequestedWrite, proposal: Proposal) -> Tuple[str, ...]:
    """Every structural way this proposal departs from what was asked for.

    Empty means the proposal does exactly what the initial approval already
    showed the human, and it rides that approval. Anything else needs the card.
    """
    flags = []
    if proposal.action != requested.action:
        flags.append(CHANGED_ACTION)
    target = proposal.target
    if requested.subject_is_authoritative and requested.blob_id:
        if target is None or target.blob_id != requested.blob_id:
            flags.append(CHANGED_SUBJECT)
    elif proposal.action != "CREATE":
        # Nothing the caller said picked this row. A CREATE has no prior
        # subject to have chosen wrongly, so it is not flagged for this.
        flags.append(UNNAMED_SUBJECT)
    if requested.entity_type and proposal.entity_type != requested.entity_type:
        flags.append(CHANGED_SCOPE)
    elif requested.scope and proposal.scope != requested.scope:
        flags.append(CHANGED_SCOPE)
    if (
        proposal.absorbs_another_memory
        or proposal.reclassification is not None
        or proposal.donor is not None
    ):
        flags.append(DESTRUCTIVE_EFFECTS)
    return tuple(flags)


# ─── The card ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FinalMutation:
    """Everything a human needs in order to accept one memory write.

    The complete prose, not a preview of it: a human asked to approve a memory
    change is being asked about the words that will be stored, and a truncated
    card would collect an acceptance for text nobody read. Surfaces that must
    abbreviate for a notification build their own short preview *in addition*
    to this, never instead of it.
    """

    event_id: str
    input_digest: str
    proposal_digest: str
    nonce: str
    action: str
    entity_type: Optional[str]
    scope: Optional[str]
    content: str
    reason: str
    write_set: Tuple[Tuple[str, str, str], ...]
    declared_effects: Tuple[str, ...]
    requested_action: str
    requested_blob_id: Optional[str]
    flags: Tuple[str, ...]
    observation: str
    source: str

    @property
    def why(self) -> Tuple[str, ...]:
        """The flags as sentences, for the human reading the card."""
        return tuple(FLAG_REASONS[flag] for flag in self.flags if flag in FLAG_REASONS)

    def as_card(self) -> Dict[str, Any]:
        """The approval payload, flat enough to cross JSON-RPC unchanged."""
        return {
            "event_id": self.event_id,
            "proposal_digest": self.proposal_digest,
            "acceptance_nonce": self.nonce,
            "action": self.action,
            "entity_type": self.entity_type,
            "scope": self.scope,
            "content": self.content,
            "reason": self.reason,
            "write_set": [
                {"blob_id": bid, "expected_version": version, "role": role}
                for bid, version, role in self.write_set
            ],
            "declared_effects": list(self.declared_effects),
            "requested_action": self.requested_action,
            "requested_blob_id": self.requested_blob_id,
            "flags": list(self.flags),
            "why": list(self.why),
            "observation": self.observation,
            "source": self.source,
        }


def final_mutation(
    event: MemoryEvent,
    proposal: Proposal,
    requested: RequestedWrite,
    flags: Tuple[str, ...],
) -> FinalMutation:
    """Build the card for one flagged proposal, with a fresh single-use nonce."""
    digest = proposal_digest(proposal)
    if digest is None:  # pragma: no cover - a proposal always digests
        raise MnemonicContractError("a final mutation needs a proposal to bind to")
    return FinalMutation(
        event_id=event.event_id,
        input_digest=input_digest(event),
        proposal_digest=digest,
        nonce=secrets.token_urlsafe(24),
        action=proposal.action,
        entity_type=proposal.entity_type,
        scope=proposal.scope,
        content=proposal.content,
        reason=proposal.reason,
        write_set=tuple((t.blob_id, t.expected_version, t.role) for t in proposal.write_set),
        declared_effects=tuple(proposal.declared_effects),
        requested_action=requested.action,
        requested_blob_id=requested.blob_id,
        flags=flags,
        observation=event.observation,
        source=f"{event.source_kind}:{event.source_id}",
    )


# ─── The answer ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Acceptance:
    """One surface's answer to one card.

    ``accepted`` is necessary and not sufficient: :func:`verify` also requires
    the nonce and the proposal digest, so an auto-approver that can only say
    "yes" is refused without the harness having to recognize it.
    """

    accepted: bool
    nonce: str = ""
    proposal_digest: str = ""
    reason: str = ""
    edited: bool = False

    @classmethod
    def declined(cls, reason: str) -> "Acceptance":
        return cls(accepted=False, reason=reason)

    @classmethod
    def granted(cls, nonce: str, digest: str) -> "Acceptance":
        return cls(accepted=True, nonce=nonce, proposal_digest=digest)

    @classmethod
    def from_payload(cls, payload: Optional[Dict[str, Any]]) -> "Acceptance":
        """Read an acceptance out of whatever a surface echoed back.

        A surface that answered only "approved" produces an acceptance with no
        nonce, which :func:`verify` refuses. That is deliberate: the shortcut
        paths all answer exactly that way.
        """
        data = payload or {}
        return cls(
            accepted=True,
            nonce=str(data.get("acceptance_nonce") or ""),
            proposal_digest=str(data.get("proposal_digest") or ""),
            edited=bool(data.get("edited")),
        )


NO_CHANNEL = (
    "this memory change needs a human acceptance and this caller offers no "
    "approval channel, so nothing was written; run it from a surface that can "
    "confirm the final change"
)
NOT_ACCEPTED = "the memory change was not accepted, so nothing was written"
STALE_ACCEPTANCE = (
    "the acceptance does not name the change that was about to be written "
    "(the proposal or the version it read has moved since), so nothing was "
    "written and a fresh acceptance is needed"
)
AUTO_APPROVED = (
    "this memory change was auto-approved by a standing grant rather than "
    "accepted for what it actually does, so nothing was written; a changed "
    "final mutation needs an explicit acceptance of the change itself"
)
EDITED = (
    "the change was revised in the approval card, so the accepted text is no "
    "longer the one that was decided; nothing was written and the revision "
    "needs to be submitted as its own instruction"
)


def verify(acceptance: Optional[Acceptance], mutation: FinalMutation) -> Optional[str]:
    """``None`` when this acceptance authorizes this exact mutation, else why not.

    Ordered so the most informative refusal wins: a surface that said yes with
    no nonce is a standing grant and is told so, rather than being told its
    digest is stale.

    Never raises. The values compared arrived from a client, so they can be any
    string at all — and ``secrets.compare_digest`` raises ``TypeError`` on a
    non-ASCII one. Letting that escape would turn a malformed acceptance into a
    ``retryable_failure`` and a ``failed`` journal row, which says "try again"
    about something that will never succeed; it is a refusal, and it says so.
    """
    if acceptance is None:
        return NO_CHANNEL
    if not acceptance.accepted:
        return acceptance.reason or NOT_ACCEPTED
    if acceptance.edited:
        return EDITED
    if not acceptance.nonce and not acceptance.proposal_digest:
        return AUTO_APPROVED
    if not _same(acceptance.nonce, mutation.nonce):
        return STALE_ACCEPTANCE
    if not _same(acceptance.proposal_digest, mutation.proposal_digest):
        return STALE_ACCEPTANCE
    return None


def _same(given: str, expected: str) -> bool:
    """Constant-time equality that treats an uncomparable value as unequal."""
    try:
        return secrets.compare_digest(given, expected)
    except (TypeError, ValueError):
        logger.info("[mnemonic] acceptance carried an uncomparable value; refusing")
        return False


# ─── The channel ──────────────────────────────────────────────────────


class ApprovalChannel(Protocol):
    """A route from the harness to whoever may accept a memory change.

    Synchronous on purpose: the commit path is synchronous from
    :func:`~zylch.memory.mnemonic.commit.submit` down to the SQLite
    transaction, and an async seam here would have to be bridged at every
    caller instead of once, in the one adapter that knows which event loop it
    belongs to (:mod:`zylch.services.mnemonic_approval`).
    """

    def request(self, mutation: FinalMutation) -> Acceptance:  # pragma: no cover
        ...


_channel: ContextVar[Optional[ApprovalChannel]] = ContextVar(
    "zylch_mnemonic_approval_channel", default=None
)


class _Installed:
    """The handle returned by :func:`install_channel`, for a ``with`` block."""

    __slots__ = ("_token",)

    def __init__(self, token: Any) -> None:
        self._token = token

    def __enter__(self) -> "_Installed":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def close(self) -> None:
        try:
            _channel.reset(self._token)
        except ValueError:
            # Reset from a different context than the one that set it — the
            # variable simply keeps whatever that context holds. Not an error
            # worth raising out of a teardown.
            logger.debug("[mnemonic] approval channel reset outside its own context")


def install_channel(channel: Optional[ApprovalChannel]) -> _Installed:
    """Make ``channel`` the acceptance route for this context and its copies.

    A context var, because the commit path is reached through two thread hops
    that copy the context (``TaskExecutor`` and ``LLMClient`` both use
    ``run_in_executor`` with ``contextvars.copy_context``). Copying carries the
    reference, so the worker thread asks the same human.
    """
    return _Installed(_channel.set(channel))


def current_channel() -> Optional[ApprovalChannel]:
    return _channel.get()


# ─── The gate ─────────────────────────────────────────────────────────


def authorize_mutation(
    event: MemoryEvent,
    proposal: Proposal,
    requested: Optional[RequestedWrite],
) -> Optional[str]:
    """``None`` when this proposal may be written, else why it may not be.

    An unflagged proposal does exactly what the caller's own approved tool call
    described, so it proceeds on that approval. A flagged one is presented in
    full and needs an acceptance that names it.
    """
    if requested is None:
        # No adapter declared what was asked for. The harness cannot tell a
        # faithful proposal from a changed one, so it treats it as changed
        # rather than guessing in the permissive direction.
        requested = RequestedWrite(action=proposal.action)
    flags = flags_for(requested, proposal)
    if not flags:
        return None

    mutation = final_mutation(event, proposal, requested, flags)
    channel = current_channel()
    if channel is None:
        logger.info(
            f"[mnemonic] event={event.event_id} flagged={','.join(flags)} "
            "refused: no approval channel"
        )
        return NO_CHANNEL

    try:
        acceptance = channel.request(mutation)
    except Exception as exc:  # noqa: BLE001 - a gate that cannot ask is a refusal
        logger.warning(f"[mnemonic] approval channel raised for event={event.event_id}: {exc}")
        return f"the approval channel failed, so nothing was written: {exc}"

    refusal = verify(acceptance, mutation)
    if refusal is not None:
        logger.info(
            f"[mnemonic] event={event.event_id} flagged={','.join(flags)} refused: {refusal}"
        )
        return refusal
    logger.info(
        f"[mnemonic] event={event.event_id} flagged={','.join(flags)} accepted "
        f"digest={mutation.proposal_digest[:12]}"
    )
    return None


def describe(mutation: FinalMutation) -> str:
    """The card as text, for a surface that can only show a string."""
    lines = [f"**Memory {mutation.action.lower()}** — confirm the final change"]
    if mutation.why:
        lines.append("")
        lines.append("This is not what the request asked for:")
        lines.extend(f"- {sentence}" for sentence in mutation.why)
    lines.append("")
    if mutation.entity_type:
        scope = f" ({mutation.scope})" if mutation.scope else ""
        lines.append(f"Files as: {mutation.entity_type}{scope}")
    for blob_id, version, role in mutation.write_set:
        lines.append(f"Writes {role}: {blob_id} at version {version}")
    for effect in mutation.declared_effects:
        lines.append(f"Effect: {effect}")
    if mutation.reason:
        lines.append(f"Reason: {mutation.reason}")
    lines.append("")
    lines.append(mutation.content)
    return "\n".join(lines)


__all__ = [
    "AUTO_APPROVED",
    "Acceptance",
    "ApprovalChannel",
    "CHANGED_ACTION",
    "CHANGED_SCOPE",
    "CHANGED_SUBJECT",
    "DESTRUCTIVE_EFFECTS",
    "EDITED",
    "FLAG_REASONS",
    "FinalMutation",
    "NOT_ACCEPTED",
    "NO_CHANNEL",
    "RequestedWrite",
    "STALE_ACCEPTANCE",
    "UNNAMED_SUBJECT",
    "authorize_mutation",
    "current_channel",
    "describe",
    "final_mutation",
    "flags_for",
    "install_channel",
    "verify",
]
