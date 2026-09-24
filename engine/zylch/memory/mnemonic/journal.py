"""Durable state for one semantic memory operation, in the company store.

The decision half of the harness is stateless: submit an event, get a decision.
That is enough until something is actually written, at which point three
questions need answers that survive a crash, a restart and a second process:

- **Was this event already done?** A replayed source must not write the memory
  twice, and a retried event must return what it decided the first time rather
  than pay for a fresh decision.
- **How much may this event still spend?** The per-event dispatch allowance was
  an in-process table in :mod:`~zylch.memory.mnemonic.authorization`. A restart
  reset it, which meant a crash loop could buy the same event a fresh budget
  every time. This column is the durable answer; that table is now a cache
  over it.
- **Who is working on it right now?** Two processes on one company store reach
  the same event through two different profiles. A fenced claim settles it: the
  lease is durable, and the commit re-checks it inside its own transaction. An
  in-memory mutex could not see the other process at all.

It lives in the **company** store, beside the blobs it writes, so the commit
and its receipt are one transaction on one file. Profile-local ``WorkerState``
could not coordinate two profiles sharing a company and swallows persistence
errors besides; ``Blob.events`` could not either, since a donor's receipts
vanish with the donor. Admission, retry limits, backoff and status stay with
``preparation_state`` / ``preparation_attempts``.

**Persistence fails closed.** Every function raises :class:`JournalError` when
the store cannot answer, and the submission facade turns that into a
``retryable_failure``: recording a commit that may not have been recorded is
the one outcome this module must never produce.
"""

from __future__ import annotations

import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from zylch.memory.company_key import COMPANY_FAMILIES
from zylch.storage.models import MemoryOperation

from .contracts import EVENT_DISPATCH_ALLOWANCE, MemoryEvent
from .digests import input_digest, proposal_digest
from .session import JournalError, company_transaction, session_factory
from .proposals import MnemonicResult, PendingEffect, Proposal

PROTOCOL_VERSION = 1

PENDING = "pending"
COMMITTED = "committed"
SKIPPED = "skipped"
REVIEW = "review"
FAILED = "failed"

# A replay of one of these returns the recorded answer instead of deciding
# again. ``failed`` is deliberately absent: a retryable failure is meant to be
# retried, and a review is meant to be resolved explicitly, not re-paid for.
TERMINAL: Tuple[str, ...] = (COMMITTED, SKIPPED, REVIEW)


class EventIdReused(JournalError):
    """This event id already exists carrying different input."""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _target_family(proposal: Optional[Proposal]) -> Optional[str]:
    """Which namespace family this operation writes into, once it is decided.

    ``None`` until a proposal says. It stays ``None`` for an operation that
    never produced one, and :func:`visible` reads that as "not company
    knowledge yet", which is the safe direction: before the role has decided,
    nobody knows whether the payload holds a company fact or one account's
    private rule.
    """
    return proposal.family if proposal is not None and proposal.family else None


def _payload(event: MemoryEvent, proposal: Optional[Proposal]) -> Dict[str, Any]:
    """The bounded, resumable body of an operation.

    Bounded because everything it can hold is already bounded: ``MemoryEvent``
    refuses an observation past ``MAX_OBSERVATION_CHARS`` and a suggestion past
    ``MAX_CONTENT_CHARS``, and ``Proposal`` refuses content past the same cap
    and a write set past ``MAX_WRITE_SET``. There is no second size check here,
    because a second check that cannot fire proves nothing — and the refusal
    that does fire is a refusal, never a truncation: a trimmed observation is a
    different observation, and the operation would then be idempotent against
    something nobody submitted.

    The original instruction is stored only when the source cannot be
    referenced durably — a chat turn the engine does not keep. An email or a
    task has a row of its own; copying its body in here would duplicate it
    under a different retention policy.
    """
    body: Dict[str, Any] = {
        "explicit_request": event.explicit_request,
        "suggestion": event.suggestion,
    }
    if event.source_kind in ("chat", "cli", "rpc"):
        body["observation"] = event.observation
    if proposal is not None:
        body["proposal"] = {
            "action": proposal.action,
            "entity_type": proposal.entity_type,
            "scope": proposal.scope,
            "content": proposal.content,
            "reason": proposal.reason,
            "write_set": [
                {"blob_id": t.blob_id, "expected_version": t.expected_version, "role": t.role}
                for t in proposal.write_set
            ],
            "declared_effects": list(proposal.declared_effects),
        }
    return body


