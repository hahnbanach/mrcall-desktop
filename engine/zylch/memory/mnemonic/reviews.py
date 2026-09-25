"""The owner's resolution of what the harness parked: list, dismiss, retry.

A review is terminal: the same account re-submitting the same source or pair
replays it rather than deciding again, so a parked source never lands its
checkpoint and a parked pair is never decided until someone resolves it. A
``failed`` or ``pending`` row that nothing resubmits — a chat turn — stays
unsettled for good. Both block a company-memory join. This module is how the
owner settles them, on the engine CLI only (``zylch memory-reviews``); no RPC
method reaches it.

:func:`list_unsettled` answers this profile's rows — either identity of the
profile, as :func:`~zylch.memory.mnemonic.authorization._current_owners`
answers it — in ``review``, ``failed`` or ``pending``, each with the actions it
admits. :func:`resolve` applies one action to one such row, in one company
write transaction under the write lock, after
:func:`~zylch.memory.mnemonic.fence.refuse_if_fenced`: a fenced company, a row
of another account or company, and a row already settled are refused with
:class:`ReviewRefused`.

- **dismiss** — any unsettled row. It becomes ``skipped`` with the reason
  :data:`DISMISSED`, its payload (a manifest included) and lease are dropped and
  its ``proposal_digest`` is cleared: a dismissal is the owner declining to act,
  not the role's decision, so a dismissed pair settles nothing for another
  account (``pairs.settled``). A child's parent is then re-aggregated in the
  same transaction from its children's recorded states by
  :func:`~zylch.memory.mnemonic.ingestion.parent_settlement`, the rule the
  ingestion loop settles a parent by: once no child is unsettled the parent
  settles ``committed`` or ``skipped`` and its manifest is pruned, so the next
  worker run replays it and lands the source's checkpoint with no paid call and
  no extraction. A leased row being worked elsewhere is safe to dismiss: its
  commit's ``journal.owns`` finds it terminal, and ``journal.receipt`` and
  ``journal.record_attempt`` refuse a terminal row.
- **retry** — a row in ``review`` whose next submission can decide it again:
  an ingested source's parent reviewed before it had any child (it extracts
  again, paid, under ordinary admission), a consolidation pair, and a child
  whose parent kept its manifest (the parent is reopened too, so the next
  worker run resumes the manifest, replays the settled siblings and decides
  that child). The row becomes ``failed`` with its allowance reset to
  ``EVENT_DISPATCH_ALLOWANCE``. Every other row is refused — a chat, CLI or
  RPC event, which nothing resubmits, and a child whose parent's manifest was
  pruned, which could only extract again and collide with its recorded
  children — and is dismissed instead.

Both actions keep a row's restrictions, whatever it becomes: a restricted FACT
stays ineligible. This is the one sanctioned way a terminal row changes; the
journal's own writers refuse one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from zylch.storage.models import MemoryOperation

from . import journal
from .contracts import EVENT_DISPATCH_ALLOWANCE, RETRYABLE_FAILURE
from .fence import CompanyFenced, refuse_if_fenced
from .proposals import MnemonicResult
from .session import JournalError, company_transaction

DISMISS = "dismiss"
RETRY = "retry"
ACTIONS: Tuple[str, ...] = (DISMISS, RETRY)

UNSETTLED: Tuple[str, ...] = (journal.REVIEW, journal.FAILED, journal.PENDING)
SETTLED: Tuple[str, ...] = (journal.COMMITTED, journal.SKIPPED)

DISMISSED = "dismissed by owner"
RETRIED = "retried by owner"
CHILD_RETRIED = "a child was retried by owner"

INTERACTIVE_KINDS: Tuple[str, ...] = ("chat", "cli", "rpc")


class ReviewRefused(RuntimeError):
    """This row may not be resolved this way; the reason says why."""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _owners() -> frozenset:
    from .authorization import _current_owners

    return _current_owners()


def source_kind(row: MemoryOperation) -> str:
    """The event's source kind, as its ``source_ref`` (``kind:id@revision``) names it."""
    return str(row.source_ref or "").split(":", 1)[0]


