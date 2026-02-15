"""LLM abstraction layer using LiteLLM for multi-provider support.

Supported providers:
- Anthropic (claude-opus-4-6-20260205) - Full features including web search and prompt caching
- OpenAI (gpt-4.1) - Tool calling supported, no web search or prompt caching
- Mistral (mistral-large-3) - Tool calling supported, no web search or prompt caching
"""

from .client import LLMClient
from .providers import PROVIDER_MODELS, PROVIDER_FEATURES, get_provider_info

__all__ = [
    "LLMClient",
    "PROVIDER_MODELS",
    "PROVIDER_FEATURES",
    "get_provider_info",
]