# ─── Opening and replaying ────────────────────────────────────────────


@dataclass(frozen=True)
class Opened:
    """What :func:`open_operation` found or created."""

    event_id: str
    state: str
    allowance: int
    attempts: int
    replay: Optional[MnemonicResult] = None


def open_operation(event: MemoryEvent, *, parent_event_id: Optional[str] = None) -> Opened:
    """Find this event's operation or create it. Never decides anything.

    Returns the recorded terminal result as ``replay`` when the event was
    already answered, so an exactly-once caller writes nothing and pays
    nothing. An id that already exists with a different input digest is
    refused: an id may be replayed, never re-pointed.
    """
    try:
        with company_transaction(write=True) as session:
            row = session.get(MemoryOperation, event.event_id)
            digest = input_digest(event)
            if row is None:
                session.add(
                    MemoryOperation(
                        event_id=event.event_id,
                        owner_id=event.owner_id,
                        company_key=event.company_key,
                        parent_event_id=parent_event_id,
                        protocol_version=PROTOCOL_VERSION,
                        input_digest=digest,
                        source_ref=event.source_ref,
                        origin=event.origin,
                        caller_class=event.caller_class,
                        target_family=_target_family(None),
                        state=PENDING,
                        allowance=EVENT_DISPATCH_ALLOWANCE,
                        attempts=0,
                        payload=_payload(event, None),
                        pending_effects=[],
                        restrictions=[],
                    )
                )
                session.flush()
                return Opened(event.event_id, PENDING, EVENT_DISPATCH_ALLOWANCE, 0)
            if row.input_digest != digest:
                raise EventIdReused(
                    f"event id {event.event_id} already exists with different input"
                )
            if row.company_key != event.company_key or row.owner_id != event.owner_id:
                raise EventIdReused(
                    f"event id {event.event_id} belongs to another account or company"
                )
            replay = _result_from(row) if row.state in TERMINAL else None
            return Opened(
                event.event_id,
                str(row.state),
                int(row.allowance or 0),
                int(row.attempts or 0),
                replay,
            )
    except JournalError:
        raise
    except Exception as exc:  # noqa: BLE001 - persistence failure is a refusal
        raise JournalError(f"operation journal unavailable: {exc}") from exc


def _result_from(row: MemoryOperation) -> MnemonicResult:
    stored = dict(row.result or {})
    outcome = stored.get("outcome") or row.state
    pending = tuple(
        PendingEffect(kind=str(e.get("kind")), detail=str(e.get("detail") or ""))
        for e in (row.pending_effects or [])
    )
    if outcome == COMMITTED:
        return MnemonicResult.committed(
            row.event_id,
            tuple((str(a), str(b)) for a, b in stored.get("committed_ids") or ()),
            pending=pending,
            attempts=int(row.attempts or 0),
        )
    reason = stored.get("reason") or f"recorded {outcome}"
    if outcome == SKIPPED:
        return MnemonicResult.skipped(row.event_id, reason, attempts=int(row.attempts or 0))
    return MnemonicResult.review_needed(row.event_id, reason, attempts=int(row.attempts or 0))


# ─── Fenced claim ─────────────────────────────────────────────────────


def claim(event_id: str) -> Optional[str]:
    """Take the operation for this process. Returns the lease, or ``None``.

    Fenced, not mutexed: the lease is a durable, unguessable value in the row,
    so a second attempt on another process (or after a restart) takes it over
    cleanly and the first one's later write is rejected by :func:`owns`.
    ``None`` means the operation is already terminal and there is nothing to
    work on.
    """
    lease = f"{os.getpid()}:{uuid.uuid4().hex[:8]}:{secrets.token_hex(4)}"
    try:
        with company_transaction(write=True) as session:
            row = session.get(MemoryOperation, event_id)
            if row is None:
                raise JournalError(f"no operation for event {event_id}")
            if row.state in TERMINAL:
                return None
            row.lease = lease
            row.updated_at = _now()
            session.flush()
            return lease
    except JournalError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise JournalError(f"operation journal unavailable: {exc}") from exc


