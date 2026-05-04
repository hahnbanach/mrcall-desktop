"""LLM abstraction layer.

Single provider (Anthropic), two transports (``direct`` BYOK and
``proxy`` MrCall credits). See :mod:`zylch.llm.client` for the
:class:`LLMClient` and the :func:`make_llm_client` factory most
callers use.
"""

from .client import LLMClient, LLMResponse, TextBlock, ToolUseBlock, make_llm_client, try_make_llm_client

__all__ = [
    "LLMClient",
    "LLMResponse",
    "TextBlock",
    "ToolUseBlock",
    "make_llm_client",
    "try_make_llm_client",
]
