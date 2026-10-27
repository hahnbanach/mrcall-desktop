"""Guarded LLM transports and explicit per-role model policy."""

from .client import (
    LLMClient,
    LLMResponse,
    TextBlock,
    ToolUseBlock,
    make_llm_client,
    try_make_llm_client,
)


def routed_model(env_key: str) -> str | None:
    """Resolve an explicit role override or the selected provider's preset."""
    from .model_policy import profile_values, resolve_model

    values = profile_values()
    explicit = str(values.get(env_key) or "").strip()
    if explicit:
        return explicit
    if str(values.get("LLM_MODEL_PRESET") or "custom").strip() == "custom":
        return None  # Factory resolves its base model; legacy worker contract.
    return resolve_model(env_key, values=values)


__all__ = [
    "LLMClient",
    "LLMResponse",
    "TextBlock",
    "ToolUseBlock",
    "make_llm_client",
    "routed_model",
    "try_make_llm_client",
]
