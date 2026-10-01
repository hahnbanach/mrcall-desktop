"""Saved provider and role policy; credentials never choose an explicit policy."""

import os
from pathlib import Path

from dotenv import dotenv_values

from .budget_pricing import BudgetError
from .roles import table

# One MODEL_<ROLE> profile key per role of the roster in roles/requirements.json.
ROLES = tuple("MODEL_" + role for role in table.roles())
BASE_KEYS = {
    "anthropic": "ANTHROPIC_MODEL",
    "mrcall": "MRCALL_CREDITS_MODEL",
    "openrouter": "OPENROUTER_MODEL",
}


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
    """The model a call runs: an explicit model, else the saved MODEL_<ROLE>
    under every preset, else the role's pick in the table for `economy` /
    `balanced` on the saved provider. `custom` keeps the provider's base key
    (or DEFAULT_MODEL) and, with none saved, resolves the role under
    `economy`, so nobody is left model-less. No role means the base model,
    resolved as role CHAT."""
    values = profile_values() if values is None else values
    provider = resolve_provider(values)
    if model and model.strip():
        return model.strip()
    role = role or "MODEL_CHAT"
    if str(values.get(role) or "").strip():
        return str(values[role]).strip()
    preset = str(values.get("LLM_MODEL_PRESET") or "custom").strip()
    if preset not in ("economy", "balanced", "custom"):
        raise BudgetError("AI paused: select a supported model preset.")
    if preset == "custom":
        explicit = values.get(BASE_KEYS[provider]) or values.get("DEFAULT_MODEL")
        if explicit and str(explicit).strip():
            return str(explicit).strip()
        preset = "economy"
    return table.pick(preset, role.removeprefix("MODEL_"), provider)


def policy_snapshot():
    values = profile_values()
    provider = resolve_provider(values)
    return {
        "provider": provider,
        "preset": str(values.get("LLM_MODEL_PRESET") or "custom"),
        "model": _snapshot_model(None, values),
        "roles": {role: _snapshot_model(role, values) for role in ROLES},
        "quality_status": (
            "OpenRouter memory/task quality has not been measured."
            if provider == "openrouter"
            else "No new task-quality benchmark performed."
        ),
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


def _snapshot_model(role, values):
    """A role the table cannot serve on this provider reads as None, not a crash."""
    try:
        return resolve_model(role, values=values)
    except BudgetError:
        return None


def policy_fingerprint(values=None):
    """In-memory digest only: refuse stale clients without storing credentials."""
    import hashlib
    import json

    values = profile_values() if values is None else values
    keys = (
        *ROLES,
        "LLM_PROVIDER",
        "LLM_MODEL_PRESET",
        *BASE_KEYS.values(),
        "DEFAULT_MODEL",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "MRCALL_PROXY_URL",
        "SMS_BUSINESS_ID",
        "VOICE_ENGINE_PROVIDER",
        "OPENAI_API_KEY",
        "OPENAI_PROJECT_ID",
    )
    selected = {key: values.get(key) for key in keys}
    return hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).digest()


def isolated_voice_unlimited(values=None, directory=None):
    """Explicit file-only operator override, restricted to the isolated voice profile."""
    values = profile_values() if values is None else values
    return values.get("VOICE_ENGINE_UNLIMITED") == "1" and isolated_voice_profile(values, directory)


def isolated_voice_profile(values=None, directory=None):
    """Validate the isolated profile markers without changing ordinary policy."""
    directory = directory or os.environ.get("ZYLCH_PROFILE_DIR")
    if not directory:
        return False
    values = profile_values() if values is None else values
    uid = Path(directory).name
    return (
        all(
            values.get(key) == uid
            for key in ("OWNER_ID", "VOICE_SMOKE_TEST_PROFILE", "VOICE_ENGINE_ISOLATED_PROFILE")
        )
        and not (Path(directory) / "zylch.db").exists()
    )
