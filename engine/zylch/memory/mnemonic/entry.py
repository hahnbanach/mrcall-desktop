"""How a helper writer enters the harness: which contract, from where.

The fact store, the rule store and correction learning are called from more
than one place, and the place decides the paid-admission contract, not the
helper. Three states, and only three:

- **inside an admitted preparation item** — automatic, with that item's stage
  and source, so the grant matches what preparation actually admitted;
- **inside a preparation run but outside an item** — refused. The
  ``bounded_operation`` trainers and the maintenance RPCs live there, and a
  helper reached from one of them must not buy the interactive contract by
  omission. No such caller exists today; this is the guard that keeps it so.
- **otherwise** — interactive, on the current turn: its cancellation handle,
  a ``turn:<id>`` source, and the turn's observation when there is one.

Correction learning is the one helper that supplies its own source: the
drafted and sent texts of one approved send, keyed by their digest, on the
solve turn that produced them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

from .contracts import AUTOMATIC, INTERACTIVE, Cancellation
from .turn import turn_cancellation


class EntryRefused(PermissionError):
    """A helper writer was called from a place that grants it no contract."""


@dataclass(frozen=True)
class Entry:
    """The admission and source binding a helper writer's event is built with."""

    origin: str
    source_kind: str
    source_id: str
    source_revision: str
    observation: str
    cancellation: Cancellation
    stage: Optional[str] = None


def digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:32]


def entry_for(
    *,
    fallback: str,
    kind: str = "chat",
    observation: Optional[str] = None,
    source_id: Optional[str] = None,
) -> Entry:
    """The entry a helper writer runs under, decided from where it was called.

    ``fallback`` is what stands as the observation when the turn recorded
    none — the text the caller was handed, which is at least what was said to
    it. ``kind`` names the interactive source kind; ``source_id`` overrides
    the turn id when the caller has a durable source of its own.
    """
    from zylch.services.preparation import current_item, current_run

    item = current_item()
    if item:
        _owner, stage, source, run_id = item
        if not run_id:
            raise EntryRefused(
                "a helper writer inside an unadmitted preparation item has no contract"
            )
        text = (observation or "").strip() or fallback
        return Entry(
            origin=AUTOMATIC,
            source_kind=stage.split(":", 1)[-1] if ":" in stage else stage,
            source_id=str(source),
            source_revision=digest(text),
            observation=text,
            cancellation=turn_cancellation(),
            stage=stage,
        )
    if current_run():
        raise EntryRefused(
            "a helper writer inside a preparation run must be called from an admitted item; "
            "nothing was written"
        )
    from zylch.assistant.turn_context import get_turn_id, get_turn_observation

    text = (observation or "").strip() or get_turn_observation().strip() or fallback
    return Entry(
        origin=INTERACTIVE,
        source_kind=kind,
        source_id=source_id or f"turn:{get_turn_id()}",
        source_revision=digest(text),
        observation=text,
        cancellation=turn_cancellation(),
    )


__all__ = ["Entry", "EntryRefused", "digest", "entry_for"]
