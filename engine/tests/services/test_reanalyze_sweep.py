"""Tests for the F4 reanalyze sweep in `process_pipeline._reanalyze_sweep`.

Defense-in-depth pass over open tasks: bounded by age threshold + cap,
oldest-first, skips completed tasks, tolerates reanalyze failures.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from zylch.services import process_pipeline


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _stale(hours_ago: float, task_id: str) -> dict:
    """Build a fake open task with `analyzed_at` that many hours in the past."""
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {
        "id": task_id,
        "completed_at": None,
        "action_required": True,
        "analyzed_at": _iso(ts),
        "created_at": _iso(ts),
    }


@pytest.mark.asyncio
async def test_sweep_skips_when_no_candidates_old_enough():
    """Tasks all younger than the age threshold => no sweep, returns 0."""
    fresh_tasks = [_stale(1.0, "t-fresh-1"), _stale(2.0, "t-fresh-2")]
    with patch(
        "zylch.workers.task_reanalyze.reanalyze_task",
        new_callable=AsyncMock,
    ) as mock_re:
        result = await process_pipeline._reanalyze_sweep("owner", None, fresh_tasks)
    assert result == 0
    mock_re.assert_not_called()


@pytest.mark.asyncio
async def test_sweep_processes_oldest_first_up_to_cap():
    """If 15 stale tasks are eligible, only REANALYZE_CAP=10 oldest run."""
    # Mix ages so order matters: 15 stale tasks, ages 25h..39h.
    tasks = [_stale(25.0 + i, f"t-{i:02d}") for i in range(15)]

    with patch(
        "zylch.workers.task_reanalyze.reanalyze_task",
        new_callable=AsyncMock,
    ) as mock_re:
        mock_re.return_value = {"ok": True, "action": "kept"}
        result = await process_pipeline._reanalyze_sweep("owner", None, tasks)

    assert result == process_pipeline.REANALYZE_CAP == 10
    # The 10 oldest are t-14 (39h), t-13, ..., t-05 (30h). Order: oldest first.
    swept_ids = [c.args[0] for c in mock_re.call_args_list]
    assert swept_ids[0] == "t-14"  # oldest
    assert swept_ids[-1] == "t-05"  # 10th oldest


@pytest.mark.asyncio
async def test_sweep_skips_completed_tasks():
    """Completed tasks must not be reanalyzed even if 'analyzed_at' is old."""
    tasks = [
        {**_stale(48.0, "t-done"), "completed_at": _iso(datetime.now(timezone.utc))},
        _stale(48.0, "t-open"),
    ]
    with patch(
        "zylch.workers.task_reanalyze.reanalyze_task",
        new_callable=AsyncMock,
    ) as mock_re:
        mock_re.return_value = {"ok": True, "action": "kept"}
        await process_pipeline._reanalyze_sweep("owner", None, tasks)

    swept_ids = [c.args[0] for c in mock_re.call_args_list]
    assert swept_ids == ["t-open"]


@pytest.mark.asyncio
async def test_sweep_tolerates_reanalyze_exception():
    """If reanalyze_task raises, the sweep continues with the next task."""
    tasks = [_stale(48.0, "t-bad"), _stale(36.0, "t-good")]
    with patch(
        "zylch.workers.task_reanalyze.reanalyze_task",
        new_callable=AsyncMock,
    ) as mock_re:
        mock_re.side_effect = [
            RuntimeError("simulated LLM failure"),
            {"ok": True, "action": "closed"},
        ]
        result = await process_pipeline._reanalyze_sweep("owner", None, tasks)
    # 1 succeeded out of 2; the exception didn't bubble up.
    assert result == 1
    assert mock_re.call_count == 2


@pytest.mark.asyncio
async def test_sweep_uses_created_at_when_analyzed_at_missing():
    """Older tasks with no analyzed_at must still be eligible via created_at."""
    ts_old = datetime.now(timezone.utc) - timedelta(hours=48)
    tasks = [
        {
            "id": "t-no-analyze",
            "completed_at": None,
            "action_required": True,
            "analyzed_at": None,
            "created_at": _iso(ts_old),
        }
    ]
    with patch(
        "zylch.workers.task_reanalyze.reanalyze_task",
        new_callable=AsyncMock,
    ) as mock_re:
        mock_re.return_value = {"ok": True, "action": "kept"}
        result = await process_pipeline._reanalyze_sweep("owner", None, tasks)
    assert result == 1
    swept_ids = [c.args[0] for c in mock_re.call_args_list]
    assert swept_ids == ["t-no-analyze"]


@pytest.mark.asyncio
async def test_sweep_skips_action_required_false():
    """Tasks marked action_required=False must not be reanalyzed."""
    tasks = [
        {**_stale(48.0, "t-noaction"), "action_required": False},
        _stale(48.0, "t-action"),
    ]
    with patch(
        "zylch.workers.task_reanalyze.reanalyze_task",
        new_callable=AsyncMock,
    ) as mock_re:
        mock_re.return_value = {"ok": True, "action": "kept"}
        await process_pipeline._reanalyze_sweep("owner", None, tasks)
    swept_ids = [c.args[0] for c in mock_re.call_args_list]
    assert swept_ids == ["t-action"]
