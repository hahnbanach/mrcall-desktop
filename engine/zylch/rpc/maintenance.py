"""Maintenance RPCs — manual triggers for the dedup + reconsolidation sweeps.

These are the "Clean up tasks" / "Reconsolidate memory" buttons in
Settings: the user can ask for a sweep on demand, instead of waiting
for the next /update. Same workers as the scheduled paths.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


def _owner_id() -> str:
    """Resolve the active profile's owner_id (matches the rest of the
    dispatcher's convention; cli.utils.get_owner_id reads
    EMAIL_ADDRESS / falls back to 'local-user')."""
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


async def tasks_dedup_now(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """tasks.dedup_now() -> summary dict.

    Runs the F8 dedup sweep immediately. Returns the worker summary so
    the renderer can surface it ("Closed N tasks across M cluster(s)").
    Tolerates LLM-not-configured (returns no_llm=True for the renderer
    to render an explanatory message).
    """
    from zylch.workers.task_dedup_sweep import run_dedup_sweep

    owner_id = _owner_id()
    logger.debug(f"[rpc] tasks.dedup_now owner_id={owner_id}")
    summary = await run_dedup_sweep(owner_id)
    logger.debug(f"[rpc] tasks.dedup_now -> {summary}")
    return summary


async def memory_reconsolidate_now(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """memory.reconsolidate_now() -> summary dict.

    Runs the memory reconsolidation pass on the active profile. The
    pass walks blob entities, merges semantically-equivalent duplicates
    (same person across multiple "Carmine Salomone PERSON" blobs etc.),
    and returns counts.

    Implementation lives in zylch.memory.llm_merge — this RPC is a
    thin wrapper for the Settings button.
    """
    from zylch.memory.llm_merge import reconsolidate_now as _reconsolidate

    owner_id = _owner_id()
    logger.debug(f"[rpc] memory.reconsolidate_now owner_id={owner_id}")
    try:
        summary = await _reconsolidate(owner_id)
    except Exception as e:
        logger.exception(f"[rpc] memory.reconsolidate_now failed: {e}")
        return {"ok": False, "error": str(e)}
    logger.debug(f"[rpc] memory.reconsolidate_now -> {summary}")
    return {"ok": True, **summary}


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "tasks.dedup_now": tasks_dedup_now,
    "memory.reconsolidate_now": memory_reconsolidate_now,
}
