"""A tool result over budget reaches the model cut and marked, never whole.

The agent loop formatted every tool result verbatim and appended it to the
conversation. Nothing between a tool and the next LLM call measured
anything, so two local searches produced a 1.4 MB step and the call was
rejected upstream — after the tool had "succeeded". Incident:
`~/hb/docs/known-issues/2026-09-08-engine-chat-prompt-unbounded.md`.

The bound is generic: it applies to every tool, so no future tool can
repeat this. It is loud: a marker the model reads, a WARNING line, and a
record on the agent that `chat.send` surfaces in its metadata.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

from zylch.assistant import budget, core
from zylch.tools.base import Tool, ToolResult, ToolStatus


class _SizedTool(Tool):
    def __init__(self, name: str, chars: int):
        super().__init__(name=name, description="test tool")
        self.chars = chars

    async def execute(self, **_kwargs) -> ToolResult:
        return ToolResult(status=ToolStatus.SUCCESS, data=None, message="x" * self.chars)

    def get_schema(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": {}}


def _agent(tool: Tool) -> core.ZylchAIAgent:
    agent = core.ZylchAIAgent.__new__(core.ZylchAIAgent)
    agent.tool_map = {tool.name: tool}
    agent.last_truncations = []
    return agent


def _use(tool: Tool):
    return SimpleNamespace(type="tool_use", id="tu_1", name=tool.name, input={})


def test_an_oversized_result_is_cut_marked_logged_and_recorded(caplog):
    tool = _SizedTool("probe_search", 500_000)
    agent = _agent(tool)

    with caplog.at_level(logging.WARNING, logger="zylch.assistant.core"):
        results, direct = asyncio.run(agent._execute_tools([_use(tool)]))

    content = results[0]["content"]
    assert direct is None
    assert len(content) < budget.TOOL_RESULT_MAX_CHARS + 600
    assert "[TOOL RESULT TRUNCATED: probe_search returned" in content
    assert "Do not call update_memory or create_memory from a partial result" in content
    assert agent.last_truncations == [
        {
            "tool": "probe_search",
            "original_chars": len(
                agent._format_tool_result(
                    ToolResult(status=ToolStatus.SUCCESS, data=None, message="x" * 500_000)
                )
            ),
            "shown_chars": budget.TOOL_RESULT_MAX_CHARS,
        }
    ]
    assert any(
        "truncated" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records
    )


def test_a_result_within_budget_is_byte_identical():
    tool = _SizedTool("probe_search", 1_000)
    agent = _agent(tool)

    results, _ = asyncio.run(agent._execute_tools([_use(tool)]))

    expected = agent._format_tool_result(
        ToolResult(status=ToolStatus.SUCCESS, data=None, message="x" * 1_000)
    )
    assert results[0]["content"] == expected
    assert agent.last_truncations == []