def _children(session: Session, parent_id: str) -> List[MemoryOperation]:
    rows = (
        session.query(MemoryOperation)
        .filter(MemoryOperation.parent_event_id == parent_id)
        .all()
    )
    return sorted(rows, key=lambda r: _child_index(str(r.event_id)))


def _child_index(event_id: str) -> Tuple[int, str]:
    tail = event_id.rsplit(":", 1)[-1]
    return (int(tail), event_id) if tail.isdigit() else (1 << 30, event_id)


def _has_manifest(row: Optional[MemoryOperation]) -> bool:
    return row is not None and isinstance(dict(row.payload or {}).get("manifest"), list)


# ─── What a row admits ────────────────────────────────────────────────


def retry_refusal(session: Session, row: MemoryOperation) -> str:
    """Why ``row`` may not be retried, or ``""`` when it may."""
    from .ingestion import PARENT_ID_PREFIX, SOURCE_KINDS
    from .pairs import PAIR_SOURCE_KIND

    if row.state != journal.REVIEW:
        return (
            f"only a review is retried; a {row.state} row is taken up again by the next run"
            if row.state in UNSETTLED
            else f"operation {row.event_id} is already {row.state}"
        )
    kind = source_kind(row)
    if kind in INTERACTIVE_KINDS:
        return f"nothing resubmits a {kind} event, so a retry would never run; dismiss it"
    if row.parent_event_id:
        parent = session.get(MemoryOperation, row.parent_event_id)
        if not _has_manifest(parent):
            return (
                "its parent kept no extraction manifest, so the child could only be "
                "extracted again and collide with its recorded siblings; dismiss it"
            )
        return ""
    if kind == PAIR_SOURCE_KIND:
        return ""
    if kind in SOURCE_KINDS and str(row.event_id).startswith(PARENT_ID_PREFIX):
        if _children(session, str(row.event_id)):
            return (
                "this source's children are decided on their own; retry or dismiss "
                "the reviewed child instead"
            )
        return ""
    return "nothing resubmits this event, so a retry would never run; dismiss it"


def _actions(session: Session, row: MemoryOperation) -> Tuple[str, ...]:
    return (DISMISS, RETRY) if not retry_refusal(session, row) else (DISMISS,)


def _entry(session: Session, row: MemoryOperation) -> Dict[str, Any]:
    return {
        "event_id": str(row.event_id),
        "state": str(row.state),
        "source_ref": str(row.source_ref or ""),
        "parent_event_id": row.parent_event_id,
        "reason": str(dict(row.result or {}).get("reason") or ""),
        "restrictions": [dict(r) for r in (row.restrictions or [])],
        "actions": list(_actions(session, row)),
    }


# ─── Listing ──────────────────────────────────────────────────────────


def list_unsettled(company_key: str) -> List[Dict[str, Any]]:
    """This profile's unsettled rows in ``company_key``, oldest first.

    Owned by either identity of the profile; another account's rows are never
    listed. A process that cannot say which account it is lists nothing.
    Raises :class:`JournalError` when the store cannot answer.
    """
    owners = _owners()
    if not owners or not company_key:
        return []
    try:
        with company_transaction() as session:
            rows = (
                session.query(MemoryOperation)
                .filter(
                    MemoryOperation.company_key == company_key,
                    MemoryOperation.owner_id.in_(sorted(owners)),
                    MemoryOperation.state.in_(UNSETTLED),
                )
                .order_by(MemoryOperation.created_at, MemoryOperation.event_id)
                .all()
            )
            return [_entry(session, row) for row in rows]
    except JournalError:
        raise
    except Exception as exc:  # noqa: BLE001 - a journal that cannot answer lists nothing
        raise JournalError(f"operation journal unavailable: {exc}") from exc


# ─── Resolving ────────────────────────────────────────────────────────


