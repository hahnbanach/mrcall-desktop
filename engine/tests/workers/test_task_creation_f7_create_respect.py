"""Fix D restriction to thread-tasks (2026-05-13).

Regression for the Wilson/Rossi-overwrites-Baker incident on
``support@example.com``. Pre-fix, ``Fix D`` in
``zylch/workers/task_creation.py`` converted any ``task_action="create"``
LLM decision into ``update_task_item(existing_tasks_all[0], …)`` whenever
the candidate list was non-empty. After F7 began surfacing cross-contact
topical-blob siblings into ``existing_tasks_all``, this meant an
unrelated customer's email could land its content on the topical
sibling's task — corrupting ``contact_email`` (kept Baker) vs
``suggested_action`` (rewritten as Wilson).

The fix restricts the create→update conversion to candidates that came
from the thread-tasks branch specifically. The predicate is exposed as
``_pick_force_update_target(existing_tasks_all, thread_task_ids)`` and
unit-tested here in isolation, mirroring the pattern of
``test_task_phase2_ordering.py``.
"""

from __future__ import annotations

from zylch.workers.task_creation import _pick_force_update_target


def _task(task_id: str, **extra) -> dict:
    return {"id": task_id, "action_required": True, **extra}


def test_thread_task_force_updates():
    """The original Fix D case: a same-thread task is in existing_tasks_all
    and was added via the thread-tasks branch. CREATE → force update."""
    thread_task = _task("thread-A")
    existing = [thread_task]
    thread_ids = {"thread-A"}

    target = _pick_force_update_target(existing, thread_ids)

    assert target is thread_task


def test_f7_only_candidate_does_not_force_update():
    """The reported bug: ``existing_tasks_all`` contains only an F7
    topical-blob sibling (different thread, possibly different contact).
    A CREATE from the LLM MUST be respected — no force-update — or
    Wilson's email lands on Baker's task again."""
    f7_sibling = _task("f7-sibling")
    existing = [f7_sibling]
    thread_ids: set = set()  # no thread-tasks were collected

    target = _pick_force_update_target(existing, thread_ids)

    assert target is None


def test_mixed_picks_thread_task_even_if_not_first():
    """When both thread-tasks and F7 siblings are present, Fix D fires
    on the thread-task — never on an F7-only candidate, regardless of
    list order. Order in production is thread → contact → F7, but the
    predicate must not rely on positional ordering."""
    f7_first = _task("f7-first")
    thread_task = _task("thread-B")
    existing = [f7_first, thread_task]
    thread_ids = {"thread-B"}

    target = _pick_force_update_target(existing, thread_ids)

    assert target is thread_task


def test_contact_only_candidate_does_not_force_update():
    """Same-contact-but-different-thread candidates (the Bug E / plural
    `get_tasks_by_contact` source) are surfaced for LLM context, but if
    the LLM chooses CREATE we let it. They are not in ``thread_task_ids``."""
    contact_task = _task("contact-sibling")
    existing = [contact_task]
    thread_ids: set = set()

    target = _pick_force_update_target(existing, thread_ids)

    assert target is None


def test_empty_existing_returns_none():
    """No candidates at all — Fix D obviously doesn't fire."""
    assert _pick_force_update_target([], set()) is None
    assert _pick_force_update_target([], {"thread-X"}) is None


def test_empty_thread_ids_short_circuits():
    """An ``existing_tasks_all`` populated entirely by F7/contact paths
    (``thread_task_ids`` empty) must always yield None, regardless of
    list length."""
    existing = [_task("a"), _task("b"), _task("c")]
    assert _pick_force_update_target(existing, set()) is None


def test_multiple_thread_tasks_returns_first_thread_match():
    """Two thread-tasks in existing_tasks_all (e.g. one anchored on this
    contact, another on a CCed colleague's earlier reply). Fix D picks
    the first match — the iteration order of existing_tasks_all is the
    insertion order, which production-side is thread_tasks first
    (line 387 of task_creation.py)."""
    t1 = _task("thread-1")
    t2 = _task("thread-2")
    f7 = _task("f7-only")
    existing = [t1, t2, f7]
    thread_ids = {"thread-1", "thread-2"}

    target = _pick_force_update_target(existing, thread_ids)

    assert target is t1
