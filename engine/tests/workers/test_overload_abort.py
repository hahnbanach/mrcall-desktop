"""Sweep paths must abort cleanly on persistent provider overload.

Regression coverage for the live observation 2026-05-06 on the gmail
profile: Anthropic returned HTTP 529 (Overloaded) for every call in
the F4 reanalyze sweep + the F8 dedup arbiter, flooding stderr with
identical stack traces. The fix bumps the SDK's max_retries to 5
(client.py) and adds an abort-on-2-consecutive-529 guard in each
sweep path so the loop stops after the second failure instead of
exhausting the whole budget.

These tests don't exercise a real LLM — they patch the engine's
``reanalyze_task`` and the dedup arbiter's ``create_message`` to raise
the same shape of error the live trace showed. Pass criterion: each
sweep makes EXACTLY 2 attempts before breaking out.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import patch


def _bootstrap_env() -> None:
    """Engine modules read settings at import time. Set the bare
    minimum so they don't blow up before we can patch them."""
    os.environ.setdefault("EMAIL_ADDRESS", "test@example.com")
    os.environ.setdefault("OWNER_ID", "test_owner")
    os.environ.setdefault("ZYLCH_PROFILE_DIR", "/tmp/mrcall-test-profile")
    os.environ.setdefault("ANTHROPIC_API_KEY", "fake-key-for-test")
    os.makedirs("/tmp/mrcall-test-profile", exist_ok=True)


_bootstrap_env()


def test_reanalyze_sweep_aborts_on_2_consecutive_overload() -> None:
    """``_reanalyze_sweep`` must break out after 2 consecutive 529s."""
    from zylch.services.process_pipeline import _reanalyze_sweep

    fake_tasks = [
        {
            "id": f"task-{i:02d}",
            "completed_at": None,
            "action_required": True,
            "analyzed_at": "2026-04-01T00:00:00+00:00",
        }
        for i in range(10)
    ]

    call_count = 0

    async def mock_reanalyze(task_id, owner_id):
        nonlocal call_count
        call_count += 1
        return {
            "ok": False,
            "error": (
                "LLM error: Error code: 529 - {'type': 'error', "
                "'error': {'type': 'overloaded_error', 'message': 'Overloaded'}}"
            ),
            "task_id": task_id,
        }

    with patch(
        "zylch.workers.task_reanalyze.reanalyze_task",
        side_effect=mock_reanalyze,
    ):
        result = asyncio.run(_reanalyze_sweep("test_owner", store=None, tasks=fake_tasks))

    assert call_count == 2, (
        f"Expected sweep to abort after 2 consecutive 529s, got {call_count} calls."
    )
    assert result == 0, f"Expected 0 successful reanalyses, got {result}"


def test_dedup_sweep_aborts_on_2_consecutive_overload() -> None:
    """``run_dedup_sweep`` must break out after 2 consecutive 529s."""
    fake_tasks = []
    for cluster_i in range(5):
        for j in range(2):
            fake_tasks.append(
                {
                    "id": f"task-c{cluster_i}-{j}",
                    "owner_id": "test_owner",
                    "contact_email": f"user{cluster_i}@example.com",
                    "urgency": "medium",
                    "suggested_action": f"do thing {cluster_i}.{j}",
                    "reason": "x",
                    "created_at": "2026-04-01",
                    "completed_at": None,
                    "action_required": True,
                    "sources": {},
                    "dedup_skip_until": None,
                }
            )

    call_count = 0

    async def mock_create_message(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Mirror the shape of `anthropic._exceptions.OverloadedError`
        # without depending on the SDK's class hierarchy: the abort
        # guard only inspects the string form of the exception.
        raise RuntimeError(
            "Error code: 529 - {'type': 'error', 'error': "
            "{'type': 'overloaded_error', 'message': 'Overloaded'}}"
        )

    from zylch.workers import task_dedup_sweep
    from zylch.storage import storage as storage_module

    class FakeStorage:
        def __init__(self, tasks):
            self.tasks = tasks

        def get_task_items(self, owner_id, action_required, limit):
            return self.tasks

        def complete_task_item(self, owner_id, task_id, note=None):
            return True

    fake_store = FakeStorage(fake_tasks)

    class FakeClient:
        async def create_message(self, **kwargs):
            return await mock_create_message(**kwargs)

    with patch.object(
        storage_module.Storage, "get_instance", return_value=fake_store
    ), patch("zylch.llm.try_make_llm_client", return_value=FakeClient()):
        summary = asyncio.run(task_dedup_sweep.run_dedup_sweep("test_owner"))

    assert call_count == 2, (
        f"Expected dedup sweep to abort after 2 consecutive 529s, got {call_count} calls."
    )
    assert summary["aborted_overload"] is True, (
        f"Expected aborted_overload=True in summary, got {summary}"
    )


if __name__ == "__main__":
    test_reanalyze_sweep_aborts_on_2_consecutive_overload()
    print("✓ _reanalyze_sweep aborts after 2 consecutive 529s")
    test_dedup_sweep_aborts_on_2_consecutive_overload()
    print("✓ run_dedup_sweep aborts after 2 consecutive 529s")
    print("\nAll overload abort tests PASS")
