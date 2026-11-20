"""Capture harness for REANALYZE (call site ``f4.reanalyze``).

Drives ``zylch.workers.task_reanalyze.reanalyze_task`` — the function the
F4 sweep, the ``tasks.reanalyze`` RPC and the CLI ``/update <task_id>``
all call, and the one that builds and sends the request — on a disposable
profile seeded with the case: the trained task prompt of its profile owner
(the reanalysis system prompt), the task under review and the emails of its
thread (and of any related thread with the same contact). The engine
renders the thread history, resolves who is waiting and builds the user
message itself; a capturing client records the request, and the function
returns its "no decision" result without touching the task.

Nothing of the engine is replaced: the profile owners and their trained
prompt are the ones of the TASK_DETECTION cases (``load_profiles``),
because in production both roles send the same trained prompt.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any


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

ROLE = "REANALYZE"
ROLE_KEY = "MODEL_REANALYZE"
TOOL = "reanalyze_decision"
# Modules whose clock reaches the request: today's date, the waiting
# state's "N days ago", the 60-day window of related threads.
CLOCK_MODULES = (
    "zylch.workers.task_reanalyze",
    "zylch.workers.thread_presenter",
    "zylch.storage.storage",
)


def build_requests(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One captured request per case, in case order (synchronous; no network)."""
    profiles = env.load_profiles()
    return [_capture(case, profiles[case["input"]["profile"]]) for case in cases]


def _capture(case: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    from zylch.workers.task_reanalyze import reanalyze_task

    spec = case["input"]
    with ExitStack() as stack:
        stack.enter_context(env.disposable_profile(profile["environment"]))
        stack.enter_context(env.frozen_clock(env.parse_instant(spec["now"]), CLOCK_MODULES))
        client = stack.enter_context(env.capturing_llm())
        env.seed_trained_prompt(profile["trained_prompt"])
        env.seed_emails(spec["emails"])
        env.seed_task(spec["task"])
        asyncio.run(reanalyze_task(spec["task"]["id"], env.OWNER_ID))
    return env.single_request(case, client, ROLE_KEY)
