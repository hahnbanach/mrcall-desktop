"""Reasoning blocks are parsed, kept, admitted and replayed; stripped only where history is rewritten.

Brief D3: ``thinking`` and ``redacted_thinking`` blocks are never treated as
unsupported content and never dropped from what a caller keeps. ``content``
stays text and tool_use (what callers read); ``assistant_content`` is the
whole turn, in order, as the dicts a tool loop sends back; admission prices
replayed blocks as input; ``without_reasoning`` is the rewrite that leaves
none in the turns it retains. A ``thinking`` block without a signature stays
in what the caller keeps but is never sent back: ``_coerce_messages``, the
history of every request, leaves it out (protocol v2, IR1 m6).
"""

from __future__ import annotations

import copy
from types import SimpleNamespace as NS

import pytest

from zylch.llm.budget_pricing import BudgetError, request_bound
from zylch.llm.response import LLMResponse, _coerce_messages, assistant_blocks, without_reasoning

THINKING = NS(type="thinking", thinking="Look the order up first.", signature="sig-1")
UNSIGNED = NS(type="thinking", thinking="OpenRouter may omit the signature.")
REDACTED = NS(type="redacted_thinking", data="opaque-bytes")
TEXT = NS(type="text", text="Searching.")
TOOL = NS(type="tool_use", id="call-1", name="lookup", input={"q": "order 7"})
TURN = [
    {"type": "thinking", "thinking": "Look the order up first.", "signature": "sig-1"},
    {"type": "redacted_thinking", "data": "opaque-bytes"},
    {"type": "text", "text": "Searching."},
    {"type": "tool_use", "id": "call-1", "name": "lookup", "input": {"q": "order 7"}},
]


def raw(*blocks, stop="tool_use"):
    return NS(stop_reason=stop, content=list(blocks), model="m", usage={"input_tokens": 1})


def test_content_stays_text_and_tool_use_and_assistant_content_keeps_the_whole_turn():
    response = LLMResponse(raw(THINKING, REDACTED, TEXT, TOOL))
    assert [block.type for block in response.content] == ["text", "tool_use"]
    assert response.assistant_content == TURN
    # A fresh list each time: a loop may edit its copy without touching the next.
    response.assistant_content[3]["input"]["q"] = "edited"
    assert response.assistant_content == TURN


def test_an_unsigned_thinking_block_is_kept_for_the_caller_without_an_invented_signature():
    response = LLMResponse(raw(UNSIGNED, TOOL))
    assert response.assistant_content[0] == {
        "type": "thinking",
        "thinking": "OpenRouter may omit the signature.",
    }


