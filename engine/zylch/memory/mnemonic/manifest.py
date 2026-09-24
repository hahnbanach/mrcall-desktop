"""A source's extraction manifest and its children, in the operation journal.

One ingested source — a mail, a WhatsApp message, a calendar event, a MrCall
conversation — is a *parent* operation whose extraction fans out into one
*child* operation per entity. The parent's payload holds the complete bounded
manifest; each child is a pending row of its own, ``parent_event_id`` set. Both
land in one transaction, before the first child is decided, which is what lets
a crash anywhere afterwards resume exactly the children that are unfinished
and never re-extract what was already paid for.

The parent is never routed through ``commit.submit``: its payload is written
here and pruned only by its own terminal receipt, after every child is
terminal. That invariant is what keeps the manifest from being overwritten by
``journal.record_attempt``, which rewrites a decided event's payload wholesale.
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence

from zylch.storage.models import MemoryOperation

from .contracts import EVENT_DISPATCH_ALLOWANCE, MemoryEvent
from .digests import input_digest
from .journal import (
    PENDING,
    PROTOCOL_VERSION,
    EventIdReused,
    JournalError,
    _now,
    _payload,
    _target_family,
    company_transaction,
    owns,
)


def record_manifest(
    parent: MemoryEvent,
    lease: str,
    entities: Sequence[str],
    children: Sequence[MemoryEvent],
) -> None:
    """Persist a source's extraction and open its children, in one transaction.

    The parent's payload gains the complete bounded manifest — one entry per
    extracted entity with the child event id it becomes — and one pending row
    per child is created beside it, ``parent_event_id`` set, before the first
    child is decided. Atomic on purpose: a crash between the manifest and the
    children would leave a source that looks extracted and has nothing to
    resume, and a crash before either leaves nothing at all, so the next run
    re-extracts. A child row that already exists (a resume) is left as it is
    and its digest is checked, because an id may be replayed and never
    re-pointed.

    The parent must still be held under ``lease``: a manifest written by an
    attempt another process has since taken over would race the winner's.
    """
    if len(entities) != len(children):
        raise JournalError("every extracted entity needs exactly one child event")
    try:
        with company_transaction(write=True) as session:
            row = owns(session, parent.event_id, lease)
            manifest = [
                {"event_id": child.event_id, "index": index, "content": entity}
                for index, (child, entity) in enumerate(zip(children, entities))
            ]
            row.payload = {**dict(row.payload or {}), "manifest": manifest}
            row.updated_at = _now()
            for child in children:
                existing = session.get(MemoryOperation, child.event_id)
                digest = input_digest(child)
                if existing is not None:
                    if existing.input_digest != digest:
                        raise EventIdReused(
                            f"event id {child.event_id} already exists with different input"
                        )
                    continue
                session.add(
                    MemoryOperation(
                        event_id=child.event_id,
                        owner_id=child.owner_id,
                        company_key=child.company_key,
                        parent_event_id=parent.event_id,
                        protocol_version=PROTOCOL_VERSION,
                        input_digest=digest,
                        source_ref=child.source_ref,
                        origin=child.origin,
                        caller_class=child.caller_class,
                        target_family=_target_family(None),
                        state=PENDING,
                        allowance=EVENT_DISPATCH_ALLOWANCE,
                        attempts=0,
                        payload=_payload(child, None),
                        pending_effects=[],
                        restrictions=[],
                    )
                )
            session.flush()
    except JournalError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise JournalError(f"operation journal unavailable: {exc}") from exc


def read_manifest(parent_event_id: str) -> Optional[list]:
    """The parent's persisted manifest, or ``None`` when extraction never landed."""
    try:
        with company_transaction() as session:
            row = session.get(MemoryOperation, parent_event_id)
            if row is None:
                return None
            payload = dict(row.payload or {})
            manifest = payload.get("manifest")
            return list(manifest) if isinstance(manifest, list) else None
    except Exception as exc:  # noqa: BLE001
        raise JournalError(f"operation journal unavailable: {exc}") from exc


def child_states(parent_event_id: str) -> Dict[str, str]:
    """Each child's current state, by event id — what a resume decides from."""
    try:
        with company_transaction() as session:
            rows = (
                session.query(MemoryOperation.event_id, MemoryOperation.state)
                .filter(MemoryOperation.parent_event_id == parent_event_id)
                .all()
            )
            return {str(event_id): str(state) for event_id, state in rows}
    except Exception as exc:  # noqa: BLE001
        raise JournalError(f"operation journal unavailable: {exc}") from exc



__all__ = ["child_states", "read_manifest", "record_manifest"]
