"""Compatibility shim for token_storage.

The SaaS ``zylch.api`` package was removed during the standalone
migration.  Many service modules still do lazy imports such as::

    from zylch.api.token_storage import get_provider

This module re-exports thin wrappers around
:class:`zylch.storage.storage.Storage` so those call-sites keep
working without edits.
"""

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _storage():
    """Return the global Storage singleton (lazy)."""
    from zylch.storage.storage import Storage

    return Storage.get_instance()


def _owner():
    """Return the configured owner_id."""
    from zylch.config import settings

    return settings.owner_id


# ------------------------------------------------------------------
# Provider / email helpers
# ------------------------------------------------------------------


def get_provider(owner_id: str) -> Optional[str]:
    """Return email provider: 'imap' from .env, or 'google'/'microsoft' from OAuth tokens."""
    from zylch.config import settings

    if settings.email_address and settings.email_password:
        return "imap"
    return _storage().get_user_provider(owner_id)


def get_email(owner_id: str) -> Optional[str]:
    """Return the user's email from .env or stored OAuth tokens."""
    from zylch.config import settings

    if settings.email_address:
        return settings.email_address
    return _storage().get_user_email_from_token(owner_id)


def get_graph_token(
    owner_id: str,
) -> Optional[Dict[str, Any]]:
    """Return Microsoft Graph token dict."""
    return _storage().get_graph_token(owner_id)


# ------------------------------------------------------------------
# LLM provider
# ------------------------------------------------------------------


# Sentinel returned in place of an API key when the resolved provider is
# MrCall credits. The credential in that mode is the in-memory Firebase
# JWT held by `zylch.auth.session` — `LLMClient.__init__("mrcall")` pulls
# it from there and ignores the `api_key` argument. The sentinel exists
# only to satisfy the many `if not api_key:` gates scattered across the
# engine which otherwise treat an empty key as "LLM not configured".
MRCALL_SESSION_SENTINEL = "firebase-session"


def get_active_llm_provider(
    owner_id: str,
) -> Tuple[str, str]:
    """Return (provider, api_key) for the active LLM.

    Resolution policy:
    1. Explicit `SYSTEM_LLM_PROVIDER=mrcall` always wins → MrCall credits.
    2. Otherwise the presence of a BYOK key decides — `ANTHROPIC_API_KEY`
       beats `OPENAI_API_KEY` if both happen to be set.
    3. No key set anywhere → MrCall credits (the Firebase JWT cached in
       `zylch.auth.session` is the credential).

    The default `SYSTEM_LLM_PROVIDER=anthropic` (from pydantic) is treated
    as "no explicit choice" when no Anthropic key is present, so a fresh
    profile without keys flows to credits without the user editing the
    setting.
    """
    from zylch.config import settings

    explicit = (settings.system_llm_provider or "").strip().lower()

    if explicit == "mrcall":
        return ("mrcall", MRCALL_SESSION_SENTINEL)
    if explicit == "anthropic" and settings.anthropic_api_key:
        return ("anthropic", settings.anthropic_api_key)
    if explicit == "openai" and settings.openai_api_key:
        return ("openai", settings.openai_api_key)

    # Explicit choice didn't match (or key missing) → infer from .env.
    if settings.anthropic_api_key:
        return ("anthropic", settings.anthropic_api_key)
    if settings.openai_api_key:
        return ("openai", settings.openai_api_key)

    # No BYOK key available → fall back to MrCall credits.
    return ("mrcall", MRCALL_SESSION_SENTINEL)


# ------------------------------------------------------------------
# MrCall credentials
# ------------------------------------------------------------------


def get_mrcall_credentials(
    owner_id: str,
) -> Optional[Dict[str, Any]]:
    """Return MrCall/StarChat OAuth credentials."""
    return _storage().get_provider_credentials(owner_id, "mrcall")


def refresh_mrcall_token(
    owner_id: str,
) -> Optional[Dict[str, Any]]:
    """Placeholder — token refresh not supported standalone."""
    logger.warning("refresh_mrcall_token called but not" " implemented in standalone mode")
    return get_mrcall_credentials(owner_id)


# ------------------------------------------------------------------
# Vonage
# ------------------------------------------------------------------


def get_vonage_keys(
    owner_id: str,
) -> Optional[Dict[str, str]]:
    """Return Vonage API credentials."""
    return _storage().get_provider_credentials(owner_id, "vonage")


# ------------------------------------------------------------------
# Delete helpers (used by /disconnect)
# ------------------------------------------------------------------


def delete_user_credentials(owner_id: str) -> bool:
    """Delete Google + Microsoft OAuth tokens."""
    s = _storage()
    s.delete_oauth_token(owner_id, "google")
    s.delete_oauth_token(owner_id, "microsoft")
    return True


def delete_mrcall_credentials(owner_id: str) -> bool:
    """Delete MrCall credentials."""
    return _storage().delete_provider_credentials(owner_id, "mrcall")


def delete_anthropic_key(owner_id: str) -> bool:
    """Delete Anthropic API key."""
    return _storage().delete_anthropic_key(owner_id)


def delete_pipedrive_key(owner_id: str) -> bool:
    """Delete Pipedrive API token."""
    return _storage().delete_provider_credentials(owner_id, "pipedrive")


def delete_vonage_keys(owner_id: str) -> bool:
    """Delete Vonage API credentials."""
    return _storage().delete_provider_credentials(owner_id, "vonage")


def delete_sendgrid_key(owner_id: str) -> bool:
    """Delete SendGrid API key."""
    return _storage().delete_provider_credentials(owner_id, "sendgrid")


def delete_llm_provider_key(
    owner_id: str,
    provider: str = "",
) -> bool:
    """Delete an LLM provider key."""
    if not provider:
        provider = "anthropic"
    return _storage().delete_provider_credentials(owner_id, provider)
