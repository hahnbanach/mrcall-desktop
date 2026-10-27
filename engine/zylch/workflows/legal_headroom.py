from typing import Any

from zylch.llm.budget import budget_snapshot
from zylch.llm.budget_pricing import request_bound
from zylch.llm.client import _coerce_messages, _with_datetime

RESEARCH_MAX_TOKENS = 1024

FINAL_TOOL_CHOICE = {
    "type": "tool",
    "name": "workflow_finish_report",
    "disable_parallel_tool_use": True,
}

FINAL_GUIDANCE = (
    "Complete the report now using retained evidence, useful conditional proposals and explicit "
    "unresolved facts or omissions. Call workflow_finish_report exactly once; no further research."
)
RESEARCH_GUIDANCE = (
    "Research is bounded by completion headroom. Batch the literal passage requests needed for "
    "the requested topics now, at most two tool actions per response; each passage call returns "
    "one complete match and next_offset for paging. "
    "Avoid repeated searches, reads or reference text already retained. Finalization may be next."
)


def plan(agent: Any, blocks: list[dict[str, Any]]) -> dict[str, int] | None:
    if agent.client.transport != "direct":
        return None
    snapshot = budget_snapshot(agent.identity.uid)
    remaining = snapshot["remaining_usd"]
    if remaining is None:
        return None
    remaining_micro = max(0, round(remaining * 1_000_000))
    request = {
        "model": agent.client.model,
        "messages": _coerce_messages(
            agent._messages_with_history_cache(agent.conversation_history)
        ),
        "system": _with_datetime(blocks + [{"type": "text", "text": RESEARCH_GUIDANCE}]),
        "tools": agent._get_tool_schemas(),
        "max_tokens": RESEARCH_MAX_TOKENS if not agent._final_only else agent.max_tokens,
        "temperature": 1.0,
        "service_tier": "standard_only",
    }
    research = request_bound(request, "direct")
    request["tools"] = [
        schema for schema in request["tools"] if schema["name"] == "workflow_finish_report"
    ]
    request["system"] = _with_datetime(blocks + [{"type": "text", "text": FINAL_GUIDANCE}])
    request["max_tokens"] = agent.max_tokens
    request["tool_choice"] = dict(FINAL_TOOL_CHOICE)
    finish = request_bound(request, "direct")
    return {
        "research_bound_micro_usd": research,
        "finish_bound_micro_usd": finish,
        "available_micro_usd": remaining_micro,
        "message_count": len(request["messages"]),
    }
