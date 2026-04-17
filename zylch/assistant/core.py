"""Core Zylch AI agent using LLM abstraction layer."""

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..llm import LLMClient
from .models import ModelSelector
from .prompts import get_system_prompt, get_system_prompt_base
from .turn_context import new_turn_id, get_turn_id
from ..tools.base import Tool, ToolResult, ToolStatus
from ..agents.base import BaseConversationalAgent
from ..services.task_executor import APPROVAL_TOOLS

# Type alias for approval callback: (tool_use_id, tool_name, input_dict) -> approved
ApprovalCallback = Callable[[str, str, Dict[str, Any]], Awaitable[bool]]

logger = logging.getLogger(__name__)


class ZylchAIAgent(BaseConversationalAgent):
    """Main conversational agent for Zylch AI.

    Single-agent architecture with native function calling via Anthropic SDK.
    """

    def __init__(
        self,
        api_key: str,
        tools: List[Tool],
        provider: str,
        model_selector: Optional[ModelSelector] = None,
        max_tokens: int = 4096,
        triggered_instructions: Optional[List[str]] = None,
    ):
        """Initialize Zylch AI agent.

        Args:
            api_key: API key for the LLM provider
            tools: List of available tools
            model_selector: Model selection logic (optional)
            max_tokens: Maximum tokens for response
            triggered_instructions: List of triggered instructions (optional, for prompt injection)
            provider: LLM provider (anthropic, openai, mistral)
        """
        self.client = LLMClient(api_key=api_key, provider=provider)
        self.provider = provider
        self.tools = tools
        self.tool_map = {tool.name: tool for tool in tools}
        self.model_selector = model_selector or ModelSelector()
        self.max_tokens = max_tokens
        self.triggered_instructions = triggered_instructions or []
        self.conversation_history: List[Dict[str, Any]] = []
        self.message_count = 0

        logger.info(
            f"Initialized Zylch AI agent with {len(tools)} tools, provider={provider}{f' and {len(self.triggered_instructions)} triggered instructions' if self.triggered_instructions else ''}"
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

        # Add user message to history
        self.conversation_history.append({"role": "user", "content": user_message})

        # Select appropriate model (check for forced model in context)
        force_model = context.get("force_model") if context else None
        model = self.model_selector.select_model(user_message, context, force_model=force_model)
        logger.info(f"[chat turn={turn_id}] Using model: {model}")

        # Build system prompt with context
        system_prompt = get_system_prompt() + get_system_prompt_base()
        if context and context.get("current_business_id"):
            system_prompt += f"\n\n**CURRENT SESSION:**\n✅ Selected MrCall Assistant: {context['current_business_id']}\nYou CAN save contacts directly to this assistant."

        # Inject triggered instructions (for prompt awareness - NOT for execution)
        # Note: Trigger execution happens elsewhere (e.g., ChatService.execute_session_start_triggers)
        # This just makes the AI aware of the triggers in case they're relevant during conversation
        if self.triggered_instructions:
            instructions_text = "\n".join(f"- {instr}" for instr in self.triggered_instructions)
            system_prompt += f"\n\n**TRIGGERED INSTRUCTIONS (event-driven, for reference):**\n{instructions_text}"
            logger.info(
                f"Injected {len(self.triggered_instructions)} triggered instructions into system prompt"
            )

        # Create message with tool support (with current date/time)
        # Note: model selection is now handled by LLMClient based on provider
        response = await self.client.create_message(
            messages=self.conversation_history,
            system=system_prompt,
            tools=self._get_tool_schemas(),
            max_tokens=self.max_tokens,
        )

        # Handle tool use loop
        step = 0
        while response.stop_reason == "tool_use":
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
            response = await self.client.create_message(
                messages=self.conversation_history,
                system=system_prompt,  # Use same system prompt with context
                tools=self._get_tool_schemas(),
                max_tokens=self.max_tokens,
            )

        # Extract final text response
        assistant_message = ""
        for block in response.content:
            if hasattr(block, "text"):
                assistant_message += block.text

        # Add final response to history
        self.conversation_history.append({"role": "assistant", "content": assistant_message})

        self.message_count += 1

        return assistant_message

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

                # Approval gate for destructive tools
                if approval_callback is not None and tool_name in APPROVAL_TOOLS:
                    approved = False
                    try:
                        approved = bool(
                            await approval_callback(block.id, tool_name, dict(tool_input or {}))
                        )
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

                # Format result for Anthropic
                formatted_result = self._format_tool_result(tool_result)
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
            result = await tool.execute(**input_data)
            return result
        except Exception as e:
            logger.error(f"Tool execution failed: {name} - {e}")
            return ToolResult(status=ToolStatus.ERROR, data=None, error=str(e))

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
