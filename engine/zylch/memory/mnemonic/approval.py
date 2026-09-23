"""What a proposal departed from — recorded, never gated.

A tool call names what it asks for: an update of this blob, a new memory under
that family. The mnemonic role then decides, and it may decide differently — a
different action, a different target, a different scope, an effect that folds
another memory in. Milestone 4 stopped such a proposal at a human acceptance;
that gate is withdrawn (brief amendment, 2026-09-23). Human memory asks nobody's
permission to write; what protects it is that a write does not destroy, and that
it remembers who said what. Retention (`memory/blob_versions.py`) is the first
half. This module is the second: a proposal that departed from the request is
committed with the departure **recorded**, in the operation journal and in the
caller's response, so a human can see that the role chose differently and
correct it later — as a new observation, not as a permission.

:class:`RequestedWrite` is the baseline an adapter declares from the tool call's
own arguments, never from the proposal. :func:`flags_for` names each structural
way the proposal departs from it. :func:`departure_for` turns that into the
record the journal and the response carry, or ``None`` when the proposal did
exactly what was asked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .proposals import Proposal

# Each flag is a structural difference between what the caller asked for and
# what the role decided. They are read by humans in a journal row and a tool
# response, so they are written to be read by one.
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

    The adapter fills this in from the tool call, never from the proposal. A
    legacy argument that carried no authority is recorded as carrying none: a
    solve ``query`` selects nothing and leaves :attr:`blob_id` empty, which is
    what makes every solve update a write whose subject the caller did not
    choose — worth recording, so a reader knows the row was the role's pick.
    """

    action: str
    blob_id: Optional[str] = None
    entity_type: Optional[str] = None
    scope: Optional[str] = None
    # True when the caller named a concrete blob it intends to write. A tool
    # that only described what to look for did not.
    subject_is_authoritative: bool = False


def flags_for(requested: RequestedWrite, proposal: Proposal) -> Tuple[str, ...]:
    """Every structural way this proposal departs from what was asked for."""
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


def departure_for(
    requested: Optional[RequestedWrite], proposal: Proposal
) -> Optional[Dict[str, Any]]:
    """The record of how ``proposal`` departed from ``requested``, or ``None``.

    ``None`` means nothing to record: the proposal did what was asked, or the
    adapter declared no baseline — with nothing to compare against there is no
    departure to name, and inventing one would put a false flag in the journal.
    JSON-shaped, because it is stored in ``memory_operations.departure`` and
    returned in the tool's response as it is.
    """
    if requested is None:
        return None
    flags = flags_for(requested, proposal)
    if not flags:
        return None
    return {
        "flags": list(flags),
        "why": [FLAG_REASONS[flag] for flag in flags if flag in FLAG_REASONS],
        "requested": {
            "action": requested.action,
            "blob_id": requested.blob_id,
            "entity_type": requested.entity_type,
            "scope": requested.scope,
        },
        "proposed": {
            "action": proposal.action,
            "entity_type": proposal.entity_type,
            "scope": proposal.scope,
            "targets": [t.blob_id for t in proposal.write_set],
        },
    }


__all__ = [
    "CHANGED_ACTION",
    "CHANGED_SCOPE",
    "CHANGED_SUBJECT",
    "DESTRUCTIVE_EFFECTS",
    "FLAG_REASONS",
    "RequestedWrite",
    "UNNAMED_SUBJECT",
    "departure_for",
    "flags_for",
]
