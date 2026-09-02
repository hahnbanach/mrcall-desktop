"""Read-only RPC handlers for engine drafts (`drafts.*`).

Drafts are composed by the chat `create_draft` tool (memory blobs +
trained voice + threading headers) and persisted in the engine DB as
the `Draft` model. They were not enumerable over JSON-RPC, so the
desktop UI showed a drafts count of 0 and operator tooling (mrcall-cs
`review`) could not list reply/outreach drafts deterministically.

This module exposes the existing `storage.list_drafts` query as a
read-only, owner-scoped RPC. It MUST NOT create / edit / send / mutate
anything — sending stays behind the existing approval-gated paths.

**How a caller sees a draft the engine did not create but did compose.**
`storage.create_draft` is idempotent: composing the same mail twice
within its window returns the existing row instead of a second one. A
caller that decides "did this turn produce a reply?" by diffing the ids
in `drafts.list` before and after therefore sees an EMPTY diff for a
reply that was genuinely composed, and reports that nothing was written.

The answer rides on `updated_at`, which every row already carries: a
reuse stamps it, so the rule for such a caller is

    new id in the after-set        -> the engine composed a new draft
    same ids, one `updated_at`
      at or after the turn started -> the engine composed the same mail
                                      again and reused the existing draft
    neither                        -> the engine composed nothing

No new method and no new field: a per-turn flag would have to be
invented, transported and kept true, while `updated_at` already means
"when this row last changed" and a re-compose is exactly that. The
consumer is `cs draft-reply` (`cs-kernel/cs/cli.py`).

Kept separate from `rpc/methods.py` per the 500-line module guideline;
merged into the dispatch table the same way the other sub-modules are.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


def _owner_id() -> str:
    """Resolve owner_id the same way the main dispatch does."""
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


async def drafts_list(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """drafts.list(status?) -> list of draft dicts.

    Mirrors `storage.list_drafts`: filter by owner_id + status, order
    `created_at` descending, return each row's `to_dict()`. Defaults to
    `status="draft"` (the unsent drafts). Read-only.
    """
    from zylch.storage.database import get_session
    from zylch.storage.models import Draft

    status = params.get("status") or "draft"
    owner_id = _owner_id()
    with get_session() as session:
        rows = (
            session.query(Draft)
            .filter(Draft.owner_id == owner_id, Draft.status == status)
            .order_by(Draft.created_at.desc())
            .all()
        )
        out: List[Dict[str, Any]] = [r.to_dict() for r in rows]
    logger.debug(f"[rpc:drafts.list] owner={owner_id} status={status} n={len(out)}")
    return out


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "drafts.list": drafts_list,
}
