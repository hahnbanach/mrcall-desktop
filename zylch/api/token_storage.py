"""Token storage utility for multi-tenant OAuth tokens.

All credentials stored in Supabase oauth_tokens table.
NO filesystem fallback - Supabase is required.
"""

import base64
import json
import logging
import pickle
from typing import Optional, Dict, Any, TYPE_CHECKING

from zylch.config import settings

# Avoid circular imports
if TYPE_CHECKING:
    from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)

# Shared Supabase storage instance
_supabase_storage: Optional['SupabaseStorage'] = None


def _get_supabase() -> 'SupabaseStorage':
    """Get Supabase storage instance.

    Returns:
        SupabaseStorage instance

    Raises:
        ValueError: If Supabase is not configured
    """
    global _supabase_storage

    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise ValueError(
            "Supabase not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY. "
            "Filesystem fallback has been removed - Supabase is required."
        )

    if _supabase_storage is None:
        from zylch.storage.supabase_client import SupabaseStorage
        _supabase_storage = SupabaseStorage()
        logger.info("Token storage using Supabase backend")

    return _supabase_storage


def save_provider(owner_id: str, provider: str, email: str = "") -> None:
    """Save auth provider for user.

    Args:
        owner_id: Firebase UID
        provider: 'google' or 'microsoft'
        email: User's email address (required for Supabase)
    """
    supabase = _get_supabase()
    supabase.store_oauth_token(owner_id, provider, email or "")
    logger.info(f"Saved provider '{provider}' for owner {owner_id}")


def get_provider(owner_id: str) -> Optional[str]:
    """Get auth provider for user.

    Args:
        owner_id: Firebase UID

    Returns:
        Provider string ('google' or 'microsoft') or None if not found
    """
    supabase = _get_supabase()
    return supabase.get_user_provider(owner_id)


def save_email(owner_id: str, email: str) -> None:
    """Save user email.

    Args:
        owner_id: Firebase UID
        email: User email address
    """
    supabase = _get_supabase()
    provider = get_provider(owner_id) or "unknown"
    supabase.store_oauth_token(owner_id, provider, email)
    logger.info(f"Saved email '{email}' for owner {owner_id}")


def get_email(owner_id: str) -> Optional[str]:
    """Get user email.

    Args:
        owner_id: Firebase UID

    Returns:
        Email string or None if not found
    """
    supabase = _get_supabase()
    return supabase.get_user_email_from_token(owner_id)


def save_graph_token(owner_id: str, access_token: str, expires_at: Optional[str] = None, refresh_token: Optional[str] = None) -> None:
    """Save Microsoft Graph API token.

    Args:
        owner_id: Firebase UID
        access_token: Microsoft Graph access token
        expires_at: ISO 8601 expiration timestamp (optional)
        refresh_token: Microsoft Graph refresh token (optional)
    """
    supabase = _get_supabase()
    email = get_email(owner_id) or ""
    supabase.store_oauth_token(
        owner_id=owner_id,
        provider="microsoft",
        email=email,
        graph_access_token=access_token,
        graph_refresh_token=refresh_token,
        graph_expires_at=expires_at
    )
    logger.info(f"Saved Microsoft Graph token for owner {owner_id}")


def get_graph_token(owner_id: str) -> Optional[Dict[str, Any]]:
    """Get Microsoft Graph API token.

    Args:
        owner_id: Firebase UID

    Returns:
        Dict with 'access_token', 'expires_at', 'refresh_token' or None if not found
    """
    supabase = _get_supabase()
    return supabase.get_graph_token(owner_id)


def delete_user_credentials(owner_id: str) -> None:
    """Delete all credentials for a user (logout).

    Args:
        owner_id: Firebase UID
    """
    supabase = _get_supabase()
    # Delete from Supabase for both providers
    supabase.delete_oauth_token(owner_id, "google")
    supabase.delete_oauth_token(owner_id, "microsoft")
    logger.info(f"Deleted OAuth tokens for owner {owner_id}")


def get_user_token_info(owner_id: str) -> Dict[str, Any]:
    """Get summary of user's token status.

    Args:
        owner_id: Firebase UID

    Returns:
        Dict with token status information
    """
    provider = get_provider(owner_id)
    email = get_email(owner_id)

    info = {
        "owner_id": owner_id,
        "provider": provider,
        "email": email,
        "has_graph_token": False,
        "has_google_tokens": False,
        "storage_backend": "supabase"
    }

    if provider == "microsoft":
        graph_token = get_graph_token(owner_id)
        info["has_graph_token"] = graph_token is not None
        if graph_token:
            info["graph_token_expires_at"] = graph_token.get("expires_at")

    if provider == "google":
        supabase = _get_supabase()
        google_token = supabase.get_google_token(owner_id)
        info["has_google_tokens"] = google_token is not None

    return info


