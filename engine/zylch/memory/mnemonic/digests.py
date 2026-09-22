"""Stable digests of what an event promised and what a proposal asks for.

Two identities the rest of the harness keys on. The **input digest** is what
makes an event id a promise: the same id may be replayed forever, and may never
be re-pointed at different input. The **proposal digest** is what a commit
permit binds to, and what milestone 4's approval will bind to — so it has to
move when the targets or the versions move, not only when the prose does.

Both cover exactly what they claim to and nothing else. The input digest omits
the model's suggestion on purpose: an outer agent re-asked about the same turn
may word its rewrite differently, and that is not a different observation.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

from .contracts import MemoryEvent
from .proposals import Proposal


def input_digest(event: MemoryEvent) -> str:
    """Digest of exactly the fields a model may never set.

    Two submissions of one event id must describe the same thing. Digesting
    the sealed fields — and not the suggestion — is what lets a retry carry a
    differently worded model suggestion while still refusing an id pointed at
    a different observation, owner or source.
    """
    sealed = {name: getattr(event, name) for name in MemoryEvent.MODEL_SEALED}
    return hashlib.sha256(
        json.dumps(sealed, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def proposal_digest(proposal: Optional[Proposal]) -> Optional[str]:
    """Digest of what the proposal asks to do, to bind a permit and an approval."""
    if proposal is None:
        return None
    shape = {
        "action": proposal.action,
        "entity_type": proposal.entity_type,
        "scope": proposal.scope,
        "content": proposal.content,
        "write_set": [(t.blob_id, t.expected_version, t.role) for t in proposal.write_set],
        "declared_effects": list(proposal.declared_effects),
        "reclassification": (
            None
            if proposal.reclassification is None
            else [
                proposal.reclassification.from_entity_type,
                proposal.reclassification.from_scope,
                proposal.reclassification.to_entity_type,
                proposal.reclassification.to_scope,
            ]
        ),
    }
    return hashlib.sha256(
        json.dumps(shape, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


__all__ = ["input_digest", "proposal_digest"]
