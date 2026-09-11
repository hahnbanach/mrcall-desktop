"""Saved provider and role policy; credentials never choose an explicit policy."""

import os
from pathlib import Path

from dotenv import dotenv_values

from .budget_pricing import BudgetError

ROLES = (
    "MODEL_MEMORY_EXTRACT",
    "MODEL_MEMORY_MERGE",
    "MODEL_TASK_DETECTION",
    "MODEL_REANALYZE",
    "MODEL_DEDUP",
)


def profile_values():
    directory = os.environ.get("ZYLCH_PROFILE_DIR")
    if not directory:
        return dict(os.environ)
    try:
        path = Path(directory) / ".env"
        text = path.read_text(encoding="utf-8")
        from io import StringIO

        from dotenv.parser import parse_stream

        if any(binding.error for binding in parse_stream(StringIO(text))):
            raise ValueError
        return dict(dotenv_values(stream=StringIO(text), interpolate=False))
    except (OSError, UnicodeError, ValueError):
        raise BudgetError(
            "AI paused: saved provider settings are unavailable or malformed."
        ) from None


def profile_value(key):
    return str(profile_values().get(key) or "").strip()


def resolve_provider(values=None):
    values = profile_values() if values is None else values
    explicit = str(values.get("LLM_PROVIDER") or "").strip()
    if explicit:
        if explicit not in ("anthropic", "mrcall", "openrouter"):
            raise BudgetError("AI paused: select a supported LLM provider.")
        return explicit
    # Legacy profiles retain their existing billing path; ambient shell keys
    # never override an active profile's explicit or legacy credentials.
    return "anthropic" if str(values.get("ANTHROPIC_API_KEY") or "").strip() else "mrcall"


def resolve_model(role=None, model=None, *, values=None):
    values = profile_values() if values is None else values
    provider = resolve_provider(values)
    if model and model.strip():
        return model.strip()
    if role and str(values.get(role) or "").strip():
        return str(values[role]).strip()
    preset = str(values.get("LLM_MODEL_PRESET") or "custom").strip()
    if preset not in ("economy", "balanced", "custom"):
        raise BudgetError("AI paused: select a supported model preset.")
    if preset == "custom":
        key = {
            "anthropic": "ANTHROPIC_MODEL",
            "mrcall": "MRCALL_CREDITS_MODEL",
            "openrouter": "OPENROUTER_MODEL",
        }[provider]
        explicit = values.get(key) or values.get("DEFAULT_MODEL")
        if explicit and str(explicit).strip():
            return str(explicit).strip()
    if provider == "openrouter":
        return "z-ai/glm-5.2"
    return "claude-sonnet-5" if preset == "balanced" else "claude-haiku-4-5"


def policy_snapshot():
    values = profile_values()
    provider = resolve_provider(values)
    return {
        "provider": provider,
        "preset": str(values.get("LLM_MODEL_PRESET") or "custom"),
        "model": resolve_model(values=values),
        "roles": {role: resolve_model(role, values=values) for role in ROLES},
        "quality_status": "OpenRouter memory/task quality has not been measured."
        if provider == "openrouter"
        else "No new task-quality benchmark performed.",
        "credential_configured": provider == "mrcall"
        or bool(
            str(
                values.get(
                    "OPENROUTER_API_KEY" if provider == "openrouter" else "ANTHROPIC_API_KEY"
                )
                or ""
            ).strip()
        ),
    }


def policy_fingerprint(values=None):
    """In-memory digest only: refuse stale clients without storing credentials."""
    import hashlib
    import json
    values = profile_values() if values is None else values
    keys = (*ROLES, "LLM_PROVIDER", "LLM_MODEL_PRESET", "ANTHROPIC_MODEL",
            "MRCALL_CREDITS_MODEL", "OPENROUTER_MODEL", "DEFAULT_MODEL",
            "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "MRCALL_PROXY_URL")
    selected = {key: values.get(key) for key in keys}
    return hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).digest()