def save_google_credentials(owner_id: str, credentials, email: str = "") -> None:
    """Save Google OAuth credentials.

    Args:
        owner_id: Firebase UID
        credentials: google.oauth2.credentials.Credentials object
        email: User's email address
    """
    logger.info(f"save_google_credentials called for owner {owner_id}, email={email}")

    supabase = _get_supabase()

    # Pickle and base64 encode credentials
    logger.info("Pickling credentials...")
    pickled = pickle.dumps(credentials)
    logger.info(f"Pickled data length: {len(pickled)}")

    logger.info("Base64 encoding...")
    token_data = base64.b64encode(pickled).decode('utf-8')
    logger.info(f"Token data length: {len(token_data)}")

    logger.info(f"Calling store_oauth_token for owner {owner_id}...")
    supabase.store_oauth_token(
        owner_id=owner_id,
        provider="google",
        email=email or get_email(owner_id) or "",
        google_token_data=token_data
    )
    logger.info(f"✅ Saved Google credentials for owner {owner_id}")


def get_google_credentials(owner_id: str):
    """Get Google OAuth credentials.

    Args:
        owner_id: Firebase UID

    Returns:
        google.oauth2.credentials.Credentials object or None if not found
    """
    supabase = _get_supabase()
    logger.info(f"Looking up Google credentials for owner {owner_id} in Supabase")
    token_data = supabase.get_google_token(owner_id)
    if token_data:
        logger.info(f"Found Google token data for owner {owner_id} (length: {len(token_data)})")
        try:
            pickled = base64.b64decode(token_data)
            credentials = pickle.loads(pickled)
            logger.info(f"Successfully loaded Google credentials for owner {owner_id}")
            return credentials
        except Exception as e:
            logger.error(f"Failed to unpickle Google credentials for owner {owner_id}: {e}")
            return None
    else:
        logger.warning(f"No Google token data found in Supabase for owner {owner_id}")
    return None


def has_google_credentials(owner_id: str) -> bool:
    """Check if user has Google OAuth credentials.

    Args:
        owner_id: Firebase UID

    Returns:
        True if credentials exist
    """
    supabase = _get_supabase()
    token_data = supabase.get_google_token(owner_id)
    return token_data is not None


# ==========================================
# Anthropic API Key Management
# ==========================================

def save_anthropic_key(owner_id: str, api_key: str) -> bool:
    """Save Anthropic API key for a user.

    Args:
        owner_id: Firebase UID
        api_key: Anthropic API key (sk-ant-...)

    Returns:
        True if saved successfully
    """
    supabase = _get_supabase()
    return supabase.save_anthropic_key(owner_id, api_key)


def get_anthropic_key(owner_id: str) -> Optional[str]:
    """Get Anthropic API key for a user.

    Args:
        owner_id: Firebase UID

    Returns:
        Anthropic API key or None if not found
    """
    supabase = _get_supabase()
    return supabase.get_anthropic_key(owner_id)


def delete_anthropic_key(owner_id: str) -> bool:
    """Delete Anthropic API key for a user.

    Args:
        owner_id: Firebase UID

    Returns:
        True if deleted
    """
    supabase = _get_supabase()
    supabase.delete_anthropic_key(owner_id)
    logger.info(f"Deleted Anthropic API key for owner {owner_id}")
    return True


# ==========================================
# Pipedrive API Key Management
# ==========================================

def save_pipedrive_key(owner_id: str, api_token: str) -> bool:
    """Save Pipedrive API token for a user.

    Args:
        owner_id: Firebase UID
        api_token: Pipedrive API token

    Returns:
        True if saved successfully
    """
    supabase = _get_supabase()
    return supabase.save_pipedrive_key(owner_id, api_token)


def get_pipedrive_key(owner_id: str) -> Optional[str]:
    """Get Pipedrive API token for a user.

    Args:
        owner_id: Firebase UID

    Returns:
        Pipedrive API token or None if not found
    """
    supabase = _get_supabase()
    return supabase.get_pipedrive_key(owner_id)


def delete_pipedrive_key(owner_id: str) -> bool:
    """Delete Pipedrive API token for a user.

    Args:
        owner_id: Firebase UID

    Returns:
        True if deleted
    """
    supabase = _get_supabase()
    supabase.delete_pipedrive_key(owner_id)
    logger.info(f"Deleted Pipedrive API token for owner {owner_id}")
    return True


# ==========================================
# Vonage API Key Management
# ==========================================

def save_vonage_keys(owner_id: str, api_key: str, api_secret: str, from_number: str) -> bool:
    """Save Vonage API credentials for a user.

    Args:
        owner_id: Firebase UID
        api_key: Vonage API key
        api_secret: Vonage API secret
        from_number: Vonage sender number

    Returns:
        True if saved successfully
    """
    supabase = _get_supabase()
    return supabase.save_vonage_keys(owner_id, api_key, api_secret, from_number)


def get_vonage_keys(owner_id: str) -> Optional[Dict[str, str]]:
    """Get Vonage API credentials for a user.

    Args:
        owner_id: Firebase UID

    Returns:
        Dict with api_key, api_secret, from_number or None if not found
    """
    supabase = _get_supabase()
    return supabase.get_vonage_keys(owner_id)


def delete_vonage_keys(owner_id: str) -> bool:
    """Delete Vonage API credentials for a user.

    Args:
        owner_id: Firebase UID

    Returns:
        True if deleted
    """
    supabase = _get_supabase()
    supabase.delete_vonage_keys(owner_id)
    logger.info(f"Deleted Vonage API credentials for owner {owner_id}")
    return True
