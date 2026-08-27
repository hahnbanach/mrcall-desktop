"""`update.run` says "already running" instead of "no changes".

The pipeline's single-flight guard refuses a second concurrent run
(`tests/services/test_pipeline_single_flight.py`). What that means on
the wire is this method's job: a refused call must not come back
looking like a pass that ran and found nothing, because the caller —
an operator catch-up, the desktop Update card — would then present
stale state as fresh. It comes back `busy`, with `success` false and an
empty diff.
"""

from __future__ import annotations

import asyncio

import pytest

from zylch.rpc import methods
from zylch.services import process_pipeline
from zylch.services.process_pipeline import PIPELINE_BUSY_MESSAGE


class _Store:
    def get_task_items(self, **_kwargs):
        return []


def _notify(*_a, **_k):
    return None


@pytest.fixture
def wired(monkeypatch):
    """A profile `update.run` will accept, and a pipeline it never enters."""

    def _install(pipeline_returns):
        async def _pipeline(args, config, owner_id, progress=None, errors_out=None):
            return pipeline_returns

        monkeypatch.setenv("EMAIL_ADDRESS", "support@example.test")
        monkeypatch.setenv("EMAIL_PASSWORD", "not-a-real-password")
        monkeypatch.setattr("zylch.cli.utils.get_owner_id", lambda: "owner-uid")
        monkeypatch.setattr("zylch.storage.storage.Storage.get_instance", lambda: _Store())
        monkeypatch.setattr(process_pipeline, "handle_process", _pipeline)

    return _install


def _call():
    return asyncio.run(methods.update_run({}, _notify))


def test_a_refused_run_is_reported_as_busy_not_as_a_clean_pass(wired):
    wired(PIPELINE_BUSY_MESSAGE)
    res = _call()
    assert res["busy"] is True
    assert res["success"] is False
    assert res["summary"] == PIPELINE_BUSY_MESSAGE
    assert res["updated_tasks"] == {"created": [], "closed": [], "updated": []}


def test_the_busy_answer_carries_no_invented_errors(wired):
    """Nothing failed. A refusal must not surface in the UI as a fault."""
    wired(PIPELINE_BUSY_MESSAGE)
    assert _call()["errors"] == []


def test_a_run_that_did_happen_is_not_busy(wired):
    wired("13 action items detected")
    res = _call()
    assert res["busy"] is False
    assert res["success"] is True


def test_the_progress_stream_ends_at_100_on_a_refusal(wired):
    wired(PIPELINE_BUSY_MESSAGE)
    seen: list = []

    def _capture(method, params):
        if method == "update.progress":
            seen.append((params.get("pct"), params.get("message")))

    asyncio.run(methods.update_run({}, _capture))
    assert seen and seen[-1] == (100, "Already running")