def owns(session: Session, event_id: str, lease: str) -> MemoryOperation:
    """The operation row, if ``lease`` is still the current holder.

    Called inside the commit's own transaction, immediately before the write:
    a process that was superseded while a model was thinking finds out here
    rather than by overwriting the winner's work.
    """
    row = session.get(MemoryOperation, event_id)
    if row is None:
        raise JournalError(f"no operation for event {event_id}")
    if row.lease != lease:
        raise JournalError("another attempt took over this operation")
    if row.state in TERMINAL:
        raise JournalError(f"operation is already {row.state}")
    return row


# ─── The durable allowance ────────────────────────────────────────────


def allowance_for(event_id: str) -> Optional[int]:
    """Paid calls still owed to this event, or ``None`` when nothing durable governs it.

    ``None`` is not zero and not unlimited. It means either that no company
    store is attached, or that this event was never opened as an operation — a
    decision made outside a commit-capable path — and the in-process bound in
    ``authorization`` governs it alone. A journal that exists but cannot answer
    raises instead: silently reporting "no durable limit" for a store that is
    merely broken would hand the event a fresh budget.
    """
    try:
        factory = session_factory()
    except JournalError:
        return None
    session = factory()
    try:
        row = session.get(MemoryOperation, event_id)
        return None if row is None else int(row.allowance or 0)
    except Exception as exc:  # noqa: BLE001
        raise JournalError(f"operation journal unavailable: {exc}") from exc
    finally:
        session.close()


def spend_allowance(event_id: str) -> Optional[int]:
    """Durably consume one paid call. Returns what is left, or ``None``.

    Written before the request reaches a provider, so a crash mid-dispatch
    leaves the call counted rather than free. That is the deliberate direction
    of the error: an uncertain call costs the event one attempt.
    """
    try:
        session_factory()
    except JournalError:
        return None
    try:
        with company_transaction(write=True) as session:
            row = session.get(MemoryOperation, event_id)
            if row is None:
                return None
            remaining = max(0, int(row.allowance or 0) - 1)
            row.allowance = remaining
            row.updated_at = _now()
            session.flush()
            return remaining
    except Exception as exc:  # noqa: BLE001
        raise JournalError(f"operation journal unavailable: {exc}") from exc


# ─── Recording progress and outcomes ──────────────────────────────────


def record_attempt(event_id: str, event: MemoryEvent, proposal: Optional[Proposal]) -> None:
    """Persist the current proposal and bump the durable attempt count."""
    try:
        with company_transaction(write=True) as session:
            row = session.get(MemoryOperation, event_id)
            if row is None:
                raise JournalError(f"no operation for event {event_id}")
            row.attempts = int(row.attempts or 0) + 1
            row.proposal_digest = proposal_digest(proposal)
            row.target_family = _target_family(proposal)
            row.payload = _payload(event, proposal)
            row.updated_at = _now()
            session.flush()
    except JournalError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise JournalError(f"operation journal unavailable: {exc}") from exc


