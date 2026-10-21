"""Capture harness for DEDUP (call sites ``dedup.f8`` and ``dedup.f9``).

The role has two call sites, and each case names its own in
``call_site``:

- ``dedup.f8`` — ``zylch.workers.task_dedup_sweep.run_dedup_sweep``
  clusters the open tasks (shared contact, shared thread, or blob overlap
  between tasks of the same party) and asks the arbiter about each
  cluster. A case seeds exactly one cluster, so the sweep sends one
  request.
- ``dedup.f9`` — ``zylch.workers.task_topic_dedup.run_topic_dedup`` sends
  every open task (at least four) in one request and asks for the
  clusters of the same problem for the same party.

Each case runs on a disposable profile seeded with its open tasks; the
sweep builds the request itself and a capturing client records it; the
sweep then takes its "no tool_use" path and closes nothing.

Nothing of the engine is replaced. The topic sweep reads today's date
inside ``run_topic_dedup``; the harness hands its prompt builder the
case's ``now`` instead, so the request is the same on any day.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any
from unittest import mock


def _shared_env():
    """``tests/measurement/task_roles_env.py`` of this checkout, imported once.

    Loaded by path, so a script needs only ``zylch`` importable; the copy
    pytest already imported as a package module is reused, so there is one
    ``CaptureError`` class per process.
    """
    path = Path(__file__).resolve().parents[3] / "measurement" / "task_roles_env.py"
    for name in ("tests.measurement.task_roles_env", "measurement_task_roles_env"):
        module = sys.modules.get(name)
        if module is not None and Path(module.__file__).resolve() == path:
            return module
    spec = importlib.util.spec_from_file_location("measurement_task_roles_env", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


env = _shared_env()

ROLE = "DEDUP"
ROLE_KEY = "MODEL_DEDUP"
# The tool each call site offers the model; the answer is its input.
TOOLS = {"dedup.f8": "dedup_decision", "dedup.f9": "topic_dedup_decision"}


@contextmanager
def _pinned_today(day: str) -> Iterator[None]:
    """Give the topic sweep's prompt builder ``day`` as today's date."""
    from zylch.workers import task_topic_dedup

    build_prompt = task_topic_dedup._build_prompt

    def pinned(active_tasks, today_iso, *args, **kwargs):
        return build_prompt(active_tasks, day, *args, **kwargs)

    with mock.patch.object(task_topic_dedup, "_build_prompt", pinned):
        yield


def build_requests(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One captured request per case, in case order (synchronous; no network)."""
    return [_capture(case) for case in cases]


def _capture(case: dict[str, Any]) -> dict[str, Any]:
    from zylch.workers.task_dedup_sweep import run_dedup_sweep
    from zylch.workers.task_topic_dedup import run_topic_dedup

    sweeps = {"dedup.f8": run_dedup_sweep, "dedup.f9": run_topic_dedup}
    if case["call_site"] not in sweeps:
        raise env.CaptureError(f"{case['id']}: unknown DEDUP call site {case['call_site']!r}")
    spec = case["input"]
    with ExitStack() as stack:
        stack.enter_context(env.disposable_profile())
        client = stack.enter_context(env.capturing_llm())
        if case["call_site"] == "dedup.f9":
            day = env.parse_instant(spec["now"]).strftime("%Y-%m-%d")
            stack.enter_context(_pinned_today(day))
        for task in spec["open_tasks"]:
            env.seed_task(task)
        asyncio.run(sweeps[case["call_site"]](env.OWNER_ID))
    return env.single_request(case, client, ROLE_KEY)
