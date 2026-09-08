"""Joining and inspecting the company memory over RPC.

``memory.join`` is the ONLY write path for ``MEMORY_KEY`` once memory
lives in a store per company: it merges, writes the key, and rebinds the
running engine in-process — the three things a ``settings.update`` plus
restart cannot do (no merge; and a headless daemon has no restart).

None of these return a filesystem path. ``cs memory`` on the kernel side
resolves the engine's memory to an RPC endpoint plus a reachability
verdict, and that shape stays untouched.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


async def memory_status(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """memory.status() -> {has_key, available, reason, self_notion?, blob_count?, contributors?}.

    Whether this profile's memory is usable, and when it is not, why —
    "no company memory store exists for this key on this host" is the
    answer a typed unknown key gets, with memory disabled and mail sync
    untouched. Sizes and the company's self-notion when available.
    """
    from zylch.memory.join import status

    out = status()
    logger.debug(f"[rpc] memory.status -> available={out.get('available')}")
    return out


async def memory_join_preview(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """memory.join_preview(key?) -> {well_formed, exists, reason, self_notion?, blob_count?, fact_count?, contributors?}.

    The echo before the join: what memory this key names, how big it is,
    whose contributions it holds. Creates nothing; an unknown key answers
    ``exists: false``. Optional because a refusal is an answer, never a
    transport error.
    """
    from zylch.memory.join import preview

    key = params.get("key")
    out = preview(key if isinstance(key, str) else "")
    logger.debug(f"[rpc] memory.join_preview -> exists={out.get('exists')}")
    return out


async def memory_join(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """memory.join(key?) -> {ok, reason?, already?, merged?, self_notion?, blob_count?, contributors?}.

    Merge this profile's memory into the store ``key`` names, write the
    key to the profile, rebind the running engine to the joined store.
    Refuses a malformed or unknown key with ``ok: false``; the old store
    stays on disk.
    """
    from zylch.memory.join import join

    key = params.get("key")
    out = join(key if isinstance(key, str) else "")
    logger.info(f"[rpc] memory.join -> ok={out.get('ok')} already={out.get('already', False)}")
    return out


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "memory.status": memory_status,
    "memory.join_preview": memory_join_preview,
    "memory.join": memory_join,
}