def receipt(
    session: Session,
    row: MemoryOperation,
    *,
    result: MnemonicResult,
    state: str,
    proposal: Optional[Proposal] = None,
    restrictions: Sequence[Dict[str, Any]] = (),
) -> None:
    """Write the operation's outcome INTO the caller's transaction.

    The commit calls this with the same session that wrote the blob, so the
    memory and the receipt that says it exists cannot disagree. Terminal
    states prune the payload down to a minimal idempotency receipt: the
    digests stay so a replay is still recognized, the bodies go.

    ``restrictions`` are the read restrictions a review records against exact
    blob identities and observed versions — a FACT the role declined to treat
    as company knowledge. They survive the pruning, and recording one bumps
    the store's mutation sequence in this same transaction, so every process's
    vector index learns that a row it holds is no longer eligible.
    """
    row.state = state
    row.result = {
        "outcome": result.outcome,
        "reason": result.reason,
        "committed_ids": [list(pair) for pair in result.committed_ids],
    }
    row.pending_effects = [{"kind": e.kind, "detail": e.detail} for e in result.pending_effects]
    row.departure = result.departure
    if proposal is not None:
        row.proposal_digest = proposal_digest(proposal)
    if restrictions:
        row.restrictions = [dict(entry) for entry in restrictions]
        from zylch.memory.store import bump_mutation_seq

        bump_mutation_seq(session)
    if state in TERMINAL:
        row.payload = None
        row.lease = None
    row.updated_at = _now()
    session.flush()


def record_result(
    event_id: str,
    result: MnemonicResult,
    *,
    state: str,
    proposal: Optional[Proposal] = None,
    restrictions: Sequence[Dict[str, Any]] = (),
) -> None:
    """Standalone form of :func:`receipt`, for an outcome with no write."""
    try:
        with company_transaction(write=True) as session:
            row = session.get(MemoryOperation, event_id)
            if row is None:
                raise JournalError(f"no operation for event {event_id}")
            receipt(
                session,
                row,
                result=result,
                state=state,
                proposal=proposal,
                restrictions=restrictions,
            )
    except JournalError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise JournalError(f"operation journal unavailable: {exc}") from exc


# ─── Read restrictions recorded by reviews ────────────────────────────


def restrictions_for() -> list:
    """Every read restriction recorded by a review in this company store.

    Read by the eligibility predicate, which is why it lives here beside the
    rows that carry it: a restriction is journal state, and the read paths
    consult it rather than a marker written onto the blob.
    """
    try:
        with company_transaction() as session:
            rows = (
                session.query(MemoryOperation.restrictions)
                .filter(MemoryOperation.state == REVIEW)
                .all()
            )
            found = []
            for (entries,) in rows:
                for entry in entries or []:
                    if isinstance(entry, dict) and entry.get("blob_id"):
                        found.append(dict(entry))
            return found
    except Exception as exc:  # noqa: BLE001
        raise JournalError(f"operation journal unavailable: {exc}") from exc


# ─── Reading, scoped like the memory it describes ─────────────────────


def visible(row: MemoryOperation, owner_id: str, company_key: str) -> bool:
    """May this account read this operation?

    The same wall ``memory/scope.blob_visible`` puts around a blob, hung the
    other way round. A blob defaults to visible and rule namespaces are carved
    out of it; an operation defaults to **private to its submitter** and only a
    decided company-family target opens it to the rest of the company.

    The asymmetry is the payload. A blob's content is already the committed
    memory; an operation carries the raw observation that produced it, and
    until the role has said which family it belongs to, nothing knows whether
    that text is company knowledge or one account's private correction.
    """
    if row.company_key != company_key:
        return False
    if row.owner_id == owner_id:
        return True
    return (row.target_family or "") in COMPANY_FAMILIES


def read(event_id: str, *, owner_id: str, company_key: str) -> Optional[Dict[str, Any]]:
    """One operation as a dict, or ``None`` when absent or not visible."""
    try:
        with company_transaction() as session:
            row = session.get(MemoryOperation, event_id)
            if row is None or not visible(row, owner_id, company_key):
                return None
            return row.to_dict()
    except Exception as exc:  # noqa: BLE001
        raise JournalError(f"operation journal unavailable: {exc}") from exc


__all__ = [
    "COMMITTED",
    "FAILED",
    "PENDING",
    "PROTOCOL_VERSION",
    "REVIEW",
    "SKIPPED",
    "TERMINAL",
    "EventIdReused",
    "JournalError",
    "Opened",
    "allowance_for",
    "claim",
    "company_transaction",
    "input_digest",
    "open_operation",
    "owns",
    "proposal_digest",
    "read",
    "receipt",
    "record_attempt",
    "record_result",
    "restrictions_for",
    "session_factory",
    "spend_allowance",
    "visible",
]
