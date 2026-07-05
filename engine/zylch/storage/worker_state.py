"""Per-owner key-value store backing pipeline event-gating state.

Thin accessors over the ``worker_state`` table (see
``zylch.storage.models.WorkerState``). Used by
``zylch.workers.task_gating`` (support-llm-cost-fix / P3) to persist
the open-task fingerprint behind the F8/F9 gate, the daily full-sweep
stamp, and the merge-canary verdict across ticks.

Both accessors are deliberately fail-open and NEVER raise: gating state
is an optimization, and a broken read/write must degrade to "sweep is
due" (get returns None), never brick the pipeline. No LLM anywhere near
this module.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def get_state(owner_id: str, key: str) -> Optional[str]:
    """Return the stored value for ``(owner_id, key)``, or ``None``.

    ``None`` means "no state" — for every gating consumer that reads as
    "the conservative path" (sweep due, daily pass due, canary must
    run). A DB error degrades to the same answer, logged as a warning.
    """
    try:
        from zylch.storage.database import get_session
        from zylch.storage.models import WorkerState

        with get_session() as session:
            row = (
                session.query(WorkerState.value)
                .filter(WorkerState.owner_id == owner_id, WorkerState.key == key)
                .one_or_none()
            )
        value = row[0] if row else None
        logger.debug(f"[worker-state] get_state(owner_id={owner_id}, key={key}) -> {value!r}")
        return value
    except Exception as e:  # noqa: BLE001 — fail-open by design
        logger.warning(f"[worker-state] get_state({owner_id!r}, {key!r}) failed: {e}")
        return None


def set_state(owner_id: str, key: str, value: str) -> None:
    """Upsert ``value`` for ``(owner_id, key)``. Never raises.

    A write failure is logged and swallowed: the worst case is that the
    next tick re-runs a sweep it could have skipped — safe, just not
    free. ``updated_at`` is maintained by the column's default/onupdate.
    """
    try:
        from zylch.storage.database import get_session
        from zylch.storage.models import WorkerState

        with get_session() as session:
            row = (
                session.query(WorkerState)
                .filter(WorkerState.owner_id == owner_id, WorkerState.key == key)
                .one_or_none()
            )
            if row is None:
                session.add(WorkerState(owner_id=owner_id, key=key, value=value))
            else:
                row.value = value
        logger.debug(f"[worker-state] set_state(owner_id={owner_id}, key={key}) -> {value!r}")
    except Exception as e:  # noqa: BLE001 — fail-open by design
        logger.warning(f"[worker-state] set_state({owner_id!r}, {key!r}) failed (ignored): {e}")
