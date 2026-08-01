"""RPC handlers for task read-only queries.

Kept separate from `rpc/methods.py` (1500+ lines) to stay under the
500-line per-module guideline.

  tasks.list_by_thread(thread_id)
      Return the list of open tasks whose source emails resolve to the
      given thread. Thin wrapper over `Storage.get_tasks_by_thread`.
      The desktop Tasks view uses this to filter itself to exactly the
      tasks belonging to one email thread — ALWAYS, even when there is
      1 task or 0 tasks (no fall-through to a per-task open shortcut).

  tasks.get(task_id)
      Return ONE task by id, open or closed, with its full row
      including the close audit fields. The ledger had no way to ask
      about a single task: `tasks.list` returns a filtered, capped,
      re-sorted slice, so a caller wanting to know "is this task still
      open, and who closed it?" had to fetch a page and hope the task
      was on it.
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


async def tasks_get(params: Dict[str, Any], notify: NotifyFn) -> Any:
    """tasks.get(task_id) -> task dict | null.

    One task by primary key, open OR closed. The returned row is the
    full record: `completed_at`, `close_note` and the `close_actor`
    audit column included, so a caller can tell an open task from one
    that was closed, and a human close from a machine one. `due_at`
    (epoch seconds, NULL when the task is actionable now) comes back
    too, so a caller can tell a parked task from a pending one.

    `null` (not an error) when no task with that id belongs to the
    owner — "does this task still exist?" is a legitimate question with
    a legitimate negative answer.
    """
    from zylch.storage.storage import Storage

    task_id = params.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")
    if not isinstance(task_id, str):
        raise ValueError("task_id must be a string")

    owner_id = _owner_id()
    store = Storage.get_instance()
    task = store.get_task_by_id(owner_id=owner_id, task_id=task_id)
    logger.debug(
        f"[rpc:tasks.get] task_id={task_id} -> found={task is not None} "
        f"completed_at={task.get('completed_at') if task else None} "
        f"close_actor={task.get('close_actor') if task else None}"
    )
    return task


METHODS: Dict[str, Callable[[Dict[str, Any], NotifyFn], Awaitable[Any]]] = {
    "tasks.list_by_thread": tasks_list_by_thread,
    "tasks.get": tasks_get,
}
