"""What each committed action writes, inside the commit's one company transaction.

``commit.py`` owns the transaction — the lease, the re-check of authorization
under the write lock, the permit, the mutation sequence and the receipt. This
module is what goes between them for each action: the UPDATE's re-read and
rewrite, the MERGE's re-read, drop, links and alias, and the index writes every
action shares. Nothing here opens a session or commits, and nothing here
swallows an error: inside a transaction a swallowed failure is exactly the
half-written state the harness exists to prevent.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from zylch.memory.commit_permit import ConflictError

from .contracts import MERGE, UPDATE, MemoryEvent
from .proposals import PendingEffect, Proposal
from .wiring import CommitContext, parse_identifiers_block

# The recorded follow-up a MERGE owes the profile that committed it: the task
# ledger naming the donor is re-pointed at the keeper, after the company commit.
TASK_REFERENCES = "task_references"


def update(session, event, proposal, permit, prepared, context, *, note: str):
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
        event_description=note,
    )


def merge(
    session,
    event: MemoryEvent,
    proposal: Proposal,
    permit: Any,
    prepared: Any,
    context: CommitContext,
    *,
    note: str,
) -> Dict[str, Any]:
    """Fold the donor into the keeper: re-read, drop, links, alias — all or nothing.

    Both members are re-read under the lock; a member that is gone is a
    conflict, never a new entity. The donor's source links are read before it
    is dropped (its own link rows go with it by cascade) and re-created on the
    keeper with each link's own ``owner_id``, so every source either blob was
    extracted from still reaches the survivor. The alias makes the donor's id
    resolvable wherever a ledger still names it. The identifier rows are the
    shared :func:`indexes`, from the merged text alone.
    """
    from zylch.memory import associations

    keeper_target, donor_target = proposal.keeper, proposal.donor
    keeper = context.storage.visible_target(session, keeper_target.blob_id, event.owner_id)
    donor = context.storage.visible_target(session, donor_target.blob_id, event.owner_id)
    if keeper is None or donor is None:
        raise ConflictError(
            "a paired memory is no longer visible to this account; refusing the merge"
        )
    links = associations.links_of(session, blob_id=str(donor.id), company_key=event.company_key)
    blob = context.storage.semantic_merge(
        session,
        permit,
        keeper=keeper,
        donor=donor,
        owner_id=event.owner_id,
        prepared=prepared,
        keeper_version=keeper_target.expected_version,
        donor_version=donor_target.expected_version,
        event_description=note,
    )
    for kind, source_id, owner_id in links:
        associations.link_source(
            session,
            source_kind=kind,
            source_id=source_id,
            blob_id=str(blob["id"]),
            owner_id=owner_id,
        )
    associations.record_alias(
        session, merged_id=str(donor_target.blob_id), keeper_id=str(blob["id"])
    )
    return blob


def indexes(session, event: MemoryEvent, blob_id: str, proposal: Proposal) -> None:
    """Identity index and source link — inside the same transaction as the blob.

    An UPDATE **replaces** the blob's identifier rows rather than adding to
    them. The old writer only appended, so correcting an email address left the
    wrong one in the index and the next cross-channel lookup still matched it.
    A MERGE replaces the keeper's the same way: its rows are what the merged
    text states, so an index row neither member's text stated — a sender's
    address a legacy writer attached — does not spread onto the survivor.
    """
    from zylch.memory import associations

    identifiers = associations.identifiers_from(parse_identifiers_block(proposal.content))
    if proposal.action in (UPDATE, MERGE):
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


def pending_for(proposal: Proposal) -> Tuple[PendingEffect, ...]:
    """The follow-up a committed proposal owes after its company transaction."""
    if proposal.action != MERGE:
        return ()
    return (
        PendingEffect(
            kind=TASK_REFERENCES,
            detail=f"{proposal.donor.blob_id}->{proposal.keeper.blob_id}",
        ),
    )


__all__ = ["TASK_REFERENCES", "indexes", "merge", "pending_for", "update"]
