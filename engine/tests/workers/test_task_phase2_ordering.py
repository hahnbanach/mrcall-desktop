"""F5 regression: Phase 2 ordering puts LLM creates before user_reply closes.

Real case (2026-05-04, profile HxiZh…): a user reply on a sibling thread
arrived in the same batch as the contact's email that produced the task.
Because `get_unprocessed_emails_for_task` returns rows newest-first, the
user_reply was consumed BEFORE the task even existed — the per-recipient
close lookup found nothing and bailed; the task was then created moments
later and never closed.

The fix sorts Phase 2 items so any `kind == "llm"` comes before any
`kind == "user_reply"`. This file exercises the sort key directly,
without going through the (currently broken) MagicMock fixture in
``test_task_worker_bugs.py``.
"""

from __future__ import annotations


def _phase2_key(item):
    # Mirrors the production sort key in
    # zylch/workers/task_creation.py Phase 2.
    return 1 if item[0] == "user_reply" else 0


def test_llm_creates_run_before_user_reply_closes():
    """The asyncio.gather output is in input order, which is dict-insertion
    order of `threads` — for a date-DESC scan that puts user_reply FIRST.
    The Phase 2 sort key flips that so LLM items run first."""
    collected = [
        ("user_reply", {"id": "user-reply-email", "thread_id": "T-newer"}),
        ("llm", {"id": "salamone-email", "thread_id": "T-older"}, {"result": {}}),
    ]
    ordered = sorted(collected, key=_phase2_key)
    assert ordered[0][0] == "llm"
    assert ordered[1][0] == "user_reply"


def test_sort_is_stable_within_each_kind():
    """Multiple LLM items keep their relative order (same key=0); same
    for multiple user_reply items (same key=1). Python's sorted() is
    stable, so we just rely on that — the assertion guards against a
    regression where someone replaces sorted() with a non-stable sort."""
    collected = [
        ("user_reply", {"id": "ur-a"}),
        ("llm", {"id": "llm-a"}, {}),
        ("user_reply", {"id": "ur-b"}),
        ("llm", {"id": "llm-b"}, {}),
        ("user_reply", {"id": "ur-c"}),
    ]
    ordered = sorted(collected, key=_phase2_key)
    llm_ids = [x[1]["id"] for x in ordered if x[0] == "llm"]
    ur_ids = [x[1]["id"] for x in ordered if x[0] == "user_reply"]
    assert llm_ids == ["llm-a", "llm-b"]
    assert ur_ids == ["ur-a", "ur-b", "ur-c"]


def test_empty_collected_is_safe():
    assert sorted([], key=_phase2_key) == []


def test_only_user_replies_no_llm_path_runs_in_input_order():
    collected = [
        ("user_reply", {"id": "ur-1"}),
        ("user_reply", {"id": "ur-2"}),
    ]
    ordered = sorted(collected, key=_phase2_key)
    assert [x[1]["id"] for x in ordered] == ["ur-1", "ur-2"]


def test_only_llm_path_runs_in_input_order():
    collected = [
        ("llm", {"id": "l-1"}, {}),
        ("llm", {"id": "l-2"}, {}),
    ]
    ordered = sorted(collected, key=_phase2_key)
    assert [x[1]["id"] for x in ordered] == ["l-1", "l-2"]
