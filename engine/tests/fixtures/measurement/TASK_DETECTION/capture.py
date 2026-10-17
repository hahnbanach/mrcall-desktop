"""Capture harness for TASK_DETECTION (call site ``task.detect``).

Drives the engine's production entry for task detection,
``TaskWorker(...).get_tasks(refresh=True)``, whose email branch
(``zylch.workers.task_creation_email.analyze_recent_email_events``) builds
the thread history, the existing-task context and the memory context, and
hands them to ``TaskWorker._analyze_event``, the method that builds and
sends the request. Each case runs on a disposable profile seeded with its
mailbox: the trained task prompt of its profile owner, the thread's emails
(the newest one ``pending``, the earlier ones already task-processed), the
open tasks and the contact's memory blob. A capturing client records the
request; the worker then takes its "no decision" path.

Replaced, because they need the embedding model: the embedding engine and
the hybrid search that fetches the contact's memory blob, which answers
with the case's ``memory`` entry for the queried address, as the search
returns the contact's blob. Everything else is the engine's own code.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
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

ROLE = "TASK_DETECTION"
ROLE_KEY = "MODEL_TASK_DETECTION"
TOOL = "task_decision"
# Modules whose clock reaches the request: the detection date line, the
# thread history's timestamps, the storage queries behind the context.
CLOCK_MODULES = (
    "zylch.workers.task_creation",
    "zylch.workers.thread_presenter",
    "zylch.storage.storage",
)


class _MemoryLookup:
    """The hybrid search as the task worker calls it: one blob per contact address."""

    def __init__(self, memory: list[dict[str, str]]) -> None:
        self._by_contact = {entry["contact"].lower(): entry for entry in memory}

    def search(self, owner_id: str, query: str, namespace: str = "", limit: int = 1, **_: Any):
        entry = self._by_contact.get((query or "").strip().lower())
        if entry is None:
            return []
        return [SimpleNamespace(content=entry["content"], blob_id=entry["blob_id"])]


def build_requests(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One captured request per case, in case order (synchronous; no network)."""
    profiles = env.load_profiles()
    return [_capture(case, profiles[case["input"]["profile"]]) for case in cases]


def _capture(case: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    from zylch.storage.storage import Storage
    from zylch.workers import task_creation

    spec = case["input"]
    memory = _MemoryLookup(spec.get("memory", []))
    with ExitStack() as stack:
        stack.enter_context(env.disposable_profile(profile["environment"]))
        stack.enter_context(env.frozen_clock(env.parse_instant(spec["now"]), CLOCK_MODULES))
        client = stack.enter_context(
            env.capturing_llm(("zylch.workers.task_creation.make_llm_client",))
        )
        stack.enter_context(mock.patch.object(task_creation, "EmbeddingEngine", lambda *a: None))
        stack.enter_context(
            mock.patch.object(task_creation, "HybridSearchEngine", lambda *a: memory)
        )
        env.seed_trained_prompt(profile["trained_prompt"])
        env.seed_emails(spec["emails"])
        for task in spec.get("open_tasks", []):
            env.seed_task(task)
        worker = task_creation.TaskWorker(
            storage=Storage.get_instance(),
            owner_id=env.OWNER_ID,
            user_email=profile["environment"]["EMAIL_ADDRESS"],
        )
        asyncio.run(worker.get_tasks(refresh=True))
    return env.single_request(case, client, ROLE_KEY)
