"""Guarded LLM transports and explicit per-role model policy."""

from .client import (
    LLMClient,
    LLMResponse,
    TextBlock,
    ToolUseBlock,
    make_llm_client,
    try_make_llm_client,
)


def routed_model(env_key: str) -> str:
    """Resolve a role's model: its explicit override, else the selected
    provider's preset; `custom` with no base model resolves the role under
    `economy`, so a routed caller never receives None."""
    from .model_policy import resolve_model

    return resolve_model(env_key)


def llm_available() -> bool:
    """True when the saved provider has its credential: a probe for callers
    that only ask whether AI can run. No model is resolved, no client built,
    and it never raises (unreadable settings read as unavailable)."""
    from .budget_pricing import BudgetError
    from .model_policy import profile_values, resolve_provider

    try:
        values = profile_values()
        provider = resolve_provider(values)
    except BudgetError:
        return False
    if provider in ("anthropic", "openrouter"):
        key = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENROUTER_API_KEY"
        return bool(str(values.get(key) or "").strip())
    try:
        from zylch.auth import get_session

        return get_session() is not None
    except Exception:  # noqa: BLE001 - a probe answers, it does not raise
        return False


__all__ = [
    "LLMClient",
    "LLMResponse",
    "TextBlock",
    "ToolUseBlock",
    "llm_available",
    "make_llm_client",
    "routed_model",
    "try_make_llm_client",
]
