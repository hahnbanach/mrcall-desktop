"""RPC handlers for task read-only queries.

Kept separate from `rpc/methods.py` (1500+ lines) to stay under the
500-line per-module guideline. At the moment this exposes a single
method used by the desktop "Open" flow on the Inbox view:

  tasks.list_by_thread(thread_id)
      Return the list of open tasks whose source emails resolve to the
      given thread. Thin wrapper over `Storage.get_tasks_by_thread`.
      The desktop Tasks view uses this to filter itself to exactly the
      tasks belonging to one email thread — ALWAYS, even when there is
      1 task or 0 tasks (no fall-through to a per-task open shortcut).
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str, Dict[str, Any]], None]


def _owner_id() -> str:
    """Resolve owner_id the same way the main dispatch does."""
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


async def tasks_list_by_thread(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """tasks.list_by_thread(thread_id) -> list of task dicts.

    Returns every OPEN task whose `sources.emails` references at least
    one email in the given thread. Empty list is a valid return — a
    thread with no associated tasks is common and must not surface as
    an error.
    """
    from zylch.storage.storage import Storage

    thread_id = params.get("thread_id")
    if not thread_id:
        raise ValueError("thread_id is required")
    if not isinstance(thread_id, str):
        raise ValueError("thread_id must be a string")

    owner_id = _owner_id()
    store = Storage.get_instance()
    tasks = store.get_tasks_by_thread(owner_id=owner_id, thread_id=thread_id)
    logger.debug(f"[rpc:tasks.list_by_thread] thread_id={thread_id} -> count={len(tasks)}")
    return tasks


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "tasks.list_by_thread": tasks_list_by_thread,
}
