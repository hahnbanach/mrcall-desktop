"""Which tools run in a thread, and why it is not "all of them".

Two properties pull in opposite directions. A tool that blocks — imaplib,
smtplib, a subprocess, an ONNX encode — must not run on the event loop,
or it stops the keepalive, every other RPC, and the loop's ability to act
on a cancellation. But `run_in_executor` cannot interrupt a thread that
has started, so moving an *interruptible* tool into one throws its
interruptibility away: a turn cancelled while `compose_email` awaited the
LLM used to write its draft anyway, seconds after the caller had been
told the turn was over.

So the offload is a named list, and this file pins the two halves of it:
a blocking tool goes to a worker thread, an awaiting tool stays where a
cancellation can reach it.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from zylch.assistant import core
from zylch.tools.base import Tool, ToolResult, ToolStatus


class _RecordingTool(Tool):
    """Reports the thread it ran on, and can be held open."""

    def __init__(self, name: str, hold: float = 0.0):
        super().__init__(name=name, description="test tool")
        self.hold = hold
        self.ran_on: str = ""
        self.started = threading.Event()
        self.finished = threading.Event()

    async def execute(self, **_kwargs) -> ToolResult:
        self.ran_on = threading.current_thread().name
        self.started.set()
        if self.hold:
            await asyncio.sleep(self.hold)
        self.finished.set()
        return ToolResult(status=ToolStatus.SUCCESS, data={}, message="ran")

    def get_schema(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": {}}


def _agent(tool: Tool):
    agent = core.ZylchAIAgent.__new__(core.ZylchAIAgent)
    agent.tool_map = {tool.name: tool}
    return agent


# ─── The two halves of the policy ─────────────────────────────────────


def test_a_blocking_tool_runs_off_the_event_loop():
    tool = _RecordingTool("sync_emails")
    assert tool.name in core._BLOCKING_TOOLS

    result = asyncio.run(_agent(tool)._call_tool("sync_emails", {}))

    assert result.status == ToolStatus.SUCCESS
    assert tool.ran_on.startswith("zylch-tool")


def test_an_awaiting_tool_stays_on_the_event_loop():
    tool = _RecordingTool("compose_email")
    assert tool.name not in core._BLOCKING_TOOLS

    result = asyncio.run(_agent(tool)._call_tool("compose_email", {}))

    assert result.status == ToolStatus.SUCCESS
    assert not tool.ran_on.startswith("zylch-tool")


def test_cancelling_stops_an_on_loop_tool_where_it_awaits():
    """The property the offload would have destroyed."""
    tool = _RecordingTool("compose_email", hold=0.3)
    agent = _agent(tool)

    async def scenario():
        task = asyncio.create_task(agent._call_tool("compose_email", {}))
        for _ in range(500):
            if tool.started.is_set():
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Well past the point where an uninterrupted body would finish.
        await asyncio.sleep(1.0)

    asyncio.run(scenario())

    assert tool.started.is_set()
    assert not tool.finished.is_set()


def test_a_cancelled_turn_never_starts_a_queued_blocking_tool():
    """A thread cannot be interrupted, so the last moment to stop is
    before it begins.

    With every worker busy, a second blocking tool sits in the queue.
    Cancelling its turn must mean it never runs at all — not that it runs
    for nobody.
    """
    from concurrent.futures import ThreadPoolExecutor

    occupied = _RecordingTool("sync_emails", hold=1.0)
    queued = _RecordingTool("search_provider_emails")
    agent = core.ZylchAIAgent.__new__(core.ZylchAIAgent)
    agent.tool_map = {occupied.name: occupied, queued.name: queued}

    single = ThreadPoolExecutor(max_workers=1, thread_name_prefix="zylch-tool")
    original, core._tool_executor = core._tool_executor, single
    try:

        async def scenario():
            busy = asyncio.create_task(agent._call_tool("sync_emails", {}))
            for _ in range(500):  # let the only worker pick it up
                if occupied.started.is_set():
                    break
                await asyncio.sleep(0.01)
            assert occupied.started.is_set()
            waiting = asyncio.create_task(agent._call_tool("search_provider_emails", {}))
            await asyncio.sleep(0.05)
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            await busy

        asyncio.run(scenario())
    finally:
        core._tool_executor = original
        single.shutdown(wait=True)

    assert occupied.finished.is_set()
    assert not queued.started.is_set()


def test_every_offloaded_name_is_a_tool_that_exists():
    """A renamed tool must not fall off the list unnoticed.

    The list is keyed by tool name, so a rename silently sends the tool
    back onto the event loop — no error, just a loop that stalls again.
    Read the names the tool modules actually register and compare.
    """
    import ast
    from pathlib import Path

    registered = set()
    tools_dir = Path(core.__file__).resolve().parent.parent / "tools"
    for path in tools_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    if isinstance(keyword.value.value, str):
                        registered.add(keyword.value.value)

    assert core._BLOCKING_TOOLS <= registered, sorted(core._BLOCKING_TOOLS - registered)
