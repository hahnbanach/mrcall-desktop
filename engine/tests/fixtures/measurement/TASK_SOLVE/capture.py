"""Capture harness for TASK_SOLVE: the solve loop's request at each case's decision point.

Builder: ``zylch.rpc.methods.tasks_solve``, the desktop's "Open" on a task.
It loads the task by id, builds the context with ``build_task_context`` (the
task's fields, the original email by ``event_id``, the memory blobs named in
``sources.blobs``), formats ``SOLVE_SYSTEM_PROMPT`` with the user's personal
data, learned rules and language directive, and runs ``TaskExecutor`` with
``SOLVE_TOOLS`` — which calls ``create_message_sync``.

The harness seeds what the RPC reads: the email (``input.email``), the memory
blobs (``input.memory``, linked from the task), the user's learned rules
(``input.rules``, the ``template:<owner>`` family the OPERATING RULES block is
built from) and the task row (``input.task``), then calls the RPC with the
case's typed ``instructions``. ``solve_tools.execute_tool`` answers from
``input.tool_results`` (tool name → the string the tool returns), so no tool
touches a mailbox, WhatsApp, MrCall, the web or memory. ``input.replay`` lists
tool calls already made in this solve; the request captured is the next one.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from tests.measurement import conversation_capture as cc

ROLE = "TASK_SOLVE"


def _seed(profile, given: Dict[str, Any]) -> str:
    """Put the task and what its context reads in place; return the task id."""
    from zylch.storage.storage import Storage

    store = Storage.get_instance()
    owner = profile.owner
    email = given.get("email")
    if email:
        cc.seed_email(owner, email)
    blob_ids = [cc.seed_blob(profile.embedder, owner, text) for text in given.get("memory") or []]
    for rule in given.get("rules") or []:
        cc.seed_blob(profile.embedder, owner, rule, namespace=f"template:{owner}")
    task = dict(given["task"])
    item = {
        "event_type": task.get("event_type", "email"),
        "event_id": task.get("event_id") or (email or {}).get("id"),
        "contact_email": task.get("contact_email") or "",
        "contact_phone": task.get("contact_phone"),
        "contact_name": task.get("contact_name"),
        "title": task.get("title"),
        "action_required": True,
        "urgency": task.get("urgency", "medium"),
        "reason": task.get("reason"),
        "suggested_action": task.get("suggested_action"),
        "sources": {"blobs": blob_ids},
    }
    if not store.store_task_item(owner, item):
        raise RuntimeError("the case's task row was not stored")
    return store.get_task_by_event(owner, item["event_type"], item["event_id"])["id"]


def _scripted_tools(mp, results: Dict[str, str]) -> None:
    """Every solve tool answers from the case's script; an unscripted one finds nothing."""
    from zylch.services import solve_tools

    def execute_tool(name: str, args: Dict[str, Any], _store: Any, _owner_id: str) -> str:
        if name not in results:
            return "No results."
        return cc.scripted_result(results[name], args)

    mp.setattr(solve_tools, "execute_tool", execute_tool)


async def _solve(task_id: str, instructions: str, approve: bool) -> Dict[str, Any]:
    from zylch.rpc import methods

    def notify(_method: str, event: Dict[str, Any]) -> None:
        # The executor waits on an approval card; answer it as the user would.
        if event.get("type") == "tool_call_pending":
            executor = methods._active_executor
            asyncio.get_running_loop().call_soon(
                lambda: asyncio.ensure_future(executor.approve(event["tool_use_id"], approve))
            )

    result = await methods.tasks_solve({"task_id": task_id, "instructions": instructions}, notify)
    # The RPC leaves the executor's event stream suspended on `done`; the loop
    # closes it once it is collected. Give that close its turns now: at
    # `asyncio.run` shutdown it would be cancelled instead, and the executor
    # answers a cancellation by yielding.
    for _ in range(3):
        await asyncio.sleep(0)
    return result


def run_case(case: Dict[str, Any], client: Any, *, approve: bool = True) -> Dict[str, Any]:
    """Run one case's solve with ``client`` answering every unscripted call.

    Approval-gated tools (the sends, memory updates, ``run_python``) are
    approved (or declined, ``approve=False``) and answer from the script. The
    follow-up reanalysis a mutating solve triggers is another role's call
    (REANALYZE) and does not run here. Returns the RPC's result, the final
    answer, the tool calls of the forwarded answers and the replayed rounds.
    """
    from zylch.rpc import methods

    given = case["input"]
    replay = cc.ReplayClient(given.get("replay") or [], client)
    with cc.disposable_profile(given.get("profile"), given.get("channels")) as profile:
        cc.route_llm(profile.mp, replay)
        _scripted_tools(profile.mp, given.get("tool_results") or {})

        async def no_reanalysis(**_kwargs: Any) -> None:
            return None

        profile.mp.setattr(methods, "_maybe_reanalyze_after_solve", no_reanalysis)
        task_id = _seed(profile, given)
        result = asyncio.run(_solve(task_id, given.get("instructions") or "", approve))
    return {
        "result": result,
        "answer": replay.last_text,
        "calls": replay.calls,
        "replayed": replay.replayed,
    }


def build_requests(cases: Any, *, calls: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """The request at each case's decision point, as the executor passed it.

    ``calls``, when given, receives per case id how many requests reached the
    capturing client — one, unless the solve sent more than its decision.
    """
    captured = []
    for case in cc.case_list(cases):
        client = cc.CapturingClient()
        outcome = run_case(case, client)
        expected = len(case["input"].get("replay") or [])
        if outcome["replayed"] != expected or not outcome["result"].get("ok"):
            raise RuntimeError(f"{case['id']}: the solve did not run as scripted: {outcome}")
        if calls is not None:
            calls[case["id"]] = len(client.requests)
        captured.append({"case_id": case["id"], "request": client.requests[-1]})
    return captured
