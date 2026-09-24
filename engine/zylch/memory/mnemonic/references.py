"""The recorded follow-up a merge owes the profile that committed it.

A merge drops its donor inside one company transaction, and the alias it
writes there makes the donor's id resolvable at once, for every account. One
reference is left that the company store does not hold: this profile's own task
ledger (``task_items.sources["blobs"]``, a JSON list in the profile's file),
which may still name the donor. Re-pointing it is not part of the memory's
meaning, and it cannot join the company transaction — it lives in another
file — so the commit records it instead, as a pending effect on its receipt
(``task_references``, ``"<donor>-><keeper>"``), and this module applies it.

Three rules keep the follow-up safe:

- **It is recorded before it runs.** The receipt that carries the effect
  commits with the merge, so a crash between the company commit and the ledger
  rewrite leaves the effect on record rather than lost.
- **It runs only where it belongs.** An effect is applied only by the account
  that committed the merge, only while this profile is still bound to the
  company the merge committed in, and only to this process's own profile file.
  Another profile sharing the store is never opened; it resolves the donor
  through the alias, and a profile that has joined another company finds no
  such receipt in its store at all.
- **It is idempotent and takes no ids from its caller.** Applying replaces the
  donor by the keeper in each ledger list that names it — nothing else in the
  row changes — and then removes the effect from the receipt. A crash between
  the two re-applies a rewrite that has nothing left to do. The effects come
  from the journal, never from an argument. The keeper is followed to where it
  lives now, so follow-ups replayed in any order along a chain of merges end
  on the chain's survivor, never on a dropped id.

A failure leaves the effect recorded: the merge stays the authoritative
``committed``, with the effect in ``pending_effects``, and the next
consolidation run replays it (:func:`replay_pending`). A follow-up is never
reported done that did not run: a receipt this process cannot read counts as
still pending, and a journal that cannot list the pending follow-ups is an
error, not "none".
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Dict, List, Optional, Tuple

from zylch.memory.company_key import current_company_key
from zylch.storage.models import MemoryOperation

from . import journal
from .pairs import PAIR_SOURCE_KIND
from .proposals import MnemonicResult, PendingEffect
from .writes import TASK_REFERENCES

logger = logging.getLogger(__name__)


def follow_up(result: MnemonicResult, *, owner_id: str) -> MnemonicResult:
    """The committed result, with its recorded follow-up applied where it could be.

    Called by the commit right after its company transaction. What could not be
    applied stays in ``pending_effects`` — the result is ``committed`` either
    way, because the memory is. Nothing raised here may reach the commit's
    failure handling, which would record a failure over a committed receipt:
    a follow-up that raises leaves every effect pending, as recorded.
    """
    try:
        remaining = apply(result.event_id, owner_id=owner_id)
    except Exception as exc:  # noqa: BLE001 - the memory is committed; the effect stays recorded
        logger.warning(f"[references] follow-up of {result.event_id} failed: {exc}")
        remaining = None
    if remaining is None:
        return result
    return dataclasses.replace(result, pending_effects=remaining)


def apply(event_id: str, *, owner_id: str) -> Optional[Tuple[PendingEffect, ...]]:
    """Apply one committed operation's recorded follow-up; return what is left.

    ``None`` when this process cannot tell — the receipt could not be read, or
    it is not in the store this profile is bound to now — and the caller keeps
    the effects it holds as pending. Nothing is applied when the operation
    belongs to another account: those effects are not this process's to
    apply, and they come back as left.
    """
    try:
        row = _row(event_id)
    except journal.JournalError as exc:
        logger.warning(f"[references] cannot read operation {event_id}: {exc}")
        return None
    if row is None:
        return None
    effects = row["effects"]
    if row["owner_id"] != owner_id or row["company_key"] != current_company_key():
        return effects
    applied: List[PendingEffect] = []
    remaining: List[PendingEffect] = []
    for effect in effects:
        if effect.kind != TASK_REFERENCES:
            remaining.append(effect)
            continue
        donor, _, keeper = effect.detail.partition("->")
        try:
            keeper = _survivor(keeper)
            rewritten = _rewrite_ledger(owner_id, donor, keeper)
        except Exception as exc:  # noqa: BLE001 - recorded and replayed, never swallowed
            logger.warning(
                f"[references] ledger follow-up {donor}->{keeper} of {event_id} "
                f"failed and stays recorded: {exc}"
            )
            remaining.append(effect)
            continue
        logger.info(f"[references] re-pointed {rewritten} task(s) {donor}->{keeper} for {event_id}")
        applied.append(effect)
    if applied:
        try:
            _record_remaining(event_id, remaining)
        except journal.JournalError as exc:
            # The ledger is rewritten; the receipt still lists the effect, and
            # the next replay re-applies a rewrite that has nothing left to do.
            logger.warning(f"[references] cannot clear the follow-up of {event_id}: {exc}")
            return effects
    return tuple(remaining)


def replay_pending(owner_id: str) -> Dict[str, int]:
    """Re-apply this account's recorded follow-ups in this company's store.

    Run by consolidation before anything else. Reads the committed merges of
    this owner in the store this profile is bound to now — no ids from any
    caller — and answers how many follow-ups it resolved and how many are still
    pending; one whose receipt cannot be read again counts as pending. Raises
    :class:`~zylch.memory.mnemonic.session.JournalError` when the pending
    follow-ups cannot be listed at all.
    """
    pending = _pending_of(owner_id)
    resolved = left = 0
    for event_id, effects in pending:
        remaining = apply(event_id, owner_id=owner_id)
        if remaining is None:
            remaining = effects
        resolved += len(effects) - len(remaining)
        left += len(remaining)
    return {"references_resolved": resolved, "references_pending": left}


# ─── The journal half ─────────────────────────────────────────────────


def _effects(raw: Any) -> Tuple[PendingEffect, ...]:
    return tuple(
        PendingEffect(kind=str(e.get("kind")), detail=str(e.get("detail") or ""))
        for e in (raw or [])
        if isinstance(e, dict)
    )


def _row(event_id: str) -> Optional[Dict[str, Any]]:
    try:
        with journal.company_transaction() as session:
            row = session.get(MemoryOperation, event_id)
            if row is None or row.state != journal.COMMITTED:
                return None
            return {
                "owner_id": row.owner_id,
                "company_key": row.company_key,
                "effects": _effects(row.pending_effects),
            }
    except journal.JournalError:
        raise
    except Exception as exc:  # noqa: BLE001 - a journal that cannot answer is a refusal
        raise journal.JournalError(f"operation journal unavailable: {exc}") from exc


def _pending_of(owner_id: str) -> List[Tuple[str, Tuple[PendingEffect, ...]]]:
    key = current_company_key()
    if not key:
        return []
    try:
        with journal.company_transaction() as session:
            rows = (
                session.query(MemoryOperation.event_id, MemoryOperation.pending_effects)
                .filter(
                    MemoryOperation.company_key == key,
                    MemoryOperation.owner_id == owner_id,
                    MemoryOperation.state == journal.COMMITTED,
                    MemoryOperation.source_ref.like(f"{PAIR_SOURCE_KIND}:%"),
                )
                .all()
            )
    except journal.JournalError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise journal.JournalError(f"operation journal unavailable: {exc}") from exc
    return [(str(event_id), _effects(raw)) for event_id, raw in rows if _effects(raw)]


def _record_remaining(event_id: str, remaining: List[PendingEffect]) -> None:
    try:
        with journal.company_transaction(write=True) as session:
            row = session.get(MemoryOperation, event_id)
            if row is None:
                raise journal.JournalError(f"no operation for event {event_id}")
            row.pending_effects = [{"kind": e.kind, "detail": e.detail} for e in remaining]
            session.flush()
    except journal.JournalError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise journal.JournalError(f"operation journal unavailable: {exc}") from exc


def _survivor(keeper: str) -> str:
    """Where the keeper lives now: a later merge may have folded it in turn."""
    from zylch.memory.scope import survivor

    try:
        with journal.company_transaction() as session:
            return survivor(session, keeper)
    except Exception as exc:  # noqa: BLE001 - the alias still resolves the keeper for readers
        logger.warning(f"[references] cannot follow the merges of {keeper}; using it: {exc}")
        return keeper


# ─── The profile half ─────────────────────────────────────────────────


def _rewrite_ledger(owner_id: str, donor: str, keeper: str) -> int:
    """Re-point this owner's task ledger from the donor to the keeper.

    Only ``sources["blobs"]`` of a task that names the donor changes: the donor
    becomes the keeper in place, a resulting duplicate is dropped, and every
    other field of the row, and every other task, is left exactly as it was.
    This process's own profile file, and no other.
    """
    from zylch.storage.database import get_session
    from zylch.storage.models import TaskItem

    if not (donor and keeper):
        return 0
    rewritten = 0
    with get_session() as session:
        for task in session.query(TaskItem).filter(TaskItem.owner_id == owner_id).all():
            sources = task.sources
            if not isinstance(sources, dict):
                continue
            listed = sources.get("blobs") or []
            if donor not in listed:
                continue
            seen, blobs = set(), []
            for blob_id in listed:
                blob_id = keeper if blob_id == donor else blob_id
                if blob_id not in seen:
                    seen.add(blob_id)
                    blobs.append(blob_id)
            task.sources = {**sources, "blobs": blobs}
            rewritten += 1
    return rewritten


__all__ = ["apply", "follow_up", "replay_pending"]
