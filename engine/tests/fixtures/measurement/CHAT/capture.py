"""Capture harness for CHAT: the chat agent's request at each case's decision point.

Builder: ``zylch.assistant.core.ZylchAIAgent.process_message``, the agent the
``chat.send`` RPC runs, built the way ``ChatService._initialize_agent`` builds
it — the real tool list from ``ToolFactory.create_all_tools``, so a captured
``tools`` is the schema list a user's chat sends, and the context
``{"user_id": <owner>}`` — and fed the case's earlier turns the way
``ChatService`` restores them (``set_history``).

Each tool's ``execute`` is replaced by the case's scripted result
(``input.tool_results``, keyed by tool name), so nothing reaches a mailbox,
WhatsApp, MrCall or the web. A case's ``input.replay`` lists tool calls the
model has already made in this turn: the harness answers them itself, the
agent runs them against the scripted tools and appends call and result to the
transcript, and the request captured is the next one — the decision point.
The agent's clock reads ``conversation_capture.CAPTURE_NOW``, so the date/time
line of the turn is the same in every capture.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from tests.measurement import conversation_capture as cc

ROLE = "CHAT"


def scripted_tools(mp, tools: List[Any], results: Dict[str, Dict[str, Any]]) -> None:
    """Answer every tool from the case's script; an unscripted one finds nothing.

    A scripted answer is a ``ToolResult`` as a dict (``status``, ``data``,
    ``message``, ``error``), which the agent formats exactly as a real one.
    """
    from zylch.tools.base import ToolResult, ToolStatus

    def scripted(name: str):
        async def execute(**kwargs: Any) -> ToolResult:
            spec = cc.scripted_result(results[name], kwargs) if name in results else None
            if spec is None:
                return ToolResult(status=ToolStatus.SUCCESS, data=None, message="No results.")
            return ToolResult(
                status=ToolStatus(spec.get("status", "success")),
                data=spec.get("data"),
                message=spec.get("message"),
                error=spec.get("error"),
            )

        return execute

    for tool in tools:
        mp.setattr(tool, "execute", scripted(tool.name))


async def _turn(profile, case: Dict[str, Any], client: Any, approve: bool) -> str:
    from zylch.assistant import core
    from zylch.assistant.core import ZylchAIAgent
    from zylch.storage import Storage
    from zylch.tools.config import ToolConfig
    from zylch.tools.factory import ToolFactory

    given = case["input"]
    # The turn's date/time line rides in the user turn the agent sends.
    cc.freeze_clock(profile.mp, core)
    config = ToolConfig.from_settings_with_owner(profile.owner, storage=Storage.get_instance())
    tools, _session_state = await ToolFactory.create_all_tools(config, current_business_id=None)
    scripted_tools(profile.mp, tools, given.get("tool_results") or {})
    agent = ZylchAIAgent(
        tools=tools,
        model_selector=ToolFactory.create_model_selector(config),
        client=client,
    )
    agent.set_history(given.get("history") or [])

    async def approval(_tool_use_id: str, _name: str, _tool_input: Dict[str, Any]):
        return approve, None

    return await agent.process_message(
        user_message=given["user_message"],
        context={"user_id": profile.owner},
        approval_callback=approval,
    )


def run_case(case: Dict[str, Any], client: Any, *, approve: bool = True) -> Dict[str, Any]:
    """Run one case's chat turn with ``client`` answering every unscripted call.

    Approval-gated tools are approved (or declined, ``approve=False``) and then
    answer from the script like the others. Returns the final answer, the tool
    calls of the forwarded answers, how many scripted rounds were replayed, and
    the turn to score (``ReplayClient.turn``: the first answer's calls, the
    later calls and all the text the model wrote).
    """
    given = case["input"]
    replay = cc.ReplayClient(given.get("replay") or [], client)
    with cc.disposable_profile(given.get("profile"), given.get("channels")) as profile:
        answer = asyncio.run(_turn(profile, case, replay, approve))
    return {
        "answer": answer,
        "calls": replay.calls,
        "replayed": replay.replayed,
        "turn": replay.turn(),
    }


def build_requests(cases: Any, *, calls: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """The request at each case's decision point, as the agent passed it.

    ``calls``, when given, receives per case id how many requests reached the
    capturing client — one, unless the role's path sent more than its decision.
    """
    captured = []
    for case in cc.case_list(cases):
        client = cc.CapturingClient()
        outcome = run_case(case, client)
        expected = len(case["input"].get("replay") or [])
        if outcome["replayed"] != expected:
            raise RuntimeError(
                f"{case['id']}: the turn replayed {outcome['replayed']} of {expected} rounds"
            )
        if calls is not None:
            calls[case["id"]] = len(client.requests)
        captured.append(cc.entry(case, client.requests[-1]))
    return captured
