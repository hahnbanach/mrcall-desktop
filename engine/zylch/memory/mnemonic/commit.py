"""The only production path from a validated proposal to written memory.

:func:`submit` is the whole public surface of the harness. A caller hands in a
:class:`~zylch.memory.mnemonic.contracts.MemoryEvent` and gets back one
:class:`~zylch.memory.mnemonic.proposals.MnemonicResult`. It never receives a
session, a permit, a writer or a commit function — those exist only inside this
module, which is what makes "the semantic write boundary" a boundary rather
than a convention.

What one commit is:

- embeddings computed **before** the transaction, so an embedding failure is a
  refusal that never opened one, and no other writer queues behind a model;
- the company write lock taken as the transaction's first statement, and every
  visible target re-read and re-version-checked under it — not against the
  version a model saw while it was thinking;
- blob, sentences, identifier index, source link, mutation sequence and the
  operation receipt written in **one transaction on one file** — the company
  store. The session is bound to that engine alone, so a stray profile-table
  statement has nowhere to go instead of quietly committing a second
  transaction inside an operation that calls itself atomic.

A proposal that departed from what the caller asked for — a different action,
a different subject, a different scope, or an effect that absorbs another memory
— is committed like any other, with the departure **recorded** in the operation
receipt and returned to the caller (:mod:`zylch.memory.mnemonic.approval`).
Nothing asks a human at write time: what protects the memory is that the
rewrite retained the text it replaced, and that the record says who chose what.

What it is not yet: MERGE and reclassification return ``review_needed`` until
the milestones that own them arrive. They are refused here rather than
approximated, because an UPDATE standing in for a merge is precisely the
failure this harness exists to remove.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence, Tuple

from zylch.memory.commit_permit import (
    ConflictError,
    PermitError,
    abandon_permit,
    issue_commit_permit,
)
from zylch.memory.company_key import scoped_namespace

from . import journal
from .agent import decide
from .approval import RequestedWrite, departure_for
from .authorization import MnemonicRefusal, authorize_request
from .contracts import CREATE, MAX_DECISION_ATTEMPTS, MERGE, UPDATE, MemoryEvent
from .wiring import (
    CommitContext,
    candidates_for,
    default_context,
    parse_identifiers_block,
)
from .proposals import MnemonicResult, Proposal

logger = logging.getLogger(__name__)

# Written into the blob's event log so a human reading a memory can see which
# operation produced it. Bounded and id-only: never the observation.
EVENT_NOTE = "mnemonic operation {event_id}"

MERGE_NOT_READY = "merging two memories is not installed yet; the proposal is recorded for review"
RECLASSIFY_NOT_READY = (
    "moving a memory between families is not installed yet; " "the proposal is recorded for review"
)


# ─── The facade ───────────────────────────────────────────────────────


def submit(
    event: MemoryEvent,
    *,
    client: Any = None,
    context: Optional[CommitContext] = None,
    allow_actions: Sequence[str] = (CREATE, UPDATE),
    parent_event_id: Optional[str] = None,
    requested: Optional[RequestedWrite] = None,
) -> MnemonicResult:
    """Decide and commit one memory event, exactly once.

    ``allow_actions`` narrows the slice a caller is ready for. A path that
    passes ``(CREATE,)`` refuses a proposal to modify existing memory outright,
    rather than falling back to a legacy direct write — that would be the
    harness writing around itself.

    ``requested`` is what the calling tool's own arguments asked for, the
    baseline a committed proposal's departure is recorded against. An adapter
    that supplies none records no departure: with nothing to compare against
    there is none to name, and a false flag in the journal is worse than an
    absent one.

    It **returns a result; it does not raise.** Callers are tools that owe
    their own caller an answer, and an exception escaping here would say
    nothing about whether memory changed. ``KeyboardInterrupt`` still
    propagates: that is the process going away, not an outcome.
    """
    try:
        return _submit(event, client, context, allow_actions, parent_event_id, requested)
    except Exception as exc:  # noqa: BLE001 - the public surface owes an answer
        logger.exception(f"[mnemonic] submit failed event={event.event_id}: {exc!r}")
        return MnemonicResult.retryable_failure(
            event.event_id, f"the semantic write path failed: {exc}"
        )


def _submit(
    event: MemoryEvent,
    client: Any,
    context: Optional[CommitContext],
    allow_actions: Sequence[str],
    parent_event_id: Optional[str],
    requested: Optional[RequestedWrite],
) -> MnemonicResult:
    try:
        opened = journal.open_operation(event, parent_event_id=parent_event_id)
    except journal.EventIdReused as exc:
        return MnemonicResult.review_needed(event.event_id, str(exc))
    except journal.JournalError as exc:
        return MnemonicResult.retryable_failure(event.event_id, str(exc))

    if opened.replay is not None:
        logger.info(f"[mnemonic] replayed event={event.event_id} outcome={opened.replay.outcome}")
        return opened.replay

    context = context or default_context(event.owner_id)
    try:
        lease = journal.claim(event.event_id)
    except journal.JournalError as exc:
        return MnemonicResult.retryable_failure(event.event_id, str(exc))
    if lease is None:
        # Settled between opening and claiming — another attempt, another
        # process. Re-read rather than decide: the answer already exists.
        try:
            replayed = journal.open_operation(event).replay
        except journal.JournalError as exc:
            return MnemonicResult.retryable_failure(event.event_id, str(exc))
        return replayed or MnemonicResult.review_needed(
            event.event_id, "another attempt already settled this event"
        )

    return _decide_and_commit(event, lease, client, context, allow_actions, requested)


def _decide_and_commit(
    event: MemoryEvent,
    lease: str,
    client: Any,
    context: CommitContext,
    allow_actions: Sequence[str],
    requested: Optional[RequestedWrite] = None,
) -> MnemonicResult:
    """At most :data:`MAX_DECISION_ATTEMPTS` decide → commit rounds.

    A CAS conflict re-reads the candidates and re-decides — each round paying
    its own ordinary reservation out of the event's durable allowance. It never
    falls through to CREATE, and an event that runs out of rounds becomes a
    visible ``review_needed`` rather than a silent retry loop.
    """
    result: Optional[MnemonicResult] = None
    for attempt in range(MAX_DECISION_ATTEMPTS):
        candidates = candidates_for(event, context)
        try:
            decision = decide(event, candidates, client=client)
        except journal.JournalError as exc:
            # The durable allowance is spent at the client boundary, so a
            # journal that stops answering surfaces here, mid-dispatch.
            return MnemonicResult.retryable_failure(event.event_id, str(exc))
        try:
            journal.record_attempt(event.event_id, event, decision.proposal)
        except journal.JournalError as exc:
            return MnemonicResult.retryable_failure(event.event_id, str(exc))

        proposal = decision.proposal
        if not decision.accepted or proposal is None:
            # Everything the role settles itself arrives with a result. The
            # fallback is not decoration: a future change that returned an
            # unaccepted decision without one must still produce a result here,
            # never an exception where a caller expects an answer.
            settled = decision.result or MnemonicResult.review_needed(
                event.event_id, "the decision round produced no usable answer"
            )
            return _settle(event, settled, proposal)

        refusal = _unsupported(proposal, allow_actions)
        if refusal:
            return _settle(
                event,
                MnemonicResult.review_needed(
                    event.event_id, refusal, proposal=proposal, attempts=decision.attempts
                ),
                proposal,
            )

        # Recorded per round, because a CAS conflict re-decides and the new
        # proposal may depart differently from the request than the last one.
        departure = departure_for(requested, proposal)

        try:
            return _commit(
                event, proposal, lease, context, attempts=decision.attempts, departure=departure
            )
        except ConflictError as exc:
            logger.info(f"[mnemonic] CAS conflict event={event.event_id} round={attempt + 1}")
            result = MnemonicResult.review_needed(
                event.event_id, f"target changed while deciding: {exc}", proposal=proposal
            )
            continue
        except MnemonicRefusal as exc:
            return _settle(
                event,
                MnemonicResult.review_needed(event.event_id, str(exc), proposal=proposal),
                proposal,
            )
        except PermitError as exc:
            logger.error(f"[mnemonic] refused at the storage boundary event={event.event_id}")
            return _settle(
                event,
                MnemonicResult.review_needed(
                    event.event_id, f"write authority refused: {exc}", proposal=proposal
                ),
                proposal,
            )
        except journal.JournalError as exc:
            # Losing the lease is not a failure of the event. Another attempt
            # — another process — took it over, and if it has already answered,
            # that answer is this caller's answer too. Reporting a failure here
            # would say no commit occurred while the memory sits committed.
            settled = _settled_elsewhere(event)
            if settled is not None:
                return settled
            return MnemonicResult.retryable_failure(event.event_id, str(exc))
        except Exception as exc:  # noqa: BLE001 - a failed write is a retry, never a claim
            logger.error(f"[mnemonic] commit failed event={event.event_id}: {exc}")
            return _record_failure(event, f"commit failed: {exc}", proposal)

    return _settle(
        event,
        result
        or MnemonicResult.review_needed(
            event.event_id, "the target kept changing; no decision could be committed"
        ),
        None,
    )


def _settled_elsewhere(event: MemoryEvent) -> Optional[MnemonicResult]:
    """The answer another attempt recorded, if it has already finished.

    ``None`` covers both "still in flight" and "the journal cannot say", which
    the caller treats alike: it did not commit, and it may try again.
    """
    try:
        return journal.open_operation(event).replay
    except journal.JournalError:
        return None


def _unsupported(proposal: Proposal, allow_actions: Sequence[str]) -> str:
    """Why this validated proposal cannot be committed by this milestone."""
    if proposal.reclassification is not None:
        return RECLASSIFY_NOT_READY
    if proposal.action == MERGE:
        return MERGE_NOT_READY
    if proposal.action not in allow_actions:
        return (
            f"this path submits {'/'.join(allow_actions)} only; a {proposal.action} of existing "
            "memory needs the approval step that is not installed yet"
        )
    return ""


def _settle(
    event: MemoryEvent, result: MnemonicResult, proposal: Optional[Proposal]
) -> MnemonicResult:
    """Record a non-committing outcome, keeping the journal authoritative."""
    state = {
        "skipped": journal.SKIPPED,
        "review_needed": journal.REVIEW,
        "retryable_failure": journal.FAILED,
    }.get(result.outcome, journal.FAILED)
    try:
        journal.record_result(event.event_id, result, state=state, proposal=proposal)
    except journal.JournalError as exc:
        return MnemonicResult.retryable_failure(event.event_id, str(exc))
    return result


def _record_failure(
    event: MemoryEvent, reason: str, proposal: Optional[Proposal]
) -> MnemonicResult:
    failure = MnemonicResult.retryable_failure(event.event_id, reason, proposal=proposal)
    return _settle(event, failure, proposal)


# ─── The transaction ──────────────────────────────────────────────────


def _commit(
    event: MemoryEvent,
    proposal: Proposal,
    lease: str,
    context: CommitContext,
    *,
    attempts: int,
    departure=None,
) -> MnemonicResult:
    """Write one validated proposal, or write nothing at all."""
    namespace = scoped_namespace(proposal.family or "", event.owner_id, event.company_key)
    # Outside the transaction on purpose: encoding is seconds of CPU and can
    # fail, and neither should happen while holding the company write lock.
    prepared = context.storage.prepare(proposal.content)

    target = proposal.target
    permit = issue_commit_permit(
        action=proposal.action,
        company_key=event.company_key,
        owner_id=event.owner_id,
        event_id=event.event_id,
        proposal_digest=journal.proposal_digest(proposal) or "",
        content=proposal.content,
        namespace=namespace,
        write_set=(
            () if proposal.action == CREATE else ((target.blob_id, target.expected_version),)
        ),
    )

    committed_ids: Tuple[Tuple[str, str], ...]
    try:
        with journal.company_transaction(write=True) as session:
            row = journal.owns(session, event.event_id, lease)
            # Authorization is re-checked under the lock, not trusted from the
            # door: a turn cancelled or a policy flipped while the model was
            # thinking must stop the write, not merely the next dispatch.
            authorize_request(event)

            if proposal.action == CREATE:
                blob = context.storage.semantic_create(
                    session,
                    permit,
                    owner_id=event.owner_id,
                    namespace=namespace,
                    prepared=prepared,
                    event_description=EVENT_NOTE.format(event_id=event.event_id),
                )
            else:
                blob = _update(session, event, proposal, permit, prepared, context)

            blob_id = str(blob["id"])
            _write_indexes(session, event, blob_id, proposal)
            context.storage.mark_mutated(session)
            committed_ids = ((blob_id, str(blob.get("updated_at") or "")),)
            journal.receipt(
                session,
                row,
                result=MnemonicResult.committed(
                    event.event_id,
                    committed_ids,
                    proposal=proposal,
                    attempts=attempts,
                    departure=departure,
                ),
                state=journal.COMMITTED,
                proposal=proposal,
            )
    except Exception:
        abandon_permit(permit)
        raise

    logger.info(
        f"[mnemonic] committed event={event.event_id} action={proposal.action} "
        f"type={proposal.entity_type} blob={blob_id} attempts={attempts}"
    )
    # The invalidation callback is a same-process fast path; the mutation
    # sequence written above is what every OTHER engine on this store reads.
    return MnemonicResult.committed(
        event.event_id, committed_ids, proposal=proposal, attempts=attempts, departure=departure
    )


def _update(session, event, proposal, permit, prepared, context):
    """Re-read the target under the lock, then rewrite it at its exact version."""
    target = proposal.target
    live = context.storage.visible_target(session, target.blob_id, event.owner_id)
    if live is None:
        raise ConflictError(
            f"blob {target.blob_id} is no longer visible to this account; refusing the update"
        )
    return context.storage.semantic_update(
        session,
        permit,
        blob=live,
        owner_id=event.owner_id,
        prepared=prepared,
        expected_version=target.expected_version,
        event_description=EVENT_NOTE.format(event_id=event.event_id),
    )


def _write_indexes(session, event: MemoryEvent, blob_id: str, proposal: Proposal) -> None:
    """Identity index and source link — inside the same transaction as the blob.

    An UPDATE **replaces** the blob's identifier rows rather than adding to
    them. The old writer only appended, so correcting an email address left the
    wrong one in the index and the next cross-channel lookup still matched it.
    """
    from zylch.memory import associations

    identifiers = associations.identifiers_from(parse_identifiers_block(proposal.content))
    if proposal.action == UPDATE:
        associations.drop_identifiers(session, blob_id=blob_id, company_key=event.company_key)
    if identifiers:
        associations.add_identifiers(
            session,
            owner_id=event.owner_id,
            blob_id=blob_id,
            identifiers=identifiers,
            company_key=event.company_key,
        )
    associations.link_source(
        session,
        source_kind=event.source_kind,
        source_id=event.source_id,
        blob_id=blob_id,
        owner_id=event.owner_id,
    )


__all__ = [
    "CommitContext",
    "MERGE_NOT_READY",
    "RECLASSIFY_NOT_READY",
    "candidates_for",
    "default_context",
    "submit",
]
