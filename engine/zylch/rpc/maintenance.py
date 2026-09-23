"""Maintenance RPCs — manual triggers for the dedup + reconsolidation sweeps,
and the mechanical restore of a memory version.

The sweeps are the "Clean up tasks" / "Reconsolidate memory" buttons in
Settings: the user can ask for a sweep on demand, instead of waiting for the
next /update. Same workers as the scheduled paths. The restore brings one
memory blob back to a version ``blob_versions`` retained for it; it asks no
model and pays nothing, so it is not a bounded operation.
"""

from __future__ import annotations

from zylch.services.preparation import bounded_operation

import asyncio
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


@bounded_operation(lambda *args, **kwargs: _owner_id())
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


@bounded_operation(lambda *args, **kwargs: _owner_id())
async def tasks_topic_dedup_now(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """tasks.topic_dedup_now() -> summary dict.

    Runs the F9 cross-contact topic dedup sweep on the user's open
    tasks. One Opus call clusters everything by underlying problem,
    closes non-keepers. Same shape as the auto-run that fires inside
    every /update; this is the manual button.
    """
    from zylch.workers.task_topic_dedup import run_topic_dedup

    owner_id = _owner_id()
    logger.debug(f"[rpc] tasks.topic_dedup_now owner_id={owner_id}")
    summary = await run_topic_dedup(owner_id)
    logger.debug(f"[rpc] tasks.topic_dedup_now -> {summary}")
    return summary


@bounded_operation(lambda *args, **kwargs: _owner_id())
async def memory_reconsolidate_now(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """memory.reconsolidate_now() -> summary dict.

    Runs the memory reconsolidation pass on the active profile. The
    pass walks blob entities, merges semantically-equivalent duplicates
    (same person across multiple "John Smith PERSON" blobs etc.),
    and returns counts.

    Implementation lives in zylch.memory.llm_merge — this RPC is a
    thin wrapper for the Settings button.
    """
    from zylch.memory.llm_merge import reconsolidate_now as _reconsolidate

    owner_id = _owner_id()
    logger.debug(f"[rpc] memory.reconsolidate_now owner_id={owner_id}")
    try:
        summary = await _reconsolidate(owner_id, force=True)  # the button always sweeps
    except Exception as e:
        logger.exception(f"[rpc] memory.reconsolidate_now failed: {e}")
        return {"ok": False, "error": str(e)}
    logger.debug(f"[rpc] memory.reconsolidate_now -> {summary}")
    return {"ok": True, **summary}


async def memory_restore_version(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """memory.restore_version(blob_id?, version_id?) -> {ok, blob?, version_id?, reason?}.

    Restores one memory blob to a version ``blob_versions`` retained for it.
    Mechanical: no model is asked, the version's text comes back exactly, and
    the text it replaces is retained first, so a restore is itself reversible.
    Both ids are declared optional because the handler answers
    ``{ok: false, reason}`` rather than raising when one is missing, when the
    version belongs to another blob, or when the blob is not visible to this
    profile.

    Denied to the scheduled operator by name in the kernel's cron template,
    like every other memory mutation reachable as a raw RPC.
    """
    blob_id = str(params.get("blob_id") or "").strip()
    version_id = str(params.get("version_id") or "").strip()
    if not blob_id or not version_id:
        return {"ok": False, "reason": "blob_id and version_id are required"}
    owner_id = _owner_id()
    logger.debug(
        f"[rpc] memory.restore_version owner_id={owner_id} blob={blob_id} version={version_id}"
    )
    try:
        from zylch.memory import BlobStorage, EmbeddingEngine, MemoryConfig
        from zylch.storage.database import get_session

        storage = BlobStorage(get_session, EmbeddingEngine(MemoryConfig()))
        result = await asyncio.to_thread(storage.restore_version, blob_id, owner_id, version_id)
    except Exception as e:
        logger.exception(f"[rpc] memory.restore_version failed: {e}")
        return {"ok": False, "reason": str(e)}
    logger.debug(f"[rpc] memory.restore_version -> ok={result.get('ok')}")
    return result


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "tasks.dedup_now": tasks_dedup_now,
    "tasks.topic_dedup_now": tasks_topic_dedup_now,
    "memory.reconsolidate_now": memory_reconsolidate_now,
    "memory.restore_version": memory_restore_version,
}