def resolve(event_id: str, action: str) -> Dict[str, Any]:
    """Apply ``action`` (:data:`DISMISS` or :data:`RETRY`) to one unsettled row.

    Answers the row's new state and, for a child, its parent's. Raises
    :class:`ReviewRefused` for a fenced company, a row that is not this
    profile's, not in the bound company or not unsettled, and a retry the row
    does not admit; nothing is written then. Raises :class:`JournalError` when
    the store cannot answer.
    """
    from zylch.memory.company_key import current_company_key

    if action not in ACTIONS:
        raise ReviewRefused(f"unknown action {action!r}; one of {', '.join(ACTIONS)}")
    company_key = current_company_key()
    if not company_key:
        raise ReviewRefused("this profile is bound to no company memory")
    owners = _owners()
    if not owners:
        raise ReviewRefused("this process cannot say which account it is acting as")
    try:
        with company_transaction(write=True) as session:
            try:
                refuse_if_fenced(session, company_key)
            except CompanyFenced as exc:
                raise ReviewRefused(str(exc)) from exc
            row = session.get(MemoryOperation, event_id)
            if row is None or row.company_key != company_key or row.owner_id not in owners:
                raise ReviewRefused(f"no operation {event_id} of this profile in this company memory")
            if row.state not in UNSETTLED:
                raise ReviewRefused(f"operation {event_id} is already {row.state}")
            if action == DISMISS:
                return _dismiss(session, row)
            return _retry(session, row)
    except (ReviewRefused, JournalError):
        raise
    except Exception as exc:  # noqa: BLE001 - a journal that cannot answer resolves nothing
        raise JournalError(f"operation journal unavailable: {exc}") from exc


def _write(row: MemoryOperation, state: str, result: MnemonicResult) -> None:
    """Settle ``row`` in the caller's transaction: its state, its result, no body, no lease."""
    row.state = state
    row.result = {
        "outcome": result.outcome,
        "reason": result.reason,
        "committed_ids": [list(pair) for pair in result.committed_ids],
    }
    row.payload = None
    row.lease = None
    row.updated_at = _now()


def _dismiss(session: Session, row: MemoryOperation) -> Dict[str, Any]:
    _write(row, journal.SKIPPED, MnemonicResult.skipped(str(row.event_id), DISMISSED))
    row.proposal_digest = None
    session.flush()
    parent = _reaggregate(session, row.parent_event_id) if row.parent_event_id else None
    return _answer(row, DISMISS, parent)


def _reaggregate(session: Session, parent_id: str) -> Optional[MemoryOperation]:
    """Settle the parent once none of its children is unsettled; else leave it."""
    from .ingestion import parent_settlement

    parent = session.get(MemoryOperation, parent_id)
    if parent is None or parent.state in SETTLED:
        return parent
    children = _children(session, parent_id)
    if any(child.state not in SETTLED for child in children):
        return parent
    settles = parent_settlement(parent_id, [journal._result_from(c) for c in children])
    if settles is None:
        return parent
    result, state = settles
    _write(parent, state, result)
    parent.pending_effects = []
    session.flush()
    return parent


def _retry(session: Session, row: MemoryOperation) -> Dict[str, Any]:
    refusal = retry_refusal(session, row)
    if refusal:
        raise ReviewRefused(refusal)
    parent = session.get(MemoryOperation, row.parent_event_id) if row.parent_event_id else None
    _reopen(row, RETRIED)
    row.allowance = EVENT_DISPATCH_ALLOWANCE
    if parent is not None:
        _reopen(parent, CHILD_RETRIED)
    session.flush()
    return _answer(row, RETRY, parent)


def _reopen(row: MemoryOperation, reason: str) -> None:
    """``failed``, lease cleared, restrictions and (for a parent) the manifest kept."""
    row.state = journal.FAILED
    row.result = {"outcome": RETRYABLE_FAILURE, "reason": reason, "committed_ids": []}
    row.lease = None
    row.updated_at = _now()


def _answer(
    row: MemoryOperation, action: str, parent: Optional[MemoryOperation]
) -> Dict[str, Any]:
    return {
        "event_id": str(row.event_id),
        "action": action,
        "state": str(row.state),
        "parent": None
        if parent is None
        else {"event_id": str(parent.event_id), "state": str(parent.state)},
    }


__all__ = [
    "ACTIONS",
    "DISMISS",
    "DISMISSED",
    "RETRY",
    "ReviewRefused",
    "list_unsettled",
    "resolve",
    "retry_refusal",
    "source_kind",
]
