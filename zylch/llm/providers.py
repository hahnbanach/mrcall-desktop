"""Provider configuration and feature flags for LLM providers."""

from typing import Dict, Any


# Single model per provider (Sonnet-equivalent tier)
# No Haiku/mini models - they underperform for our use cases
PROVIDER_MODELS: Dict[str, str] = {
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4.1",           # Best non-reasoning, 1M context
    "mistral": "mistral-large-3",  # Dec 2025, open-weight, multimodal
}

# LiteLLM model prefixes
LITELLM_MODEL_PREFIXES: Dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "mistral": "mistral",
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
        "web_search": False,     # Anthropic-only feature
        "prompt_caching": False, # Anthropic-only feature
        "vision": True,
    },
    "mistral": {
        "tool_calling": True,
        "web_search": False,     # Anthropic-only feature
        "prompt_caching": False, # Anthropic-only feature
        "vision": True,          # mistral-large-3 is multimodal
    },
}

# API key environment variable names (for reference)
PROVIDER_API_KEY_NAMES: Dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
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
        "is_eu": provider == "mistral",
    }


def get_litellm_model(provider: str) -> str:
    """Get the full LiteLLM model string for a provider.

    Args:
        provider: Provider name (anthropic, openai, mistral)

    Returns:
        LiteLLM model string (e.g., "anthropic/claude-sonnet-4-20250514")
    """
    if provider not in PROVIDER_MODELS:
        raise ValueError(f"Unknown provider: {provider}")

    prefix = LITELLM_MODEL_PREFIXES[provider]
    model = PROVIDER_MODELS[provider]
    return f"{prefix}/{model}"


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
        lines.append(f"**Region:** 🇪🇺 European Union (GDPR compliant)")

    lines.append("")
    lines.append("**Features:**")

    for feature in ["tool_calling", "web_search", "prompt_caching", "vision"]:
        enabled = info["features"].get(feature, False)
        icon = "✅" if enabled else "❌"
        feature_name = feature.replace("_", " ").title()
        lines.append(f"  {icon} {feature_name}")

    if info["unavailable_features"]:
        lines.append("")
        lines.append("*Note: Web search and prompt caching are Anthropic-exclusive features.*")

    return "\n".join(lines)
