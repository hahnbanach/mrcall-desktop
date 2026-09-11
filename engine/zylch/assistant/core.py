"""Core Zylch AI agent using LLM abstraction layer."""

import asyncio
import atexit
import contextvars
import copy
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ..llm import LLMClient, make_llm_client
from ..llm.exceptions import LLMPromptTooLargeError
from .budget import (
    PROMPT_TOKEN_BUDGET,
    TOOL_RESULT_MAX_CHARS,
    bound_tool_result,
    check_prompt_budget,
)
from .models import ModelSelector
from .prompts import get_system_prompt_base
from .turn_context import new_turn_id, get_turn_id
from ..tools.base import Tool, ToolResult, ToolStatus
from ..agents.base import BaseConversationalAgent
from ..services.solve_constants import get_personal_data_section
from ..services.channel_status import get_channel_status_block
from ..services.task_executor import APPROVAL_TOOLS

# Type alias for approval callback:
#   (tool_use_id, tool_name, input_dict) -> (approved, edited_input | None)
# `edited_input`, when present, replaces the tool input — it carries the
# user's edits made in the approval card (e.g. a corrected WhatsApp /
# email body) before the tool actually runs.
ApprovalCallback = Callable[
    [str, str, Dict[str, Any]], Awaitable[Tuple[bool, Optional[Dict[str, Any]]]]
]

logger = logging.getLogger(__name__)


# ─── Where a tool runs ────────────────────────────────────────────────
#
# Two properties are in tension.
#
# *Responsiveness*: a tool that blocks the event loop — imaplib, smtplib,
# a subprocess, an ONNX encode — stops the WebSocket keepalive, every
# other RPC, and the loop's ability to act on a cancellation, for as long
# as it runs. Those belong in a thread.
#
# *Interruptibility*: `run_in_executor` cannot stop a thread that has
# started. A turn cancelled while such a tool runs still finishes it and
# still commits its side effect. A tool that spends its time on `await`
# instead is genuinely interruptible, and moving it to a thread would
# THROW THAT AWAY. `compose_email` is the case that matters: it awaits an
# LLM call and then writes a draft, so on the loop a cancelled turn
# writes nothing, and in a thread it writes the orphaned draft this whole
# fix exists to prevent.
#
# So the offload is an explicit list of the tools that genuinely block,
# not a blanket rule. Forgetting to add a blocking tool costs latency;
# adding an interruptible one costs correctness — the list errs toward
# the loop on purpose.
_BLOCKING_TOOLS = frozenset(
    {
        # IMAP / SMTP
        "search_provider_emails",
        "send_draft",
        "sync_emails",
        "search_emails",
        "close_email_threads",
        "email_stats",
        "download_attachment",
        # Subprocess
        "run_python",
        # Local files
        "read_document",
        # Embedding (ONNX) + full-corpus SQLite scans
        "search_local_memory",
        "search_local_emails",
        "update_memory",
        "create_memory",
        # neonize (synchronous Go bindings) + WhatsApp SQLite
        "search_whatsapp",
        "get_whatsapp_conversation",
        "send_whatsapp_message",
        "whatsapp_gap_analysis",
        "get_contact_timeline",
        "get_whatsapp_contacts",
        # Synchronous httpx client
        "search_pipedrive_person",
        "get_pipedrive_deals",
    }
)

# The pool blocking tools run in. NOT `job_executor`'s pool: that one has
# four workers shared with multi-minute email syncs, so an interactive
# turn submitted there can queue behind four of them.
_INTERACTIVE_TOOL_WORKERS = max(2, int(os.environ.get("ZYLCH_TOOL_WORKERS", "8") or 8))
_tool_executor: Optional[ThreadPoolExecutor] = None


def get_tool_executor() -> ThreadPoolExecutor:
    """The thread pool blocking tool calls run in (created on first use)."""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ThreadPoolExecutor(
            max_workers=_INTERACTIVE_TOOL_WORKERS,
            thread_name_prefix="zylch-tool",
        )
        # Do not let a stuck tool thread hold the interpreter open at
        # exit: `concurrent.futures` joins its threads via atexit.
        atexit.register(_shutdown_tool_executor)
        logger.info(f"[tools] blocking-tool executor started ({_INTERACTIVE_TOOL_WORKERS} workers)")
    return _tool_executor


