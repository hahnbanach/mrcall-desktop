"""Core MrPark agent using Anthropic SDK."""

import logging
from typing import Any, Dict, List, Optional

import anthropic

from .models import ModelSelector
from .prompts import get_system_prompt, get_system_prompt_base
from ..tools.base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


class MrParkAgent:
    """Main conversational agent for MrPark.

    Single-agent architecture with native function calling via Anthropic SDK.
    """

    def __init__(
        self,
        api_key: str,
        tools: List[Tool],
        model_selector: Optional[ModelSelector] = None,
        max_tokens: int = 4096,
        email_style_prompt: Optional[str] = None,
        memory_system: Optional[Any] = None,
    ):
        """Initialize MrPark agent.

        Args:
            api_key: Anthropic API key
            tools: List of available tools
            model_selector: Model selection logic (optional)
            max_tokens: Maximum tokens for response
            email_style_prompt: Custom email style instructions
            memory_system: ReasoningBankMemory instance (optional)
        """
        self.client = anthropic.Anthropic(api_key=api_key)
        self.tools = tools
        self.tool_map = {tool.name: tool for tool in tools}
        self.model_selector = model_selector or ModelSelector()
        self.max_tokens = max_tokens
        self.email_style_prompt = email_style_prompt
        self.memory_system = memory_system
        self.conversation_history: List[Dict[str, Any]] = []

        logger.info(f"Initialized MrPark agent with {len(tools)} tools{' and memory system' if memory_system else ''}")

    def _get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Get Anthropic tool schemas for all registered tools.

        Returns:
            List of tool schemas
        """
        return [tool.get_schema() for tool in self.tools]

    async def process_message(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Process user message with tool use.

        Args:
            user_message: User's message
            context: Optional context (e.g., contact info, settings)

        Returns:
            Agent's response
        """
        # Add user message to history
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        # Select appropriate model
        model = self.model_selector.select_model(user_message, context)
        logger.info(f"Using model: {model}")

        # Build system prompt with context and email style preferences
        system_prompt = get_system_prompt() + get_system_prompt_base(self.email_style_prompt)
        if context and context.get("current_business_id"):
            system_prompt += f"\n\n**CURRENT SESSION:**\n✅ Selected MrCall Assistant: {context['current_business_id']}\nYou CAN save contacts directly to this assistant."

        # Inject memory prompt (global + personal rules for channel)
        if self.memory_system:
            # Get channel from context, default to email
            channel = context.get("channel", "email") if context else "email"

            memory_prompt = self.memory_system.build_memory_prompt(
                channel=channel,
                task_description=f"interacting with contacts via {channel}"
            )
            if memory_prompt:
                system_prompt += memory_prompt
                logger.info(f"Injected memory rules for channel={channel}")

        # Create message with tool support (with current date/time)
        response = self.client.messages.create(
            model=model,
            max_tokens=self.max_tokens,
            system=system_prompt,
            tools=self._get_tool_schemas(),
            messages=self.conversation_history
        )

        # Handle tool use loop
        while response.stop_reason == "tool_use":
            # Extract tool calls from response
            tool_results = await self._execute_tools(response.content)

            # Add assistant's tool use to history
            self.conversation_history.append({
                "role": "assistant",
                "content": response.content
            })

            # Add tool results to history
            self.conversation_history.append({
                "role": "user",
                "content": tool_results
            })

            # Continue conversation with tool results (with current date/time)
            response = self.client.messages.create(
                model=model,
                max_tokens=self.max_tokens,
                system=system_prompt,  # Use same system prompt with context
                tools=self._get_tool_schemas(),
                messages=self.conversation_history
            )

        # Extract final text response
        assistant_message = ""
        for block in response.content:
            if hasattr(block, 'text'):
                assistant_message += block.text

        # Add final response to history
        self.conversation_history.append({
            "role": "assistant",
            "content": assistant_message
        })

        return assistant_message

    async def _execute_tools(self, content: List[Any]) -> List[Dict[str, Any]]:
        """Execute tool calls from response.

        Args:
            content: Response content blocks

        Returns:
            Tool results for Anthropic API
        """
        results = []

        for block in content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input

                logger.info(f"Executing tool: {tool_name}")
                logger.debug(f"Tool input: {tool_input}")

                # Execute tool
                tool_result = await self._call_tool(tool_name, tool_input)

                # Log tool result details for debugging
                logger.info(f"Tool {tool_name} result status: {tool_result.status.value}")
                if tool_result.message:
                    logger.info(f"Tool {tool_name} message: {tool_result.message}")
                    # Special logging for freshness check
                    if "fresh contact" in tool_result.message.lower():
                        logger.warning(f"⚠️  FRESH CONTACT DETECTED - Agent should NOT call Gmail/web search!")

                # Format result for Anthropic
                formatted_result = self._format_tool_result(tool_result)
                logger.debug(f"Formatted tool result sent to agent:\n{formatted_result}")

                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": formatted_result
                })

        return results

    async def _call_tool(self, name: str, input_data: Dict[str, Any]) -> ToolResult:
        """Call a registered tool.

        Args:
            name: Tool name
            input_data: Tool input parameters

        Returns:
            Tool execution result
        """
        if name not in self.tool_map:
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Unknown tool: {name}"
            )

        tool = self.tool_map[name]

        try:
            result = await tool.execute(**input_data)
            return result
        except Exception as e:
            logger.error(f"Tool execution failed: {name} - {e}")
            return ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=str(e)
            )

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

    def get_history(self) -> List[Dict[str, Any]]:
        """Get conversation history.

        Returns:
            List of conversation turns
        """
        return self.conversation_history.copy()
