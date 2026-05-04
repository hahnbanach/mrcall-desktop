"""Compatibility shim for token_storage.

The SaaS ``zylch.api`` package was removed during the standalone
migration.  Many service modules still do lazy imports such as::

    from zylch.api.token_storage import get_provider

This module re-exports thin wrappers around
:class:`zylch.storage.storage.Storage` so those call-sites keep
working without edits.
"""

import logging
from typing import Any, Dict, Optional

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
#
# The `(provider, api_key)` resolution function used to live here. It
# is gone — the engine now picks transport (`direct` BYOK vs `proxy`
# credits) from the presence of `ANTHROPIC_API_KEY` and the Firebase
# session, both inside `zylch.llm.client.make_llm_client()`. Callers
# that used to do
#
#     provider, api_key = get_active_llm_provider(owner_id)
#     client = LLMClient(api_key, provider)
#
# now do
#
#     from zylch.llm import make_llm_client
#     client = make_llm_client()


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
