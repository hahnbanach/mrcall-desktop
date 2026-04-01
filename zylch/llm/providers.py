"""Provider configuration and feature flags for LLM providers."""

from typing import Dict, Any

from zylch.config import settings

# One model per provider — configured via env vars
PROVIDER_MODELS: Dict[str, str] = {
    "anthropic": settings.anthropic_model,
    "openai": settings.openai_model,
}

# Feature availability per provider
PROVIDER_FEATURES: Dict[str, Dict[str, bool]] = {
    "anthropic": {
        "tool_calling": True,
        "web_search": True,      # Built-in web_search_20250305 tool
        "prompt_caching": True,  # cache_control: {"type": "ephemeral"}
        "vision": True,
    },
    "openai": {
        "tool_calling": True,
        "web_search": True,      # Via Responses API (web_search_preview tool)
        "prompt_caching": False, # Anthropic-only feature
        "vision": True,
    },
}

# API key environment variable names (for reference)
PROVIDER_API_KEY_NAMES: Dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def get_provider_info(provider: str) -> Dict[str, Any]:
    """Get comprehensive info about a provider for display to user.

    Args:
        provider: Provider name (anthropic, openai, mistral)

    Returns:
        Dictionary with provider information
    """
    if provider not in PROVIDER_MODELS:
        return {
            "error": f"Unknown provider: {provider}. Supported: {', '.join(PROVIDER_MODELS.keys())}"
        }

    features = PROVIDER_FEATURES.get(provider, {})
    model = PROVIDER_MODELS[provider]

    available = [f for f, enabled in features.items() if enabled]
    unavailable = [f for f, enabled in features.items() if not enabled]

    return {
        "provider": provider,
        "model": model,
        "features": features,
        "available_features": available,
        "unavailable_features": unavailable,
        "is_eu": False,
    }


def get_model_string(provider: str) -> str:
    """Get the full model string for a provider (aisuite format: provider:model).

    Args:
        provider: Provider name (anthropic, openai, mistral, scaleway)

    Returns:
        Model string (e.g., "anthropic:claude-sonnet-4-20250514")
    """
    if provider not in PROVIDER_MODELS:
        raise ValueError(f"Unknown provider: {provider}")

    from .client import AISUITE_PROVIDER_KEYS
    aisuite_key = AISUITE_PROVIDER_KEYS.get(provider, provider)
    model = PROVIDER_MODELS[provider]
    return f"{aisuite_key}:{model}"


def format_provider_info_message(provider: str) -> str:
    """Format provider info as a user-friendly message.

    Args:
        provider: Provider name

    Returns:
        Formatted message string
    """
    info = get_provider_info(provider)

    if "error" in info:
        return info["error"]

    lines = [
        f"**{provider.upper()} Provider Connected**",
        f"",
        f"**Model:** `{info['model']}`",
    ]

    if info["is_eu"]:
        lines.append(f"**Region:** EU (GDPR compliant)")

    lines.append("")
    lines.append("**Features:**")

    for feature in ["tool_calling", "web_search", "prompt_caching", "vision"]:
        enabled = info["features"].get(feature, False)
        icon = "Y" if enabled else "N"
        feature_name = feature.replace("_", " ").title()
        lines.append(f"  [{icon}] {feature_name}")

    if info["unavailable_features"]:
        lines.append("")
        lines.append("*Note: Prompt caching is Anthropic-exclusive. Web search is available with Anthropic and OpenAI.*")

    return "\n".join(lines)


def get_system_llm_credentials(
    fallback_provider: str = "",
    fallback_api_key: str = "",
) -> tuple[str, str]:
    """Get system-level LLM credentials (for when user has no BYOK key).

    Used by MrCall dashboard and other integrations where the operator
    provides the API key (not the end user).

    Uses system_llm_provider setting to determine which system key to use.
    Falls back to provided values if no system key is available.

    Returns:
        (provider, api_key) tuple
    """
    provider = settings.system_llm_provider
    if provider == "anthropic" and settings.anthropic_api_key:
        return "anthropic", settings.anthropic_api_key
    if provider == "openai" and settings.openai_api_key:
        return "openai", settings.openai_api_key
    # Try any available key as last resort
    if settings.anthropic_api_key:
        return "anthropic", settings.anthropic_api_key
    if settings.openai_api_key:
        return "openai", settings.openai_api_key
    return fallback_provider, fallback_api_key
