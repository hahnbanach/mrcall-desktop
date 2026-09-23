"""The interactive CLI solve installs the solve context, so it can correct memory.

Milestone 4 declared this surface unconverted: `_cli_run_executor` ran the
executor with no solve context, so `update_memory` answered "no task behind
this" and wrote nothing. Milestone 5 installs the context in the one runner all
three CLI sites go through; what this proves is that the event the solve
adapter builds from a CLI run carries the typed instruction as its observation,
exactly as it does over RPC.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from zylch.memory.mnemonic.contracts import OPERATOR_DELEGATED
from zylch.services import task_interactive
from zylch.services.solve_context import current_solve
from zylch.services.solve_memory import solve_context_from_task


@pytest.fixture(autouse=True)
def quiet_console(monkeypatch):
    monkeypatch.setattr(task_interactive, "console", SimpleNamespace(print=lambda *a, **k: None))


def test_the_runner_installs_the_solve_context_around_the_loop(monkeypatch):
    """Seen from inside the executor, the context is the CLI's typed instruction."""
    seen = {}

    class Executor:
        messages = []

        async def run(self):
            seen["context"] = current_solve()
            yield {"type": "done", "result": {"messages": []}}

    context = solve_context_from_task(
        {"id": "t1", "title": "Preventivo Beta"}, "Correggi l'indirizzo ordini di Beta"
    )
    task_interactive._cli_run_executor(Executor(), context)

    assert seen["context"] is not None
    assert seen["context"].task_id == "t1"
    assert seen["context"].observation == "Correggi l'indirizzo ordini di Beta"
    assert seen["context"].human_asked is True


def test_the_context_reaches_the_memory_adapter_on_a_worker_thread(monkeypatch):
    """The executor hops the tool onto a thread with a copied context; the
    adapter builds its event from what the CLI typed, not from nothing."""
    import asyncio
    import contextvars

    from zylch.memory.mnemonic import commit as commit_mod
    from zylch.memory.mnemonic.proposals import MnemonicResult
    from zylch.services import solve_memory

    captured = {}

    def capture(event, **kwargs):
        captured["event"] = event
        return MnemonicResult.review_needed(event.event_id, "captured")

    monkeypatch.setattr(commit_mod, "submit", capture)
    import zylch.memory.mnemonic as pkg

    monkeypatch.setattr(pkg, "submit", capture)
    monkeypatch.setattr(
        "zylch.memory.company_key.require_company_key", lambda: "AAAAAAAAAAAAAAAAAAAAAA"
    )

    class Executor:
        messages = []

        async def run(self):
            loop = asyncio.get_event_loop()
            ctx = contextvars.copy_context()
            await loop.run_in_executor(
                None,
                lambda: ctx.run(
                    solve_memory.update_memory,
                    {"query": "Beta", "new_content": "orders@beta.test"},
                    None,
                    "uid-a",
                ),
            )
            yield {"type": "done", "result": {"messages": []}}

    context = solve_context_from_task({"id": "t7", "title": "x"}, "Beta ordina da orders@beta.test")
    task_interactive._cli_run_executor(Executor(), context)

    event = captured["event"]
    assert event.observation == "Beta ordina da orders@beta.test"
    assert event.source_id == "task:t7"
    assert event.caller_class == OPERATOR_DELEGATED


def test_every_cli_site_passes_a_context_built_from_its_own_task():
    """The three constructions go through one runner and none of them forgets."""
    import inspect

    source = inspect.getsource(task_interactive)
    calls = [
        line
        for line in source.splitlines()
        if "_cli_run_executor(executor," in line and not line.lstrip().startswith("def ")
    ]
    assert len(calls) == 3, calls
    assert all("solve_context_from_task(task" in line for line in calls), calls
