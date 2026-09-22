"""Wiring the engine's real memory surfaces to one event's decision.

The commit itself must not decide which store it writes to or which account it
reads as — that is composition, and it is here so a test can drive the real
commit against real split databases without the module choosing for it.

Nothing here writes. It gathers: the bounded candidate set the mnemonic role
is shown, and the read-only callables that produce it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence, Tuple

from .candidates import event_identifiers, gather
from .contracts import MAX_CANDIDATES, Candidate, MemoryEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommitContext:
    """The storage surfaces one commit needs, assembled once by the engine.

    Passing them in rather than reaching for globals is what lets a test drive
    the real commit against real split databases without the module deciding
    for itself which store it writes to.
    """

    storage: Any  # zylch.memory.blob_storage.BlobStorage
    get_blob: Callable[[str], Optional[dict]]
    search: Callable[[str, int], Sequence[Any]] = lambda _q, _n: ()
    identifier_blob_ids: Callable[[Sequence[Tuple[str, str]]], Sequence[str]] = lambda _i: ()


def default_context(owner_id: str) -> CommitContext:
    """Wire the engine's real memory surfaces for this account."""
    from zylch.memory import EmbeddingEngine, MemoryConfig
    from zylch.memory.blob_storage import BlobStorage
    from zylch.memory.hybrid_search import HybridSearchEngine
    from zylch.storage.database import get_session
    from zylch.storage.storage import Storage

    embeddings = EmbeddingEngine(MemoryConfig())
    storage = BlobStorage(get_session, embeddings)
    search_engine = HybridSearchEngine(get_session, embeddings)
    rows = Storage()

    return CommitContext(
        storage=storage,
        get_blob=lambda blob_id: storage.get_blob(blob_id, owner_id),
        search=lambda query, limit: search_engine.search(owner_id, query, limit=limit),
        identifier_blob_ids=lambda ids: rows.find_blobs_by_identifiers(owner_id, list(ids)),
    )


def parse_identifiers_block(content: str) -> list:
    """The ``(kind, value)`` pairs a blob's ``#IDENTIFIERS`` header declares.

    One parser, imported rather than reimplemented: it carries rules a second
    copy would lose — multi-value lines, the ``00`` → ``+`` upgrade, and the
    refusal to index a LID-shaped value as a phone. It lives in
    ``workers/memory.py`` because that is where it was written; milestone 6
    converts that module and can move it then.
    """
    from zylch.workers.memory import _parse_identifiers_block

    return _parse_identifiers_block(content or "")


_PHONE_SHAPED = re.compile(r"^\+?\d{7,}$")


def typed_identifiers(event: MemoryEvent) -> list:
    """The event's identifiers as ``(kind, value)``, for the identity index.

    Only the two shapes the index actually stores get a kind. A name or a
    company name is a real identifier for *retrieval* and no identifier at all
    for ``person_identifiers``, which deliberately excludes names — two people
    called Mario Rossi are two people.
    """
    pairs = []
    for token in event_identifiers(event):
        if "@" in token:
            pairs.append(("email", token))
        elif _PHONE_SHAPED.match(token):
            pairs.append(("phone", token))
    return pairs


def candidates_for(event: MemoryEvent, context: CommitContext) -> Tuple[Candidate, ...]:
    """The bounded, read-only comparison set for one event."""
    typed = typed_identifiers(event)
    identifier_ids = list(context.identifier_blob_ids(typed))[:MAX_CANDIDATES] if typed else []
    return gather(
        event,
        get_blob=context.get_blob,
        search=context.search,
        identifier_blob_ids=identifier_ids,
    )


__all__ = [
    "CommitContext",
    "candidates_for",
    "default_context",
    "parse_identifiers_block",
    "typed_identifiers",
]
