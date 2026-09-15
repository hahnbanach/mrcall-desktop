"""Completion compatibility never turns incomplete or malformed turns into actions."""

from types import SimpleNamespace as NS

import pytest
from zylch.llm.client import LLMResponse


def tool(**changes):
    return NS(
        **{"type": "tool_use", "id": "tool-1", "name": "task_decision", "input": {}, **changes}
    )


@pytest.mark.parametrize("blocks", [[tool()], [NS(type="text", text=""), tool()]])
def test_complete_tools_normalize_without_mutating_raw(blocks):
    raw = NS(stop_reason="end_turn", content=blocks)
    response = LLMResponse(raw)
    assert response.stop_reason == "tool_use"
    assert response.original_stop_reason == "end_turn"
    assert response._raw is raw
    assert raw.stop_reason == "end_turn"
    assert LLMResponse(raw, normalize_tool_completion=False).stop_reason == "end_turn"


@pytest.mark.parametrize(
    "blocks",
    [
        [],
        [NS(type="text", text="Done")],
        [NS(type="text", text=None), tool()],
        [tool(id=None)],
        [tool(id="")],
        [tool(id="  ")],
        [tool(name=None)],
        [tool(name="")],
        [tool(name="  ")],
        [tool(input=None)],
        [tool(input=[])],
        [tool(), tool(input=[])],
        [tool(), NS(type="refusal", refusal="refused")],
        [tool(), NS(type="thinking", thinking="private")],
        [tool(refusal="refused")],
        [tool(), {}],
    ],
)
def test_malformed_or_refused_blocks_never_normalize(blocks):
    assert LLMResponse(NS(stop_reason="end_turn", content=blocks)).stop_reason == "end_turn"


@pytest.mark.parametrize("reason", ["max_tokens", "refusal", "stop_sequence", None, "pause_turn"])
def test_non_end_turn_never_normalizes(reason):
    assert LLMResponse(NS(stop_reason=reason, content=[tool()])).stop_reason == reason


def test_top_level_refusal_never_normalizes():
    assert (
        LLMResponse(NS(stop_reason="end_turn", content=[tool()], refusal="denied")).stop_reason
        == "end_turn"
    )
