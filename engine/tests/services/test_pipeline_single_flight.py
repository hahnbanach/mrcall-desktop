"""One pipeline run at a time, across threads and across event loops.

`handle_process` has three ways in — the chat `/update` command, the
JSON-RPC `update.run`, and the headless auto-update tick that goes
through `update.run` on a timer — and they all live in the one `zylch
serve` process. Before the guard, an operator asking for a catch-up
while the timer was mid-tick got two passes over the same mail: the
LLM bill paid twice, and two writers on the task ledger.

The overlap that actually happens is between DIFFERENT event loops:
`update.run` runs the pipeline through `asyncio.to_thread(asyncio.run,
…)`, so the second caller is on another thread with a loop of its own.
That is why the guard is a `threading.Lock`; an `asyncio.Lock` would
be held on one loop and unseen by the other, and the first test below
is the one that would catch a regression back to it.

`_run_pipeline` is stubbed throughout — what is under test is who gets
admitted, not what the pipeline does once it is in.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from zylch.services import process_pipeline
from zylch.services.process_pipeline import PIPELINE_BUSY_MESSAGE, PipelineBusy


@pytest.fixture
def stub_pipeline(monkeypatch):
    """Replace the pipeline body with something observable.

    Returns a record dict: `calls` counts entries, `args` keeps the
    args list each entry was given.
    """
    record = {"calls": 0, "args": []}

    def _install(body=None):
        record["calls"] = 0
        record["args"] = []

        async def _default(args, config, owner_id, progress=None, errors_out=None):
            return "pipeline ran"

        inner = body or _default

        async def _tracked(args, config, owner_id, progress=None, errors_out=None):
            record["calls"] += 1
            record["args"].append(list(args))
            return await inner(args, config, owner_id, progress, errors_out)

        monkeypatch.setattr(process_pipeline, "_run_pipeline", _tracked)
        return record

    return _install


def _run(args=None, progress=None):
    """Drive `handle_process` on a fresh event loop, as its callers do."""
    return asyncio.run(
        process_pipeline.handle_process(args or [], None, "owner-uid", progress=progress)
    )


# ─── the overlap the guard exists for ─────────────────────────────────


def test_a_second_caller_on_another_event_loop_is_refused(stub_pipeline):
    """The regression guard for `threading.Lock` vs `asyncio.Lock`.

    The holder runs on a background thread's loop; the challenger runs
    on this thread's loop. An asyncio primitive would let both in.
    """
    entered = threading.Event()
    may_finish = threading.Event()

    async def _blocking(args, config, owner_id, progress=None, errors_out=None):
        entered.set()
        await asyncio.to_thread(may_finish.wait, 10)
        return "pipeline ran"

    record = stub_pipeline(_blocking)

    holder_result = {}

    def _hold():
        holder_result["value"] = _run()

    holder = threading.Thread(target=_hold, name="holder")
    holder.start()
    try:
        assert entered.wait(10), "the first run never started"
        assert _run() == PIPELINE_BUSY_MESSAGE
        # The refused caller did not reach the pipeline at all.
        assert record["calls"] == 1
    finally:
        may_finish.set()
        holder.join(10)

    assert holder_result["value"] == "pipeline ran"
    assert record["calls"] == 1


def test_the_refused_caller_is_told_it_is_at_100_percent(stub_pipeline):
    """A progress subscriber must not be left hanging at 0% forever."""
    entered = threading.Event()
    may_finish = threading.Event()

    async def _blocking(args, config, owner_id, progress=None, errors_out=None):
        entered.set()
        await asyncio.to_thread(may_finish.wait, 10)
        return "pipeline ran"

    stub_pipeline(_blocking)
    seen: list = []

    holder = threading.Thread(target=_run, name="holder")
    holder.start()
    try:
        assert entered.wait(10)
        _run(progress=lambda pct, msg, eta: seen.append((pct, msg)))
    finally:
        may_finish.set()
        holder.join(10)

    assert seen and seen[-1][0] == 100
    assert "already running" in seen[-1][1].lower()


def test_a_progress_subscriber_that_throws_does_not_change_the_answer(stub_pipeline):
    """Same tolerance the pipeline's own `_p` has: a bad subscriber is
    the subscriber's problem."""
    entered = threading.Event()
    may_finish = threading.Event()

    async def _blocking(args, config, owner_id, progress=None, errors_out=None):
        entered.set()
        await asyncio.to_thread(may_finish.wait, 10)
        return "pipeline ran"

    stub_pipeline(_blocking)

    def _explode(pct, msg, eta):
        raise RuntimeError("bad subscriber")

    holder = threading.Thread(target=_run, name="holder")
    holder.start()
    try:
        assert entered.wait(10)
        assert _run(progress=_explode) == PIPELINE_BUSY_MESSAGE
    finally:
        may_finish.set()
        holder.join(10)


# ─── the guard does not outstay the run ───────────────────────────────


def test_runs_one_after_another_are_all_admitted(stub_pipeline):
    record = stub_pipeline()
    assert _run() == "pipeline ran"
    assert _run() == "pipeline ran"
    assert record["calls"] == 2


def test_a_crashing_run_still_releases_the_guard(stub_pipeline):
    """Otherwise one bad tick would wedge the pipeline until restart."""

    async def _boom(args, config, owner_id, progress=None, errors_out=None):
        raise RuntimeError("pipeline exploded")

    stub_pipeline(_boom)
    with pytest.raises(RuntimeError, match="pipeline exploded"):
        _run()

    record = stub_pipeline()
    assert _run() == "pipeline ran"
    assert record["calls"] == 1


def test_nothing_holds_the_guard_between_tests():
    assert process_pipeline.pipeline_running_for() is None


# ─── what the guard does not gate ─────────────────────────────────────


def test_help_is_answered_while_a_run_is_in_flight(stub_pipeline):
    """Asking what the command does is not a second pass over the mail."""
    entered = threading.Event()
    may_finish = threading.Event()

    async def _blocking(args, config, owner_id, progress=None, errors_out=None):
        if "--help" in args:
            return "**Full Pipeline**"
        entered.set()
        await asyncio.to_thread(may_finish.wait, 10)
        return "pipeline ran"

    stub_pipeline(_blocking)

    holder = threading.Thread(target=_run, name="holder")
    holder.start()
    try:
        assert entered.wait(10)
        assert _run(["--help"]) == "**Full Pipeline**"
    finally:
        may_finish.set()
        holder.join(10)


# ─── the primitive itself ─────────────────────────────────────────────


def test_the_guard_refuses_reentry_and_names_the_holder():
    with process_pipeline.pipeline_single_flight("scheduled-tick"):
        with pytest.raises(PipelineBusy, match="scheduled-tick"):
            with process_pipeline.pipeline_single_flight("catch-up"):
                pytest.fail("two holders were admitted at once")


def test_the_run_clock_starts_and_stops_with_the_run():
    assert process_pipeline.pipeline_running_for() is None
    with process_pipeline.pipeline_single_flight("scheduled-tick"):
        assert process_pipeline.pipeline_running_for() is not None
    assert process_pipeline.pipeline_running_for() is None
