"""Provider configuration and feature flags for LLM providers."""

from typing import Dict, Any

from zylch.config import settings

# One model per provider — configured via env vars
PROVIDER_MODELS: Dict[str, str] = {
    "anthropic": settings.anthropic_model,
    "openai": settings.openai_model,
    # "mrcall" routes through mrcall-agent's proxy and bills the user's
    # MrCall credit balance instead of using a BYOK Anthropic key. The
    # underlying model is still a Claude model — pinned via
    # `mrcall_credits_model` so we control which model we charge for
    # without depending on whatever the user's Anthropic env happens to
    # have configured.
    "mrcall": settings.mrcall_credits_model,
}

# Feature availability per provider.
#
# `is_metered`: True when the provider charges against the user's MrCall
# credit balance (bookkeeping happens server-side). Callers can branch
# on this to surface "Out of credits" UX or to skip features that don't
# make sense in metered mode (e.g. local-only fallback).
PROVIDER_FEATURES: Dict[str, Dict[str, bool]] = {
    "anthropic": {
        "tool_calling": True,
        "web_search": True,  # Built-in web_search_20250305 tool
        "prompt_caching": True,  # cache_control: {"type": "ephemeral"}
        "vision": True,
        "is_metered": False,
    },
    "openai": {
        "tool_calling": True,
        "web_search": True,  # Via Responses API (web_search_preview tool)
        "prompt_caching": False,  # Anthropic-only feature
        "vision": True,
        "is_metered": False,
    },
    "mrcall": {
        # Same capability surface as anthropic — the proxy is a
        # pass-through to Anthropic server-side; cache headers /
        # web_search tool defs are forwarded verbatim.
        "tool_calling": True,
        "web_search": True,
        "prompt_caching": True,
        "vision": True,
        "is_metered": True,
    },
}

# API key environment variable names (for reference). "mrcall" is
# omitted: the credentials in that mode are the Firebase ID token held
# in `zylch.auth.session`, not an env var.
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
    """Get the model name for a provider.

    Args:
        provider: Provider name (anthropic, openai)

    Returns:
        Model string (e.g., "claude-opus-4-6")
    """
    if provider not in PROVIDER_MODELS:
        raise ValueError(f"Unknown provider: {provider}")
    return PROVIDER_MODELS[provider]


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
        "",
        f"**Model:** `{info['model']}`",
    ]

    if info["is_eu"]:
        lines.append("**Region:** EU (GDPR compliant)")

    lines.append("")
    lines.append("**Features:**")

    for feature in ["tool_calling", "web_search", "prompt_caching", "vision"]:
        enabled = info["features"].get(feature, False)
        icon = "Y" if enabled else "N"
        feature_name = feature.replace("_", " ").title()
        lines.append(f"  [{icon}] {feature_name}")

    if info["unavailable_features"]:
        lines.append("")
        lines.append(
            "*Note: Prompt caching is Anthropic-exclusive. Web search is available with Anthropic and OpenAI.*"
        )

    return "\n".join(lines)


def get_system_llm_credentials(
    fallback_provider: str = "",
    fallback_api_key: str = "",
) -> tuple[str, str]:
    """Get system-level LLM credentials (for when user has no BYOK key).

    Mirrors :func:`zylch.api.token_storage.get_active_llm_provider`:
    explicit `SYSTEM_LLM_PROVIDER=mrcall` wins; otherwise the presence
    of a BYOK key decides; no key → MrCall credits with the Firebase
    JWT as credential. The sentinel constant is imported lazily to
    avoid a circular import.

    Returns:
        (provider, api_key) tuple
    """
    from zylch.api.token_storage import MRCALL_SESSION_SENTINEL

    explicit = (settings.system_llm_provider or "").strip().lower()

    if explicit == "mrcall":
        return "mrcall", MRCALL_SESSION_SENTINEL
    if explicit == "anthropic" and settings.anthropic_api_key:
        return "anthropic", settings.anthropic_api_key
    if explicit == "openai" and settings.openai_api_key:
        return "openai", settings.openai_api_key

    if settings.anthropic_api_key:
        return "anthropic", settings.anthropic_api_key
    if settings.openai_api_key:
        return "openai", settings.openai_api_key

    if fallback_provider or fallback_api_key:
        return fallback_provider, fallback_api_key
    return "mrcall", MRCALL_SESSION_SENTINEL
