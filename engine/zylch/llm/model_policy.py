"""Saved provider and role policy; credentials never choose an explicit policy."""

import os
from pathlib import Path

from dotenv import dotenv_values

from . import role_pause
from .budget_pricing import BudgetError
from .roles import served, table

# One MODEL_<ROLE> profile key per role of the roster in roles/requirements.json.
ROLES = tuple("MODEL_" + role for role in table.roles())
BASE_KEYS = {
    "anthropic": "ANTHROPIC_MODEL",
    "mrcall": "MRCALL_CREDITS_MODEL",
    "openrouter": "OPENROUTER_MODEL",
}
PROXY_URL = "https://zylch.mrcall.ai"


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


def proxy_url(values):
    """The billing server a credits profile uses: MRCALL_PROXY_URL, else the default."""
    return str(values.get("MRCALL_PROXY_URL") or "").strip() or PROXY_URL


def resolve_model(role=None, model=None, *, values=None):
    """The model a call runs: an explicit model, else the saved MODEL_<ROLE>
    under every preset, else the role's pick in the table for `economy` /
    `balanced` on the saved provider. `custom` keeps the provider's base key
    (or DEFAULT_MODEL) and, with none saved, resolves the role under
    `economy`, so nobody is left model-less. No role means the base model,
    resolved as role CHAT.

    The pick reads the role's rankings in the table in force (`roles/table.py`):
    on OpenRouter its first ranked id; on a personal Anthropic key the first
    entry of its Anthropic ranking, and an empty one pauses that role with an
    explicit message; on MrCall credits the first ranked id the billing server
    serves (`roles/served.py`, its v2 capabilities read at most once an hour),
    and none served pauses the role, naming it. Nothing is guessed."""
    values = profile_values() if values is None else values
    provider = resolve_provider(values)
    if model and model.strip():
        return model.strip()
    return _resolve(role or "MODEL_CHAT", values, provider, online=True)


def _choice(role, values, provider):
    """The model saved for `role`, or None and the (preset, role) whose ranking decides."""
    if str(values.get(role) or "").strip():
        return str(values[role]).strip(), None
    preset = str(values.get("LLM_MODEL_PRESET") or "custom").strip()
    if preset not in ("economy", "balanced", "custom"):
        raise BudgetError("AI paused: select a supported model preset.")
    if preset == "custom":
        explicit = values.get(BASE_KEYS[provider]) or values.get("DEFAULT_MODEL")
        if explicit and str(explicit).strip():
            return str(explicit).strip(), None
        preset = "economy"
    return None, (preset, role.removeprefix("MODEL_"))


def _resolve(role, values, provider, *, online):
    """`role`'s model; on credits the served set is read when `online`, else
    only the cached one is used (no network)."""
    model, ranked = _choice(role, values, provider)
    if model:
        return model
    preset, name = ranked
    if provider == "mrcall":
        return served.pick(preset, name, proxy_url(values), online=online)
    return table.pick(preset, name, provider)


def policy_snapshot():
    values = profile_values()
    provider = resolve_provider(values)
    if provider == "mrcall":
        # One read of the served set (cached one hour) for every role below,
        # each then resolved from the cache; a failed read leaves them None.
        try:
            served.served(proxy_url(values))
        except BudgetError:
            pass
    return {
        "provider": provider,
        "preset": str(values.get("LLM_MODEL_PRESET") or "custom"),
        "model": _snapshot_model(None, values),
        "roles": {role: _snapshot_model(role, values) for role in ROLES},
        # A role read as None above because it pauses, and why (role_pause.py).
        "paused": role_pause.reasons(ROLES, values),
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
        return _resolve(role or "MODEL_CHAT", values, resolve_provider(values), online=False)
    except BudgetError:
        return None


def resolved_models(values):
    """``{MODEL_<ROLE>: model}`` as this profile resolves every role now, with no
    network (credits from the cached served set); None for a role that pauses."""
    try:
        provider = resolve_provider(values)
    except BudgetError:
        return {}
    models = {}
    for role in ROLES:
        try:
            models[role] = _resolve(role, values, provider, online=False)
        except (BudgetError, ValueError):
            models[role] = None
    return models


def _ranked_on_credits(values):
    """True when the profile is on credits and some role is decided by a ranking."""
    try:
        provider = resolve_provider(values)
        return provider == "mrcall" and any(_choice(r, values, provider)[1] for r in ROLES)
    except BudgetError:
        return False


def client_fingerprint(values):
    """The fingerprint a new client keeps. A credits profile whose roles a
    ranking decides reads the served set first (cached one hour), so the first
    read after the client is built does not change its fingerprint."""
    if _ranked_on_credits(values):
        served.served(proxy_url(values))
    return policy_fingerprint(values)


def policy_fingerprint(values=None):
    """In-memory digest only: refuse stale clients without storing credentials.

    It covers the saved policy keys and the model each role resolves to
    (`resolved_models`: no network, credits from the cached served set), not the
    table's version: a table refresh or a change of the served set that moves a
    model this profile runs reads as a settings change and aborts the runs in
    progress, a price refresh or a reorder that moves none of them does not
    (brief D9)."""
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
    selected["resolved"] = resolved_models(values)
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
