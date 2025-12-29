"""Unified LLM client using LiteLLM for multi-provider support.

This module provides a drop-in replacement for direct Anthropic SDK usage,
supporting Anthropic, OpenAI, and Mistral through a unified interface.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from litellm import acompletion, completion

from .providers import (
    LITELLM_MODEL_PREFIXES,
    PROVIDER_FEATURES,
    PROVIDER_MODELS,
    get_litellm_model,
)

logger = logging.getLogger(__name__)


@dataclass
class ToolUseBlock:
    """Represents a tool use block in the response (Anthropic-compatible format)."""
    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: Dict[str, Any] = None

    def __post_init__(self):
        if self.input is None:
            self.input = {}


@dataclass
class TextBlock:
    """Represents a text block in the response (Anthropic-compatible format)."""
    type: str = "text"
    text: str = ""


class LLMResponse:
    """Adapter that provides Anthropic-compatible response interface for LiteLLM responses.

    LiteLLM returns OpenAI-format responses. This adapter translates them to
    Anthropic format so existing code doesn't need to change.

    OpenAI format:
    - response.choices[0].message.content
    - response.choices[0].message.tool_calls
    - response.choices[0].finish_reason == "tool_calls"

    Anthropic format (what we expose):
    - response.content (list of TextBlock/ToolUseBlock)
    - response.stop_reason == "tool_use" or "end_turn"
    - block.type, block.name, block.input, block.id
    """

    def __init__(self, litellm_response: Any):
        self._raw = litellm_response
        self._content: List[Union[TextBlock, ToolUseBlock]] = []
        self._stop_reason: str = "end_turn"
        self._parse_response()

    def _parse_response(self):
        """Parse LiteLLM/OpenAI response into Anthropic-compatible format."""
        if not self._raw.choices:
            return

        choice = self._raw.choices[0]
        message = choice.message

        # Parse text content
        if message.content:
            self._content.append(TextBlock(text=message.content))

        # Parse tool calls
        if message.tool_calls:
            for tool_call in message.tool_calls:
                # Parse arguments - they come as JSON string
                try:
                    args = json.loads(tool_call.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}

                self._content.append(ToolUseBlock(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    input=args,
                ))

            self._stop_reason = "tool_use"
        elif choice.finish_reason == "stop":
            self._stop_reason = "end_turn"
        else:
            self._stop_reason = choice.finish_reason or "end_turn"

    @property
    def content(self) -> List[Union[TextBlock, ToolUseBlock]]:
        """Get response content as list of blocks (Anthropic format)."""
        return self._content

    @property
    def stop_reason(self) -> str:
        """Get stop reason in Anthropic format ('tool_use', 'end_turn', etc.)."""
        return self._stop_reason

    @property
    def model(self) -> str:
        """Get the model that generated the response."""
        return self._raw.model

    @property
    def usage(self) -> Dict[str, int]:
        """Get token usage information."""
        if hasattr(self._raw, 'usage') and self._raw.usage:
            return {
                "input_tokens": self._raw.usage.prompt_tokens,
                "output_tokens": self._raw.usage.completion_tokens,
            }
        return {"input_tokens": 0, "output_tokens": 0}


class LLMClient:
    """Unified LLM client using LiteLLM.

    Provides a consistent interface for making LLM calls across different providers
    (Anthropic, OpenAI, Mistral) while maintaining backward compatibility with
    existing code that expects Anthropic response format.

    Example:
        client = LLMClient(api_key="sk-...", provider="anthropic")
        response = await client.create_message(
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=1000,
        )
        # Response has Anthropic-compatible interface
        print(response.content[0].text)
    """

    def __init__(
        self,
        api_key: str,
        provider: str,
        model: Optional[str] = None,
    ):
        """Initialize LLM client.

        Args:
            api_key: API key for the provider
            provider: Provider name (anthropic, openai, mistral)
            model: Optional model override. If not provided, uses PROVIDER_MODELS default.
        """
        if provider not in PROVIDER_MODELS:
            raise ValueError(
                f"Unknown provider: {provider}. "
                f"Supported: {', '.join(PROVIDER_MODELS.keys())}"
            )

        self.api_key = api_key
        self.provider = provider
        self.model = model or PROVIDER_MODELS[provider]
        self.features = PROVIDER_FEATURES.get(provider, {})

        logger.info(f"Initialized LLMClient with provider={provider}, model={self.model}")

    def _get_litellm_model(self, model: Optional[str] = None) -> str:
        """Get LiteLLM-formatted model string.

        Args:
            model: Optional model name override

        Returns:
            LiteLLM model string (e.g., "anthropic/claude-sonnet-4-20250514")
        """
        model_name = model or self.model

        # If already has prefix, use as-is
        if "/" in model_name:
            return model_name

        # Add provider prefix
        prefix = LITELLM_MODEL_PREFIXES.get(self.provider, self.provider)
        return f"{prefix}/{model_name}"

    def _convert_tools_to_openai_format(
        self, tools: Optional[List[Dict[str, Any]]]
    ) -> Optional[List[Dict[str, Any]]]:
        """Convert Anthropic tool format to OpenAI format if needed.

        Anthropic format:
            {"name": "...", "description": "...", "input_schema": {...}}

        OpenAI format:
            {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}

        LiteLLM handles this conversion, but we ensure consistency.
        """
        if not tools:
            return None

        openai_tools = []
        for tool in tools:
            # Check if already in OpenAI format
            if "type" in tool and tool["type"] == "function":
                openai_tools.append(tool)
            else:
                # Convert from Anthropic format
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "parameters": tool.get("input_schema", {}),
                    }
                })

        return openai_tools

    def _convert_tool_choice(
        self, tool_choice: Optional[Dict[str, Any]]
    ) -> Optional[Union[str, Dict[str, Any]]]:
        """Convert Anthropic tool_choice format to OpenAI format.

        Anthropic format:
            {"type": "tool", "name": "my_tool"}  # Force specific tool
            {"type": "auto"}  # Let model decide
            {"type": "any"}  # Model must use a tool

        OpenAI format:
            {"type": "function", "function": {"name": "my_tool"}}
            "auto"
            "required"
        """
        if not tool_choice:
            return None

        choice_type = tool_choice.get("type", "auto")

        if choice_type == "auto":
            return "auto"
        elif choice_type == "any":
            return "required"
        elif choice_type == "tool":
            tool_name = tool_choice.get("name", "")
            return {
                "type": "function",
                "function": {"name": tool_name}
            }

        return "auto"

    def _convert_messages_to_openai_format(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert Anthropic-style messages to OpenAI format for LiteLLM.

        Handles:
        - Assistant messages with tool_use blocks → assistant with tool_calls
        - User messages with tool_result blocks → tool role messages

        This is necessary because core.py stores conversation history in Anthropic format,
        but LiteLLM expects OpenAI format.
        """
        converted = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            # Handle tool results (Anthropic puts these in user messages)
            if role == "user" and isinstance(content, list):
                tool_results = [c for c in content if isinstance(c, dict) and c.get("type") == "tool_result"]
                if tool_results:
                    # Convert each tool_result to a separate tool message
                    for result in tool_results:
                        result_content = result.get("content", "")
                        # Handle case where content might be a list (e.g., with images)
                        if isinstance(result_content, list):
                            result_content = json.dumps(result_content)
                        converted.append({
                            "role": "tool",
                            "tool_call_id": result.get("tool_use_id", ""),
                            "content": str(result_content),
                        })
                    continue

            # Handle assistant messages with tool use blocks
            if role == "assistant" and isinstance(content, list):
                text_parts = []
                tool_calls = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": block.get("name", ""),
                                    "arguments": json.dumps(block.get("input", {})),
                                }
                            })
                        elif block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                    elif hasattr(block, "type"):  # ToolUseBlock or TextBlock dataclass
                        if block.type == "tool_use":
                            tool_calls.append({
                                "id": block.id,
                                "type": "function",
                                "function": {
                                    "name": block.name,
                                    "arguments": json.dumps(block.input),
                                }
                            })
                        elif block.type == "text":
                            text_parts.append(block.text)

                assistant_msg = {"role": "assistant"}
                if text_parts:
                    assistant_msg["content"] = "\n".join(text_parts)
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                    if "content" not in assistant_msg:
                        assistant_msg["content"] = None  # OpenAI requires content field
                converted.append(assistant_msg)
                continue

            # Pass through other messages unchanged
            converted.append(msg)

        return converted

    async def create_message(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Dict[str, Any]] = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        model: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """Create a message with optional tool calling.

        Args:
            messages: List of message dicts ({"role": "user", "content": "..."})
            system: Optional system prompt
            tools: Optional list of tool definitions (Anthropic or OpenAI format)
            tool_choice: Optional tool choice config (Anthropic format supported)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            model: Optional model override
            **kwargs: Additional arguments passed to LiteLLM

        Returns:
            LLMResponse with Anthropic-compatible interface
        """
        litellm_model = self._get_litellm_model(model)

        # Convert messages from Anthropic format to OpenAI format
        # This handles tool_use blocks and tool_result blocks in conversation history
        full_messages = self._convert_messages_to_openai_format(messages)
        if system:
            full_messages = [{"role": "system", "content": system}] + full_messages

        # Convert tools to OpenAI format
        openai_tools = self._convert_tools_to_openai_format(tools)

        # Convert tool_choice to OpenAI format
        openai_tool_choice = self._convert_tool_choice(tool_choice)

        # Build request kwargs
        request_kwargs = {
            "model": litellm_model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "api_key": self.api_key,
        }

        if openai_tools:
            request_kwargs["tools"] = openai_tools
        if openai_tool_choice:
            request_kwargs["tool_choice"] = openai_tool_choice

        # Add any extra kwargs (but filter out Anthropic-specific ones for non-Anthropic providers)
        anthropic_only_kwargs = {"cache_control"}
        for key, value in kwargs.items():
            if key in anthropic_only_kwargs and self.provider != "anthropic":
                logger.debug(f"Skipping Anthropic-only kwarg '{key}' for provider {self.provider}")
                continue
            request_kwargs[key] = value

        logger.debug(f"LiteLLM request: model={litellm_model}, messages={len(full_messages)}, tools={len(openai_tools) if openai_tools else 0}")

        # Make the async request
        response = await acompletion(**request_kwargs)

        return LLMResponse(response)

    def create_message_sync(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Dict[str, Any]] = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        model: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """Synchronous version of create_message.

        Same arguments as create_message but runs synchronously.
        """
        litellm_model = self._get_litellm_model(model)

        # Convert messages from Anthropic format to OpenAI format
        full_messages = self._convert_messages_to_openai_format(messages)
        if system:
            full_messages = [{"role": "system", "content": system}] + full_messages

        # Convert tools to OpenAI format
        openai_tools = self._convert_tools_to_openai_format(tools)

        # Convert tool_choice to OpenAI format
        openai_tool_choice = self._convert_tool_choice(tool_choice)

        # Build request kwargs
        request_kwargs = {
            "model": litellm_model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "api_key": self.api_key,
        }

        if openai_tools:
            request_kwargs["tools"] = openai_tools
        if openai_tool_choice:
            request_kwargs["tool_choice"] = openai_tool_choice

        # Add any extra kwargs
        anthropic_only_kwargs = {"cache_control"}
        for key, value in kwargs.items():
            if key in anthropic_only_kwargs and self.provider != "anthropic":
                continue
            request_kwargs[key] = value

        logger.debug(f"LiteLLM sync request: model={litellm_model}")

        # Make the sync request
        response = completion(**request_kwargs)

        return LLMResponse(response)

    def supports_feature(self, feature: str) -> bool:
        """Check if the current provider supports a feature.

        Args:
            feature: Feature name (tool_calling, web_search, prompt_caching, vision)

        Returns:
            True if feature is supported
        """
        return self.features.get(feature, False)