def test_an_unsigned_thinking_block_is_left_out_of_the_history_a_request_carries():
    """Protocol v2 (IR1 m6): a ``thinking`` block without a signature — absent,
    None or empty — is never sent back; signed and redacted blocks are, in
    order; a message it alone made up goes too; the caller's list is untouched."""
    unsigned = {"type": "thinking", "thinking": "OpenRouter may omit the signature."}
    history = [
        {"role": "user", "content": "Find order 7."},
        {"role": "assistant", "content": [unsigned, *copy.deepcopy(TURN)]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-1"}]},
        {"role": "assistant", "content": [UNSIGNED, {**unsigned, "signature": None}]},
        {"role": "assistant", "content": [{**unsigned, "signature": ""}, TEXT]},
        {"role": "user", "content": []},
    ]
    before = copy.deepcopy(history)
    sent = _coerce_messages(history)
    assert history == before
    assert sent == [
        history[0],
        {"role": "assistant", "content": TURN},
        history[2],
        {"role": "assistant", "content": [{"type": "text", "text": "Searching."}]},
        history[5],
    ]
    assert LLMResponse(raw(UNSIGNED, TOOL)).assistant_content[0]["type"] == "thinking"


def test_sdk_messages_keep_their_reasoning_blocks():
    from anthropic.types import Message

    message = Message.model_validate(
        {
            "id": "msg",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5-5",
            "content": [
                {"type": "thinking", "thinking": "Look the order up first.", "signature": "sig-1"},
                {"type": "redacted_thinking", "data": "opaque-bytes"},
                {"type": "text", "text": "Searching."},
                {"type": "tool_use", "id": "call-1", "name": "lookup", "input": {"q": "order 7"}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )
    response = LLMResponse(message)
    assert response.assistant_content == TURN
    assert response.stop_reason == "tool_use"


@pytest.mark.parametrize("reasoning", [THINKING, UNSIGNED, REDACTED])
def test_a_complete_tool_turn_led_by_reasoning_is_recognised(reasoning):
    assert LLMResponse(raw(reasoning, TOOL, stop="end_turn")).stop_reason == "tool_use"


@pytest.mark.parametrize(
    "malformed",
    [
        NS(type="thinking", thinking=None, signature="sig"),
        NS(type="thinking", thinking="text", signature=7),
        NS(type="redacted_thinking", data=""),
        NS(type="redacted_thinking"),
    ],
)
def test_a_malformed_reasoning_block_is_not_repaired_into_a_tool_turn(malformed):
    assert LLMResponse(raw(malformed, TOOL, stop="end_turn")).stop_reason == "end_turn"


def test_assistant_blocks_falls_back_to_content_for_a_response_without_the_turn():
    legacy = NS(stop_reason="tool_use", content=[TEXT, TOOL])
    assert assistant_blocks(legacy) == TURN[2:]
    assert assistant_blocks(LLMResponse(raw(THINKING, REDACTED, TEXT, TOOL))) == TURN


def test_without_reasoning_strips_every_turn_and_mutates_nothing():
    history = [
        {"role": "user", "content": "Find order 7."},
        {"role": "assistant", "content": copy.deepcopy(TURN)},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-1"}]},
        {"role": "assistant", "content": [copy.deepcopy(TURN[0])]},
        {"role": "assistant", "content": "Shipped."},
    ]
    before = copy.deepcopy(history)
    stripped = without_reasoning(history)
    assert history == before
    assert stripped == [
        history[0],
        {"role": "assistant", "content": TURN[2:]},
        history[2],
        history[4],
    ]
    assert stripped[0] is history[0] and stripped[2] is history[2]


# ─── Admission: replayed reasoning is history, priced as input ─────────


def admitted(**extra):
    request = {
        "model": "claude-sonnet-5-5",
        "max_tokens": 1424,
        "messages": [
            {"role": "user", "content": "Find order 7."},
            {"role": "assistant", "content": copy.deepcopy(TURN)},
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "call-1", "content": "ok"}],
            },
        ],
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "low"},
        "tools": [{"name": "lookup", "input_schema": {"type": "object"}, "strict": True}],
    }
    request.update(extra)
    return request


def test_reasoning_history_and_controls_are_admitted_and_priced_as_input():
    with_blocks = request_bound(admitted(), "direct")
    without = admitted()
    without["messages"][1]["content"] = TURN[2:]
    assert with_blocks > request_bound(without, "direct")
    assert request_bound(admitted(thinking={"type": "disabled"}), "direct") > 0
    assert request_bound(admitted(model="anthropic/claude-sonnet-5.5"), "openrouter") > 0


@pytest.mark.parametrize(
    "override",
    [
        {"thinking": {"type": "enabled"}},
        {"thinking": {"type": "adaptive", "budget_tokens": 1}},
        {"output_config": {"effort": "none"}},
        {"output_config": {"effort": "low", "format": {}}},
        {"tools": [{"name": "lookup", "input_schema": {"type": "object"}, "strict": "yes"}]},
    ],
)
def test_unpriced_reasoning_options_are_refused(override):
    with pytest.raises(BudgetError):
        request_bound(admitted(**override), "direct")


@pytest.mark.parametrize("effort", ["minimal", "none", "MAX", None])
def test_an_effort_outside_the_request_vocabulary_is_refused_on_both_transports(effort):
    """IR1 B1: only `low`..`max` reach a provider; a catalogue's `minimal` is refused."""
    with pytest.raises(BudgetError, match="unsupported reasoning option"):
        request_bound(admitted(output_config={"effort": effort}), "direct")
    routed = admitted(model="anthropic/claude-sonnet-5.5", output_config={"effort": effort})
    with pytest.raises(BudgetError, match="unsupported reasoning option"):
        request_bound(routed, "openrouter")
    for allowed in ("low", "medium", "high", "xhigh", "max"):
        assert request_bound(admitted(output_config={"effort": allowed}), "direct") > 0


@pytest.mark.parametrize(
    "block",
    [
        {
            "type": "thinking",
            "thinking": "t",
            "signature": "s",
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "thinking", "thinking": 1, "signature": "s"},
        {"type": "thinking", "thinking": "t", "signature": None},
        {"type": "redacted_thinking", "data": None},
        {"type": "redacted_thinking", "data": "d", "extra": 1},
    ],
)
def test_malformed_reasoning_history_is_refused(block):
    request = admitted()
    request["messages"][1]["content"] = [block] + TURN[2:]
    with pytest.raises(BudgetError, match="reasoning block"):
        request_bound(request, "direct")