def _shutdown_tool_executor() -> None:
    """Stop accepting work and stop waiting for what is still running."""
    global _tool_executor
    executor, _tool_executor = _tool_executor, None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)


class ZylchAIAgent(BaseConversationalAgent):
    """Main conversational agent for Zylch AI.

    Single-agent architecture with native function calling via Anthropic SDK.
    """

    def __init__(
        self,
        tools: List[Tool],
        model_selector: Optional[ModelSelector] = None,
        max_tokens: int = 4096,
        triggered_instructions: Optional[List[str]] = None,
    ):
        """Initialize Zylch AI agent.

        Args:
            tools: List of available tools
            model_selector: Model selection logic (optional)
            max_tokens: Maximum tokens for response
            triggered_instructions: List of triggered instructions (optional, for prompt injection)
        """
        self.client: LLMClient = make_llm_client()
        self.tools = tools
        self.tool_map = {tool.name: tool for tool in tools}
        self.model_selector = model_selector or ModelSelector()
        self.max_tokens = max_tokens
        self.triggered_instructions = triggered_instructions or []
        self.conversation_history: List[Dict[str, Any]] = []
        self.message_count = 0
        # Usage dict from the most recent LLM call — exposed for tests
        # and observability. Reset at the start of each process_message.
        self.last_usage: Dict[str, int] = {}
        # Tool results cut for size in the most recent turn — see
        # `budget.bound_tool_result`. `chat.send` surfaces them.
        self.last_truncations: List[Dict[str, Any]] = []

        logger.info(
            f"Initialized Zylch AI agent with {len(tools)} tools, transport={self.client.transport}{f' and {len(self.triggered_instructions)} triggered instructions' if self.triggered_instructions else ''}"
        )

    def _get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Get Anthropic tool schemas for all registered tools.

        Returns:
            List of tool schemas
        """
        schemas = [tool.get_schema() for tool in self.tools]
        tool_names = [s["name"] for s in schemas]
        logger.info(f"Tools available to Claude: {tool_names}")
        return schemas

    def _messages_with_history_cache(
        self,
        messages: List[Dict[str, Any]],
        volatile_suffix: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return a deep copy of ``messages`` with a cache_control marker on
        the last content block of the most recent message.

        Anthropic caches the entire prefix up to the marker, so on the next
        turn the whole history becomes a cache read. We never mutate
        ``self.conversation_history`` — the marker is added only on the wire
        representation, because history is serialized/restored elsewhere and
        stale cache_control markers would accumulate.

        If ``volatile_suffix`` is provided, it is appended as an EXTRA text
        block AFTER the cache_control breakpoint on the last message. This
        lets per-turn, minute-granular content (current time, notifications)
        reach the model without invalidating the cached prefix.

        Anthropic allows at most 4 ephemeral breakpoints; the system prompt
        consumes 1, this adds 1, total = 2 — well within the limit.
        """
        if not messages:
            return messages
        out = copy.deepcopy(messages)
        last = out[-1]
        content = last.get("content")
        if isinstance(content, str):
            # Promote string content to a single text block so we can attach
            # cache_control on it. Anthropic accepts both shapes.
            blocks: List[Dict[str, Any]] = [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
            if volatile_suffix:
                blocks.append({"type": "text", "text": volatile_suffix})
            last["content"] = blocks
            return out
        if isinstance(content, list) and content:
            # Attach cache_control to the last block — the stable prefix.
            last_block = content[-1]
            if isinstance(last_block, dict):
                last_block["cache_control"] = {"type": "ephemeral"}
            if volatile_suffix:
                content.append({"type": "text", "text": volatile_suffix})
        return out

    async def process_message(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
        approval_callback: Optional[ApprovalCallback] = None,
    ) -> str:
        """Process user message with tool use.

        Args:
            user_message: User's message
            context: Optional context (e.g., contact info, settings)

        Returns:
            Agent's response
        """
        # Install a turn id for log correlation across LLM calls, tool loop,
        # and the tools themselves (which read it from a ContextVar).
        turn_id = new_turn_id()
        logger.debug(
            f"[chat turn={turn_id}] process_message start" f" user_message_len={len(user_message)}"
        )

        self.last_truncations = []

        # Add user message to history
        self.conversation_history.append({"role": "user", "content": user_message})

        # Select appropriate model (check for forced model in context)
        force_model = context.get("force_model") if context else None
        model = self.model_selector.select_model(user_message, context, force_model=force_model)
        logger.info(f"[chat turn={turn_id}] Using model: {model}")

        # Build system prompt with context.
        # We use ``get_system_prompt_base()`` only (no datetime header) so
        # the cached prefix stays byte-identical across turns within the
        # same day/hour. The current date/time is injected into the user
        # message below, AFTER the cache breakpoint, so minute-granular
        # time updates don't invalidate the cached history.
        system_prompt = get_system_prompt_base()
        if context and context.get("current_business_id"):
            system_prompt += f"\n\n**CURRENT SESSION:**\n✅ Selected MrCall Assistant: {context['current_business_id']}\nYou CAN save contacts directly to this assistant."

        # Inject user personal data / notes / secret instructions into the
        # cached system block (Deliverable 2). These live in the profile
        # .env and change rarely, so placing them inside the cached prefix
        # keeps the cache valid across turns while still letting them
        # steer every chat response.
        owner_id_for_prefs = context.get("user_id") if context else None
        personal_section = get_personal_data_section(owner_id=owner_id_for_prefs)
        if personal_section:
            system_prompt += f"\n\n**USER CONTEXT:**{personal_section}"

        # Inject triggered instructions (for prompt awareness - NOT for execution)
        # Note: Trigger execution happens elsewhere (e.g., ChatService.execute_session_start_triggers)
        # This just makes the AI aware of the triggers in case they're relevant during conversation
        if self.triggered_instructions:
            instructions_text = "\n".join(f"- {instr}" for instr in self.triggered_instructions)
            system_prompt += f"\n\n**TRIGGERED INSTRUCTIONS (event-driven, for reference):**\n{instructions_text}"
            logger.info(
                f"Injected {len(self.triggered_instructions)} triggered instructions into system prompt"
            )

        # Wrap system as a single cached text block. Anthropic caches the
        # full prefix (tools + system) up to this marker, and the history
        # breakpoint below extends caching through the latest turn.
        system_blocks = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        # Volatile per-turn context (current date/time) goes AFTER the last
        # cache_control breakpoint so minute-granular changes never
        # invalidate the cached prefix.
        now = datetime.now()
        volatile_suffix = (
            "\n\n[CURRENT DATE/TIME — "
            f"{now.strftime('%A, %B %d, %Y')}, {now.strftime('%H:%M')}]"
            "\n\n"
            f"{get_channel_status_block()}"
        )

        # Create message with tool support (with current date/time)
        # Note: model selection is now handled by LLMClient based on provider
        response = await self._create_message_within_budget(
            system_blocks=system_blocks,
            volatile_suffix=volatile_suffix,
            turn_id=turn_id,
            step=0,
        )
        try:
            u = response.usage
            self.last_usage = dict(u)
            logger.debug(
                f"[chat turn={turn_id}] usage "
                f"input={u.get('input_tokens', 0)} "
                f"output={u.get('output_tokens', 0)} "
                f"cache_read={u.get('cache_read_input_tokens', 0)} "
                f"cache_create={u.get('cache_creation_input_tokens', 0)}"
            )
        except Exception:
            pass

        # Handle tool use loop
        step = 0
        while response.stop_reason == "tool_use":
            if step >= 10:
                raise RuntimeError("Chat stopped after 10 tool rounds. Review progress before continuing.")
            step += 1
            logger.debug(
                f"[chat turn={turn_id} step={step}] tool_use stop_reason"
                f" — entering tool loop iteration"
            )
            # Normalize assistant content blocks to plain dicts so that
            # conversation_history stays JSON-serializable across turns
            # (SDK TextBlock/ToolUseBlock instances break re-serialization
            # once we loop back with a declined tool_result).
            assistant_content_dicts: List[Dict[str, Any]] = []
            for block in response.content:
                btype = getattr(block, "type", None)
                if btype == "text":
                    assistant_content_dicts.append(
                        {"type": "text", "text": getattr(block, "text", "")}
                    )
                elif btype == "tool_use":
                    assistant_content_dicts.append(
                        {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": dict(block.input or {}),
                        }
                    )
                else:
                    # Unknown block type — best-effort model_dump
                    try:
                        assistant_content_dicts.append(block.model_dump())
                    except Exception:
                        pass

            # Extract tool calls from response
            tool_results, direct_response = await self._execute_tools(
                response.content, approval_callback, turn_id=turn_id, step=step
            )

            # Check for direct response tools (e.g., get_tasks)
            # These tools return pre-formatted output that should be returned as-is
            if direct_response:
                logger.info("Direct response from tool, skipping second LLM call")
                # Add assistant's tool use to history
                self.conversation_history.append(
                    {"role": "assistant", "content": assistant_content_dicts}
                )
                # Add the direct response as assistant message
                self.conversation_history.append({"role": "assistant", "content": direct_response})
                return direct_response

            # Add assistant's tool use to history
            self.conversation_history.append({"role": "assistant", "content": response.content})

            # Add tool results to history
            self.conversation_history.append({"role": "user", "content": tool_results})

            # Continue conversation with tool results (with current date/time)
            response = await self._create_message_within_budget(
                system_blocks=system_blocks,  # Same cached system prompt
                volatile_suffix=volatile_suffix,
                turn_id=turn_id,
                step=step,
            )
            try:
                u = response.usage
                self.last_usage = dict(u)
                logger.debug(
                    f"[chat turn={turn_id} step={step}] usage "
                    f"input={u.get('input_tokens', 0)} "
                    f"output={u.get('output_tokens', 0)} "
                    f"cache_read={u.get('cache_read_input_tokens', 0)} "
                    f"cache_create={u.get('cache_creation_input_tokens', 0)}"
                )
            except Exception:
                pass

        # Extract final text response
        assistant_message = ""
        for block in response.content:
            if hasattr(block, "text"):
                assistant_message += block.text

        # Add final response to history
        self.conversation_history.append({"role": "assistant", "content": assistant_message})

        self.message_count += 1

        return assistant_message

    async def _create_message_within_budget(
        self,
        *,
        system_blocks: List[Dict[str, Any]],
        volatile_suffix: str,
        turn_id: str,
        step: int,
    ) -> Any:
        """Assemble the wire prompt, refuse it if over budget, else send it.

        Every dispatch goes through here, so the check covers the first
        call and each tool-loop iteration — the iteration that appends tool
        results is the one that grows. A refused prompt raises
        `LLMPromptTooLargeError` with the numbers; nothing is sent.
        """
        messages = self._messages_with_history_cache(
            self.conversation_history,
            volatile_suffix=volatile_suffix,
        )
        tools = self._get_tool_schemas()
        try:
            estimated = check_prompt_budget(system=system_blocks, tools=tools, messages=messages)
        except LLMPromptTooLargeError as e:
            logger.error(f"[chat turn={turn_id} step={step}] prompt refused before dispatch: {e}")
            raise
        logger.debug(
            f"[chat turn={turn_id} step={step}] prompt estimate={estimated} tokens"
            f" budget={PROMPT_TOKEN_BUDGET}"
        )
        return await self.client.create_message(
            messages=messages,
            system=system_blocks,
            tools=tools,
            max_tokens=self.max_tokens,
        )

    # Tools that return pre-formatted output and should bypass the second LLM call
    DIRECT_RESPONSE_TOOLS = {"get_tasks"}

    async def _execute_tools(
        self,
        content: List[Any],
        approval_callback: Optional[ApprovalCallback] = None,
        turn_id: Optional[str] = None,
        step: int = 0,
    ) -> tuple[List[Dict[str, Any]], str | None]:
        """Execute tool calls from response.

        Args:
            content: Response content blocks
            approval_callback: Optional approval gate
            turn_id: Chat-turn id used for log correlation
            step: Current tool-loop iteration (1-based)

        Returns:
            Tuple of (tool_results for Anthropic API, direct_response if applicable)
            If direct_response is not None, skip the second LLM call and return it directly.
        """
        results = []
        direct_response = None
        tid = turn_id or get_turn_id()

        for block in content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                try:
                    input_keys = list((tool_input or {}).keys())
                except Exception:
                    input_keys = []

                logger.info(
                    f"[chat turn={tid} step={step}] tool={tool_name}"
                    f" input_keys={input_keys} status=executing"
                )
                logger.debug(
                    f"[chat turn={tid} step={step}] tool={tool_name}" f" full_input={tool_input}"
                )

                # Approval gate for destructive tools.
                #
                # The condition is on the TOOL, not on whether a gate happens
                # to be wired: `approval_callback is not None and ...` meant a
                # caller that supplied no gate got every approval-listed tool
                # executed without one, which is the opposite of what a gate is
                # for. No callback means there is nobody to ask, and nobody to
                # ask means refuse.
                if tool_name in APPROVAL_TOOLS:
                    if approval_callback is None:
                        logger.warning(
                            f"[chat turn={tid} step={step}] tool={tool_name}"
                            " status=refused reason=no_approval_channel"
                        )
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": (
                                    f"{tool_name} needs approval and this client offers"
                                    " no approval channel, so it was not run. Tell the"
                                    " user to complete the action from a surface that"
                                    " can confirm it."
                                ),
                            }
                        )
                        continue
                    approved = False
                    edited_input: Optional[Dict[str, Any]] = None
                    # The card shows/edits the tool's `approval_input`, not
                    # the raw model input. For most tools these are equal;
                    # for reference-style tools (send_draft carries only a
                    # draft_id) the override hydrates the editable content
                    # (To / Subject / Body) so the widget has something to
                    # edit. `execute` accepts the hydrated fields back.
                    gate_tool = self.tool_map.get(tool_name)
                    if gate_tool is not None:
                        card_input = gate_tool.approval_input(dict(tool_input or {}))
                    else:
                        card_input = dict(tool_input or {})
                    try:
                        decision = await approval_callback(block.id, tool_name, card_input)
                        # New shape: (approved, edited_input). Tolerate a
                        # bare bool for any older callback.
                        if isinstance(decision, tuple):
                            approved = bool(decision[0])
                            edited_input = decision[1] if len(decision) > 1 else None
                        else:
                            approved = bool(decision)
                    except Exception as e:
                        logger.warning(
                            f"[approval] callback raised for tool={tool_name}: {e}; treating as declined"
                        )
                        approved = False
                    try:
                        input_keys = list((tool_input or {}).keys())
                    except Exception:
                        input_keys = []
                    logger.debug(
                        f"[approval] tool={tool_name} approved={approved} keys={input_keys}"
                    )
                    if not approved:
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": "User declined this action.",
                            }
                        )
                        continue
                    # The user may have edited the draft in the approval
                    # card (corrected recipient / body). Swap the edited
                    # input in before the tool runs.
                    if isinstance(edited_input, dict) and edited_input:
                        logger.info(
                            f"[approval] tool={tool_name} using edited input "
                            f"keys={list(edited_input.keys())}"
                        )
                        tool_input = edited_input

                # Execute tool
                tool_result = await self._call_tool(tool_name, tool_input)

                # Log tool result details for debugging
                logger.info(
                    f"[chat turn={tid} step={step}] tool={tool_name}"
                    f" input_keys={input_keys} status={tool_result.status.value}"
                )
                if tool_result.message:
                    logger.info(
                        f"[chat turn={tid} step={step}] tool={tool_name}"
                        f" message={tool_result.message}"
                    )
                    # Special logging for freshness check
                    if "fresh contact" in tool_result.message.lower():
                        logger.warning(
                            f"[chat turn={tid} step={step}] FRESH CONTACT DETECTED"
                            " — agent should NOT call Gmail/web search!"
                        )

                # Check if this is a direct response tool (bypass second LLM call)
                if (
                    tool_name in self.DIRECT_RESPONSE_TOOLS
                    and tool_result.status == ToolStatus.SUCCESS
                ):
                    logger.info(
                        f"Tool {tool_name} is a direct response tool - will skip second LLM call"
                    )
                    direct_response = tool_result.message
                    # Don't add to results - we're returning directly
                    continue

                # Format result for Anthropic, within the per-result budget.
                formatted_result, cut = bound_tool_result(
                    tool_name, self._format_tool_result(tool_result)
                )
                if cut:
                    logger.warning(
                        f"[chat turn={tid} step={step}] tool={tool_name} result truncated:"
                        f" {cut['original_chars']} chars -> {cut['shown_chars']}"
                        f" (budget {TOOL_RESULT_MAX_CHARS})"
                    )
                    self.last_truncations.append(cut)
                logger.debug(f"Formatted tool result sent to agent:\n{formatted_result}")

                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": formatted_result}
                )

        return results, direct_response

    async def _call_tool(self, name: str, input_data: Dict[str, Any]) -> ToolResult:
        """Call a registered tool.

        Args:
            name: Tool name
            input_data: Tool input parameters

        Returns:
            Tool execution result
        """
        if name not in self.tool_map:
            return ToolResult(status=ToolStatus.ERROR, data=None, error=f"Unknown tool: {name}")

        tool = self.tool_map[name]

        try:
            if name in _BLOCKING_TOOLS:
                result = await self._execute_off_loop(tool, input_data)
            else:
                # Stays on the loop, where a cancellation reaches it.
                result = await tool.execute(**input_data)
            return result
        except Exception as e:
            logger.error(f"Tool execution failed: {name} - {e}")
            return ToolResult(status=ToolStatus.ERROR, data=None, error=str(e))

    async def _execute_off_loop(self, tool: Tool, input_data: Dict[str, Any]) -> ToolResult:
        """Run a blocking tool's coroutine in the worker pool.

        Only tools in `_BLOCKING_TOOLS` come here: their work would
        otherwise freeze the event loop, and they have no `await` for a
        cancellation to land on anyway.

        Cancelling the caller returns immediately, and a thread that has
        already started keeps running — which at least keeps a tool's
        side effect and its bookkeeping on the same side of the
        interruption. A tool that has NOT started does not start: the
        executor future is cancellable while the work item is queued, and
        the flag below closes the sliver between "the worker picked the
        item up" and "the tool body began".

        The turn's context is carried across explicitly: a worker thread
        starts with an empty one, which would lose the turn id tools put
        in their log lines and the call-site tag LLM spend is attributed
        by. Each call copies its own context, so two concurrent turns
        never enter the same one.

        Args:
            tool: The tool to run.
            input_data: Keyword arguments for `tool.execute`.

        Returns:
            Whatever `tool.execute` returns.
        """
        loop = asyncio.get_running_loop()
        ctx = contextvars.copy_context()
        cancelled = threading.Event()

        def _runner() -> ToolResult:
            if cancelled.is_set():
                return ToolResult(
                    status=ToolStatus.ERROR,
                    data=None,
                    error=f"{tool.name} was not run - the turn was cancelled first",
                )
            return ctx.run(lambda: asyncio.run(tool.execute(**input_data)))

        try:
            return await loop.run_in_executor(get_tool_executor(), _runner)
        except asyncio.CancelledError:
            cancelled.set()
            logger.info(f"[tools] turn cancelled during blocking tool={tool.name}")
            raise

    def _format_tool_result(self, result: ToolResult) -> str:
        """Format tool result for Anthropic.

        Args:
            result: Tool execution result

        Returns:
            Formatted string for Anthropic
        """
        import json

        formatted = {
            "status": result.status.value,
            "data": result.data,
        }

        if result.message:
            formatted["message"] = result.message
        if result.error:
            formatted["error"] = result.error

        return json.dumps(formatted, indent=2, default=str)

    def clear_history(self) -> None:
        """Clear conversation history."""
        self.conversation_history = []
        logger.info("Cleared conversation history")

    def set_history(self, history: List[Dict[str, Any]]) -> None:
        """Restore conversation history from previous session.

        Args:
            history: List of conversation turns in Anthropic format:
                [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
        """
        self.conversation_history = history.copy()
        logger.info(f"Restored conversation history with {len(history)} messages")

    def get_history(self) -> List[Dict[str, Any]]:
        """Get conversation history.

        Returns:
            List of conversation turns
        """
        return self.conversation_history.copy()
