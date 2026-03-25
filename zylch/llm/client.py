"""Unified LLM client using aisuite for multi-provider support.

This module provides a consistent interface for making LLM calls across
different providers (Anthropic, OpenAI, Mistral) while maintaining backward
compatibility with existing code that expects Anthropic response format.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import aisuite

from .providers import (
    PROVIDER_FEATURES,
    PROVIDER_MODELS,
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
    """Adapter that provides Anthropic-compatible response interface.

    aisuite returns OpenAI-format responses. This adapter translates them to
    Anthropic format so existing code doesn't need to change.
    """

    def __init__(self, aisuite_response: Any):
        self._raw = aisuite_response
        self._content: List[Union[TextBlock, ToolUseBlock]] = []
        self._stop_reason: str = "end_turn"
        self._parse_response()

    def _parse_response(self):
        """Parse response into Anthropic-compatible format.

        Handles both:
        - OpenAI format (choices[0].message with tool_calls)
        - Anthropic native format (content list with tool_use blocks, stop_reason)
        """
        # Anthropic native format: has .content as list and .stop_reason
        if hasattr(self._raw, 'stop_reason') and hasattr(self._raw, 'content') and isinstance(self._raw.content, list):
            for block in self._raw.content:
                if hasattr(block, 'type'):
                    if block.type == 'text':
                        self._content.append(TextBlock(text=block.text))
                    elif block.type == 'tool_use':
                        self._content.append(ToolUseBlock(
                            id=block.id,
                            name=block.name,
                            input=block.input if isinstance(block.input, dict) else {},
                        ))
            self._stop_reason = self._raw.stop_reason or "end_turn"
            return

        # OpenAI format: has .choices[0].message
        if not hasattr(self._raw, 'choices') or not self._raw.choices:
            return

        choice = self._raw.choices[0]
        message = choice.message

        if message.content:
            self._content.append(TextBlock(text=message.content))

        if hasattr(message, 'tool_calls') and message.tool_calls:
            for tool_call in message.tool_calls:
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
        return self._content

    @property
    def stop_reason(self) -> str:
        return self._stop_reason

    @property
    def model(self) -> str:
        return self._raw.model

    @property
    def usage(self) -> Dict[str, int]:
        if hasattr(self._raw, 'usage') and self._raw.usage:
            usage = self._raw.usage
            return {
                "input_tokens": getattr(usage, 'input_tokens', 0) or getattr(usage, 'prompt_tokens', 0),
                "output_tokens": getattr(usage, 'output_tokens', 0) or getattr(usage, 'completion_tokens', 0),
            }
        return {"input_tokens": 0, "output_tokens": 0}


# aisuite provider key mapping
AISUITE_PROVIDER_KEYS = {
    "anthropic": "anthropic",
    "openai": "openai",
    "mistral": "mistral",
    "scaleway": "mistral",  # Scaleway uses Mistral models
}


class LLMClient:
    """Unified LLM client using aisuite.

    Provides a consistent interface for making LLM calls across different providers
    (Anthropic, OpenAI, Mistral) while maintaining backward compatibility with
    existing code that expects Anthropic response format.

    Example:
        client = LLMClient(api_key="sk-...", provider="anthropic")
        response = await client.create_message(
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=1000,
        )
        print(response.content[0].text)
    """

    def __init__(
        self,
        api_key: str,
        provider: str,
        model: Optional[str] = None,
    ):
        if provider not in PROVIDER_MODELS:
            raise ValueError(
                f"Unknown provider: {provider}. "
                f"Supported: {', '.join(PROVIDER_MODELS.keys())}"
            )

        self.api_key = api_key
        self.provider = provider
        self.model = model or PROVIDER_MODELS[provider]
        self.features = PROVIDER_FEATURES.get(provider, {})

        # Build aisuite provider config with API key
        aisuite_key = AISUITE_PROVIDER_KEYS.get(provider, provider)
        provider_configs = {aisuite_key: {"api_key": api_key}}

        # For Scaleway, set the base URL for Mistral-compatible API
        if provider == "scaleway":
            provider_configs[aisuite_key]["base_url"] = "https://api.scaleway.ai/v1"

        self._client = aisuite.Client(provider_configs=provider_configs)

        logger.info(f"Initialized LLMClient with provider={provider}, model={self.model}")

    def _get_aisuite_model(self, model: Optional[str] = None) -> str:
        """Get aisuite-formatted model string (provider:model)."""
        model_name = model or self.model
        if ":" in model_name:
            return model_name
        aisuite_key = AISUITE_PROVIDER_KEYS.get(self.provider, self.provider)
        return f"{aisuite_key}:{model_name}"

    def _convert_tools_to_openai_format(
        self, tools: Optional[List[Dict[str, Any]]]
    ) -> Optional[List[Dict[str, Any]]]:
        """Convert Anthropic tool format to OpenAI format if needed."""
        if not tools:
            return None

        openai_tools = []
        for tool in tools:
            if "type" in tool and tool["type"] == "function":
                openai_tools.append(tool)
            else:
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
        """Convert Anthropic tool_choice format to OpenAI format."""
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
        """Convert Anthropic-style messages to OpenAI format.

        Handles:
        - Assistant messages with tool_use blocks -> assistant with tool_calls
        - User messages with tool_result blocks -> tool role messages
        """
        converted = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            # Handle tool results (Anthropic puts these in user messages)
            if role == "user" and isinstance(content, list):
                tool_results = [c for c in content if isinstance(c, dict) and c.get("type") == "tool_result"]
                if tool_results:
                    for result in tool_results:
                        result_content = result.get("content", "")
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
                    elif hasattr(block, "type"):
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
                        assistant_msg["content"] = None
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

        Returns:
            LLMResponse with Anthropic-compatible interface
        """
        # aisuite is synchronous — run in executor to avoid blocking
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self.create_message_sync(
                messages=messages,
                system=system,
                tools=tools,
                tool_choice=tool_choice,
                max_tokens=max_tokens,
                temperature=temperature,
                model=model,
                **kwargs
            )
        )

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
        """Synchronous version of create_message."""
        aisuite_model = self._get_aisuite_model(model)

        # Convert messages
        full_messages = self._convert_messages_to_openai_format(messages)
        if system:
            full_messages = [{"role": "system", "content": system}] + full_messages

        # Build request kwargs
        request_kwargs = {
            "model": aisuite_model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        # Tools and tool_choice format depends on provider
        # aisuite providers pass kwargs directly to their SDK, so we must match the provider's format
        if self.provider == "anthropic":
            # Anthropic SDK uses its own format (tools as-is, tool_choice as-is)
            if tools:
                request_kwargs["tools"] = tools
            if tool_choice:
                request_kwargs["tool_choice"] = tool_choice
        else:
            # OpenAI-compatible providers need OpenAI format
            openai_tools = self._convert_tools_to_openai_format(tools)
            openai_tool_choice = self._convert_tool_choice(tool_choice)
            if openai_tools:
                request_kwargs["tools"] = openai_tools
            if openai_tool_choice:
                request_kwargs["tool_choice"] = openai_tool_choice

        # Filter out Anthropic-specific kwargs for non-Anthropic providers
        anthropic_only_kwargs = {"cache_control"}
        for key, value in kwargs.items():
            if key in anthropic_only_kwargs and self.provider != "anthropic":
                logger.debug(f"Skipping Anthropic-only kwarg '{key}' for provider {self.provider}")
                continue
            request_kwargs[key] = value

        num_tools = len(request_kwargs.get("tools", []))
        logger.debug(f"aisuite request: model={aisuite_model}, messages={len(full_messages)}, tools={num_tools}")

        # Call provider directly to avoid aisuite's MCP config processing bug
        # (is_mcp_config not defined when mcp package not installed)
        provider_key, model_name = aisuite_model.split(":", 1)
        from aisuite.provider import ProviderFactory
        if provider_key not in self._client.providers:
            config = self._client.provider_configs.get(provider_key, {})
            self._client.providers[provider_key] = ProviderFactory.create_provider(provider_key, config)
        provider = self._client.providers[provider_key]
        del request_kwargs["model"]
        response = provider.chat_completions_create(model_name, full_messages, **{k: v for k, v in request_kwargs.items() if k != "messages"})

        return LLMResponse(response)

    def supports_feature(self, feature: str) -> bool:
        """Check if the current provider supports a feature."""
        return self.features.get(feature, False)
