"""Unified LLM client — direct SDK calls to Anthropic / OpenAI.

Replaces aisuite with direct provider SDK usage to avoid
dependency conflicts (aisuite pins httpx<0.28, neonize needs >=0.28).
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from .providers import PROVIDER_FEATURES, PROVIDER_MODELS

logger = logging.getLogger(__name__)


@dataclass
class ToolUseBlock:
    """Tool use block (Anthropic-compatible format)."""

    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: Dict[str, Any] = None

    def __post_init__(self):
        if self.input is None:
            self.input = {}


@dataclass
class TextBlock:
    """Text block (Anthropic-compatible format)."""

    type: str = "text"
    text: str = ""


class LLMResponse:
    """Adapter providing Anthropic-compatible response interface.

    Normalizes both Anthropic and OpenAI response formats into
    a consistent interface with .content, .stop_reason, .usage.
    """

    def __init__(self, raw_response: Any):
        self._raw = raw_response
        self._content: List[Union[TextBlock, ToolUseBlock]] = []
        self._stop_reason: str = "end_turn"
        self._parse_response()

    def _parse_response(self):
        """Parse into Anthropic-compatible format."""
        # Anthropic native: has .stop_reason and .content as list
        if hasattr(self._raw, "stop_reason") and hasattr(self._raw, "content"):
            if isinstance(self._raw.content, list):
                for block in self._raw.content:
                    if hasattr(block, "type"):
                        if block.type == "text":
                            self._content.append(
                                TextBlock(text=block.text),
                            )
                        elif block.type == "tool_use":
                            inp = block.input if isinstance(block.input, dict) else {}
                            self._content.append(
                                ToolUseBlock(
                                    id=block.id,
                                    name=block.name,
                                    input=inp,
                                ),
                            )
                self._stop_reason = self._raw.stop_reason or "end_turn"
                return

        # OpenAI format: has .choices[0].message
        if not hasattr(self._raw, "choices") or not self._raw.choices:
            return

        choice = self._raw.choices[0]
        message = choice.message

        if message.content:
            self._content.append(TextBlock(text=message.content))

        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                self._content.append(
                    ToolUseBlock(
                        id=tc.id,
                        name=tc.function.name,
                        input=args,
                    ),
                )
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
        if hasattr(self._raw, "usage") and self._raw.usage:
            u = self._raw.usage
            return {
                "input_tokens": getattr(
                    u,
                    "input_tokens",
                    0,
                )
                or getattr(u, "prompt_tokens", 0),
                "output_tokens": getattr(
                    u,
                    "output_tokens",
                    0,
                )
                or getattr(u, "completion_tokens", 0),
                # Anthropic-only cache metrics; 0 when absent (OpenAI etc.)
                "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
                "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
            }
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }


class LLMClient:
    """Unified LLM client — calls Anthropic or OpenAI SDK directly.

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
                f"Unknown provider: {provider}. " f"Supported: {', '.join(PROVIDER_MODELS.keys())}"
            )

        self.api_key = api_key
        self.provider = provider
        self.model = model or PROVIDER_MODELS[provider]
        self.features = PROVIDER_FEATURES.get(provider, {})

        # Initialize the appropriate SDK client
        if provider == "anthropic":
            import anthropic

            self._client = anthropic.Anthropic(api_key=api_key)
        elif provider == "openai":
            import openai

            self._client = openai.OpenAI(api_key=api_key)
        elif provider == "mrcall":
            # Credits mode — route through mrcall-agent's proxy. The
            # credential is the Firebase ID token held in
            # zylch.auth.session, NOT the `api_key` arg (which the
            # caller may pass as "" since the user has no BYOK key in
            # this mode). Fail fast at init time if no session exists
            # so the renderer surfaces a clear "sign in first" error
            # instead of a confusing 401 mid-conversation.
            from zylch.auth import get_session
            from zylch.config import settings

            from .proxy_client import MrCallProxyClient

            session = get_session()
            if session is None:
                raise RuntimeError(
                    "MrCall credits require Firebase signin. "
                    "Use Settings → Sign In."
                )
            self._client = MrCallProxyClient(
                proxy_base_url=settings.mrcall_proxy_url,
                firebase_session=session,
            )
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        logger.info(
            f"Initialized LLMClient with" f" provider={provider}, model={self.model}",
        )

    def _convert_tools_to_openai_format(
        self,
        tools: Optional[List[Dict[str, Any]]],
    ) -> Optional[List[Dict[str, Any]]]:
        """Convert Anthropic tool format to OpenAI format."""
        if not tools:
            return None
        openai_tools = []
        for tool in tools:
            if "type" in tool and tool["type"] == "function":
                openai_tools.append(tool)
            else:
                openai_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.get("name", ""),
                            "description": tool.get(
                                "description",
                                "",
                            ),
                            "parameters": tool.get(
                                "input_schema",
                                {},
                            ),
                        },
                    }
                )
        return openai_tools

    def _convert_tool_choice(
        self,
        tool_choice: Optional[Dict[str, Any]],
    ) -> Optional[Union[str, Dict[str, Any]]]:
        """Convert Anthropic tool_choice to OpenAI format."""
        if not tool_choice:
            return None
        choice_type = tool_choice.get("type", "auto")
        if choice_type == "auto":
            return "auto"
        elif choice_type == "any":
            return "required"
        elif choice_type == "tool":
            return {
                "type": "function",
                "function": {
                    "name": tool_choice.get("name", ""),
                },
            }
        return "auto"

    def _convert_messages_to_openai_format(
        self,
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Convert Anthropic-style messages to OpenAI format.

        Handles tool_use blocks and tool_result blocks.
        """
        converted = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            # Tool results (Anthropic: user message with tool_result)
            if role == "user" and isinstance(content, list):
                tool_results = [
                    c for c in content if isinstance(c, dict) and c.get("type") == "tool_result"
                ]
                if tool_results:
                    for result in tool_results:
                        rc = result.get("content", "")
                        if isinstance(rc, list):
                            rc = json.dumps(rc)
                        converted.append(
                            {
                                "role": "tool",
                                "tool_call_id": result.get(
                                    "tool_use_id",
                                    "",
                                ),
                                "content": str(rc),
                            }
                        )
                    continue

            # Assistant messages with tool_use blocks
            if role == "assistant" and isinstance(
                content,
                list,
            ):
                text_parts = []
                tool_calls = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            tool_calls.append(
                                {
                                    "id": block.get("id", ""),
                                    "type": "function",
                                    "function": {
                                        "name": block.get(
                                            "name",
                                            "",
                                        ),
                                        "arguments": json.dumps(
                                            block.get(
                                                "input",
                                                {},
                                            ),
                                        ),
                                    },
                                }
                            )
                        elif block.get("type") == "text":
                            text_parts.append(
                                block.get("text", ""),
                            )
                    elif hasattr(block, "type"):
                        if block.type == "tool_use":
                            tool_calls.append(
                                {
                                    "id": block.id,
                                    "type": "function",
                                    "function": {
                                        "name": block.name,
                                        "arguments": json.dumps(
                                            block.input,
                                        ),
                                    },
                                }
                            )
                        elif block.type == "text":
                            text_parts.append(block.text)

                assistant_msg = {"role": "assistant"}
                if text_parts:
                    assistant_msg["content"] = "\n".join(
                        text_parts,
                    )
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                    if "content" not in assistant_msg:
                        assistant_msg["content"] = None
                converted.append(assistant_msg)
                continue

            converted.append(msg)

        return converted

    async def create_message(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[Union[str, List[Dict[str, Any]]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Dict[str, Any]] = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        model: Optional[str] = None,
        **kwargs,
    ) -> LLMResponse:
        """Create a message with optional tool calling."""
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
                **kwargs,
            ),
        )

    def _call_anthropic(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[Union[str, List[Dict[str, Any]]]],
        tools: Optional[List[Dict[str, Any]]],
        tool_choice: Optional[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        model: str,
        **kwargs,
    ) -> Any:
        """Call Anthropic SDK directly."""

        # Coerce any SDK block objects (TextBlock/ToolUseBlock) lingering
        # in messages to plain dicts — otherwise anthropic's request JSON
        # serializer raises "Object of type TextBlock is not JSON
        # serializable".
        def _coerce_block(b):
            if isinstance(b, dict):
                return b
            btype = getattr(b, "type", None)
            if btype == "text":
                return {"type": "text", "text": getattr(b, "text", "")}
            if btype == "tool_use":
                return {
                    "type": "tool_use",
                    "id": getattr(b, "id", ""),
                    "name": getattr(b, "name", ""),
                    "input": dict(getattr(b, "input", {}) or {}),
                }
            if hasattr(b, "model_dump"):
                try:
                    return b.model_dump()
                except Exception:
                    pass
            return b

        coerced_messages = []
        for m in messages:
            content = m.get("content") if isinstance(m, dict) else None
            if isinstance(content, list):
                new_content = [_coerce_block(b) for b in content]
                coerced_messages.append({**m, "content": new_content})
            else:
                coerced_messages.append(m)

        request_kwargs = {
            "model": model,
            "messages": coerced_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            request_kwargs["system"] = system
        if tools:
            request_kwargs["tools"] = tools
        if tool_choice:
            request_kwargs["tool_choice"] = tool_choice

        # Pass through Anthropic-compatible kwargs
        for key, value in kwargs.items():
            request_kwargs[key] = value

        num_tools = len(tools) if tools else 0
        logger.debug(
            f"anthropic request: model={model}," f" messages={len(messages)}, tools={num_tools}",
        )

        return self._client.messages.create(**request_kwargs)

    def _call_openai(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str],
        tools: Optional[List[Dict[str, Any]]],
        tool_choice: Optional[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        model: str,
        **kwargs,
    ) -> Any:
        """Call OpenAI SDK directly."""
        full_messages = self._convert_messages_to_openai_format(
            messages,
        )
        if system:
            full_messages = [
                {"role": "system", "content": system},
            ] + full_messages

        request_kwargs = {
            "model": model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        openai_tools = self._convert_tools_to_openai_format(
            tools,
        )
        if openai_tools:
            request_kwargs["tools"] = openai_tools

        if tool_choice:
            oai_choice = self._convert_tool_choice(tool_choice)
            if oai_choice:
                request_kwargs["tool_choice"] = oai_choice

        # Filter out Anthropic-only kwargs
        anthropic_only = {"cache_control"}
        for key, value in kwargs.items():
            if key not in anthropic_only:
                request_kwargs[key] = value

        num_tools = len(request_kwargs.get("tools", []))
        logger.debug(
            f"openai request: model={model},"
            f" messages={len(full_messages)},"
            f" tools={num_tools}",
        )

        return self._client.chat.completions.create(
            **request_kwargs,
        )

    def create_message_sync(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[Union[str, List[Dict[str, Any]]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Dict[str, Any]] = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        model: Optional[str] = None,
        **kwargs,
    ) -> LLMResponse:
        """Synchronous version of create_message."""
        model_name = model or self.model

        if self.provider == "anthropic" or self.provider == "mrcall":
            # MrCall-credits mode reuses the Anthropic call path because
            # the proxy mirrors the SDK surface (`client.messages.create`)
            # and returns Anthropic-shaped Message objects. The only
            # difference is that `self._client` is a MrCallProxyClient
            # instead of `anthropic.Anthropic`.
            response = self._call_anthropic(
                messages,
                system,
                tools,
                tool_choice,
                max_tokens,
                temperature,
                model_name,
                **kwargs,
            )
        elif self.provider == "openai":
            response = self._call_openai(
                messages,
                system,
                tools,
                tool_choice,
                max_tokens,
                temperature,
                model_name,
                **kwargs,
            )
        else:
            raise ValueError(
                f"Unsupported provider: {self.provider}",
            )

        return LLMResponse(response)

    def supports_feature(self, feature: str) -> bool:
        """Check if the current provider supports a feature."""
        return self.features.get(feature, False)
