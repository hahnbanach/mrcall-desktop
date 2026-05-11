"""Pure-logic agentic task executor.

Surfaces the solve loop as an async event stream so both CLI and RPC
callers can drive it. The CLI wraps this with `click.confirm()`; the
RPC layer forwards events over JSON-RPC and waits for an explicit
approve call.

Events yielded:
  {"type": "thinking", "text": str}
  {"type": "tool_use_start", "tool_use_id": str, "name": str}
  {"type": "tool_call_pending", "tool_use_id": str,
   "name": str, "input": dict, "preview": str}
  {"type": "tool_result", "tool_use_id": str,
   "name": str, "output": str, "approved": bool}
  {"type": "done", "result": {"messages": list}}
  {"type": "error", "message": str}

`tool_use_start` fires for every tool right before execution (both
read-only and approval-gated). It exists to give the UI a chance to
show "Sto cercando…" while a tool runs, instead of a static
"Sto pensando" between turns.

Approvals: caller invokes `await executor.approve(tool_use_id,
approved, edited_input=None)`. Auto-approved (read-only) tools do
not emit a pending event.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)


# Canonical set of destructive tool names that require explicit user
# approval before execution. Two surfaces consume this:
#  - ChatService (zylch/assistant/core.py) — uses ToolFactory tool names
#    (`send_draft`, `send_whatsapp_message`).
#  - TaskExecutor (this file, driven by `tasks.solve`) — uses the
#    flatter SOLVE_TOOLS naming (`send_email`, `send_whatsapp`) defined
#    in zylch/services/solve_constants.py.
# Both name shapes are listed here so the gate fires in either surface.
# Adding a new write-effect tool to SOLVE_TOOLS or ToolFactory MUST also
# add it here; the naming-coherence test in tests/services covers this.
APPROVAL_TOOLS = {
    # ChatService (factory) names
    "send_draft",
    "send_whatsapp_message",
    # TaskExecutor (solve) names
    "send_email",
    "send_whatsapp",
    # Shared
    "send_sms",
    "update_memory",
    "run_python",
}


def format_approval_preview(tool_name: str, args: Dict) -> str:
    """Human-readable preview of a pending tool call."""
    if tool_name == "send_email":
        return (
            f"**Send Email**\nTo: {args.get('to', '')}\n"
            f"Subject: {args.get('subject', '')}\n\n"
            f"{args.get('body', '')}"
        )
    if tool_name == "draft_email":
        return (
            f"**Draft Email**\nTo: {args.get('to', '')}\n"
            f"Subject: {args.get('subject', '')}\n\n"
            f"{args.get('body', '')}"
        )
    if tool_name == "send_whatsapp":
        return (
            f"**Send WhatsApp**\nTo: {args.get('phone_number', '')}\n\n"
            f"{args.get('message', '')}"
        )
    if tool_name == "send_sms":
        return f"**Send SMS**\nTo: {args.get('phone_number', '')}\n\n" f"{args.get('message', '')}"
    if tool_name == "run_python":
        return (
            f"**Run Python**\n_{args.get('description', '')}_\n\n"
            f"```python\n{args.get('code', '')}\n```"
        )
    if tool_name == "update_memory":
        return (
            f"**Update Memory**\nblob_id: {args.get('blob_id', '')}\n\n"
            f"New content:\n{args.get('new_content', '')}"
        )
    return json.dumps(args, indent=2, default=str)


class TaskExecutor:
    """Runs the agent loop, yielding events and awaiting approvals.

    Usage:
        ex = TaskExecutor(client, system, messages, store, owner_id)
        async for event in ex.run():
            if event["type"] == "tool_call_pending":
                await ex.approve(event["tool_use_id"], True)
    """

    def __init__(
        self,
        client,
        system: str,
        messages: List[Dict],
        store,
        owner_id: str,
        tools: List[Dict],
        max_turns: int = 10,
    ):
        self._client = client
        self._system = system
        self._messages = messages
        self._store = store
        self._owner_id = owner_id
        self._tools = tools
        self._max_turns = max_turns
        # Map tool_use_id -> Future set by approve()
        self._pending: Dict[str, asyncio.Future] = {}

    @property
    def messages(self) -> List[Dict]:
        return self._messages

    async def approve(
        self,
        tool_use_id: str,
        approved: bool,
        edited_input: Optional[Dict] = None,
    ) -> bool:
        """Resolve a pending approval. Returns True if accepted."""
        fut = self._pending.get(tool_use_id)
        if fut is None or fut.done():
            logger.warning(f"[executor] approve({tool_use_id}) -> no pending future")
            return False
        fut.set_result(
            {
                "approved": approved,
                "edited_input": edited_input,
            }
        )
        return True

    async def run(self) -> AsyncIterator[Dict[str, Any]]:
        """Drive the loop, yielding events."""
        from zylch.services.solve_tools import execute_tool

        loop = asyncio.get_event_loop()

        try:
            for _turn in range(self._max_turns):
                # LLM call runs in a thread (sync SDK call).
                response = await loop.run_in_executor(
                    None,
                    lambda: self._client.create_message_sync(
                        system=self._system,
                        messages=self._messages,
                        tools=self._tools,
                        max_tokens=2000,
                    ),
                )

                if response.stop_reason != "tool_use":
                    # Final text
                    text = ""
                    for block in response.content:
                        if hasattr(block, "text"):
                            text += block.text
                    if text:
                        self._messages.append(
                            {"role": "assistant", "content": text},
                        )
                        yield {"type": "thinking", "text": text}
                    yield {
                        "type": "done",
                        "result": {"messages": self._messages},
                    }
                    return

                tool_results: List[Dict] = []
                assistant_content: List[Dict] = []

                for block in response.content:
                    btype = getattr(block, "type", None)
                    if btype == "text" and getattr(block, "text", ""):
                        assistant_content.append(
                            {"type": "text", "text": block.text},
                        )
                        yield {
                            "type": "thinking",
                            "text": block.text,
                        }
                    elif btype == "tool_use":
                        tool_name = block.name
                        tool_input = dict(block.input or {})
                        tool_id = block.id
                        assistant_content.append(
                            {
                                "type": "tool_use",
                                "id": tool_id,
                                "name": tool_name,
                                "input": tool_input,
                            }
                        )

                        approved = True
                        if tool_name in APPROVAL_TOOLS:
                            # Pause for approval.
                            fut: asyncio.Future = loop.create_future()
                            self._pending[tool_id] = fut
                            yield {
                                "type": "tool_call_pending",
                                "tool_use_id": tool_id,
                                "name": tool_name,
                                "input": tool_input,
                                "preview": format_approval_preview(
                                    tool_name,
                                    tool_input,
                                ),
                            }
                            decision = await fut
                            self._pending.pop(tool_id, None)
                            approved = bool(decision.get("approved"))
                            edited = decision.get("edited_input")
                            if edited and isinstance(edited, dict):
                                tool_input = edited
                                # Reflect the edit in the recorded
                                # assistant message so the model sees
                                # what actually ran.
                                assistant_content[-1]["input"] = tool_input

                        if not approved:
                            output = "User declined this action."
                        else:
                            # UI hint: every tool gets a start event so
                            # the renderer can swap "Sto pensando…" for
                            # "Sto cercando…" / "Sto eseguendo…" while
                            # the tool runs. Without this, read-only
                            # tools (search_*, read_document, …) ran
                            # silently and the user saw no progress
                            # between turns.
                            yield {
                                "type": "tool_use_start",
                                "tool_use_id": tool_id,
                                "name": tool_name,
                            }
                            try:
                                output = await loop.run_in_executor(
                                    None,
                                    execute_tool,
                                    tool_name,
                                    tool_input,
                                    self._store,
                                    self._owner_id,
                                )
                            except Exception as e:
                                logger.exception(f"[executor] tool {tool_name} failed")
                                output = f"Tool error: {e}"

                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": output,
                            }
                        )
                        yield {
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "name": tool_name,
                            "output": output,
                            "approved": approved,
                        }

                self._messages.append(
                    {"role": "assistant", "content": assistant_content},
                )
                self._messages.append(
                    {"role": "user", "content": tool_results},
                )

            # max_turns exhausted
            yield {
                "type": "done",
                "result": {"messages": self._messages},
            }
        except Exception as e:
            logger.exception("[executor] run failed")
            yield {"type": "error", "message": f"{type(e).__name__}: {e}"}
