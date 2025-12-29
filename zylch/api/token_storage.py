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
# LLM Provider API Key Management
# Supports: Anthropic, OpenAI, Mistral
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


def save_llm_provider_key(owner_id: str, provider: str, api_key: str) -> bool:
    """Save API key for any LLM provider.

    Args:
        owner_id: Firebase UID
        provider: LLM provider (anthropic, openai, mistral)
        api_key: Provider's API key

    Returns:
        True if saved successfully
    """
    supabase = _get_supabase()
    return supabase.save_provider_credentials(
        owner_id=owner_id,
        provider_key=provider,
        credentials_dict={"api_key": api_key}
    )


def get_llm_provider_key(owner_id: str, provider: str) -> Optional[str]:
    """Get API key for a specific LLM provider.

    Args:
        owner_id: Firebase UID
        provider: LLM provider (anthropic, openai, mistral)

    Returns:
        API key or None if not found
    """
    supabase = _get_supabase()
    credentials = supabase.get_provider_credentials(owner_id, provider)
    if credentials:
        return credentials.get("api_key")
    return None


def get_active_llm_provider(owner_id: str) -> tuple[Optional[str], Optional[str]]:
    """Get the active LLM provider and API key for a user.

    Checks providers in order: Anthropic, OpenAI, Mistral.
    Returns the first configured provider.

    Args:
        owner_id: Firebase UID

    Returns:
        Tuple of (provider_name, api_key) or (None, None) if none configured
    """
    # Check providers in preferred order
    for provider in ["anthropic", "openai", "mistral"]:
        api_key = get_llm_provider_key(owner_id, provider)
        if api_key:
            return provider, api_key

    # Also check legacy Anthropic key storage for backward compatibility
    anthropic_key = get_anthropic_key(owner_id)
    if anthropic_key:
        return "anthropic", anthropic_key

    return None, None


def delete_llm_provider_key(owner_id: str, provider: str) -> bool:
    """Delete API key for an LLM provider.

    Args:
        owner_id: Firebase UID
        provider: LLM provider (anthropic, openai, mistral)

    Returns:
        True if deleted
    """
    supabase = _get_supabase()
    success = supabase.delete_provider_credentials(owner_id, provider)
    logger.info(f"Deleted {provider} API key for owner {owner_id}")
    return success


# ==========================================
# MrCall OAuth Token Management
# ==========================================

def save_mrcall_credentials(
    owner_id: str,
    access_token: str,
    refresh_token: Optional[str] = None,
    expires_in: int = 3600,
    token_type: str = "Bearer",
    business_id: Optional[str] = None,
    target_owner: Optional[str] = None,
    realm: str = "mrcall0"
) -> bool:
    """Save MrCall OAuth credentials for a user.

    Args:
        owner_id: Firebase UID
        access_token: OAuth access token
        refresh_token: OAuth refresh token
        expires_in: Token lifetime in seconds
        token_type: Token type (Bearer)
        business_id: MrCall business ID
        target_owner: StarChat Firebase UID for delegated access
        realm: StarChat realm

    Returns:
        True if saved successfully
    """
    from datetime import datetime, timedelta, timezone

    supabase = _get_supabase()

    # Calculate expiration timestamp
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # Build credentials dict
    credentials = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": token_type,
        "business_id": business_id,
        "target_owner": target_owner,
        "realm": realm
    }

    # Build metadata dict
    metadata = {
        "expires_at": expires_at.isoformat(),
        "scopes": ["business:read", "contacts:read"],
        "realm": realm
    }

    # Save to Supabase using provider credentials system
    return supabase.save_provider_credentials(
        owner_id=owner_id,
        provider_key="mrcall",
        credentials_dict=credentials,
        metadata_dict=metadata
    )


def get_mrcall_credentials(owner_id: str) -> Optional[Dict[str, Any]]:
    """Get MrCall OAuth credentials for a user.

    Args:
        owner_id: Firebase UID

    Returns:
        Dict with credentials or None if not found
    """
    supabase = _get_supabase()

    credentials = supabase.get_provider_credentials(
        owner_id=owner_id,
        provider_key="mrcall",
        include_metadata=True
    )

    return credentials


def delete_mrcall_credentials(owner_id: str) -> bool:
    """Delete MrCall OAuth credentials for a user.

    Args:
        owner_id: Firebase UID

    Returns:
        True if deleted
    """
    supabase = _get_supabase()
    success = supabase.delete_provider_credentials(owner_id, "mrcall")
    logger.info(f"Deleted MrCall credentials for owner {owner_id}")
    return success


async def refresh_mrcall_token(owner_id: str) -> Optional[Dict[str, Any]]:
    """Refresh MrCall OAuth access token.

    Args:
        owner_id: Firebase UID

    Returns:
        New credentials dict or None if refresh failed
    """
    import httpx
    from datetime import datetime, timedelta, timezone

    supabase = _get_supabase()
    credentials = get_mrcall_credentials(owner_id)

    if not credentials or not credentials.get("refresh_token"):
        logger.error(f"No refresh token for owner {owner_id}")
        return None

    # Make refresh request to StarChat
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.mrcall_base_url.rstrip('/')}/oauth/token/refresh",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": credentials["refresh_token"],
                    "client_id": settings.mrcall_client_id,
                    "client_secret": settings.mrcall_client_secret
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )

            if response.status_code != 200:
                logger.error(f"Token refresh failed: {response.status_code} - {response.text}")
                return None

            tokens = response.json()

            # Update credentials with new tokens
            save_mrcall_credentials(
                owner_id=owner_id,
                access_token=tokens["access_token"],
                refresh_token=tokens.get("refresh_token", credentials["refresh_token"]),
                expires_in=tokens.get("expires_in", 3600),
                token_type=tokens.get("token_type", "Bearer"),
                business_id=credentials.get("business_id"),
                target_owner=credentials.get("target_owner"),
                realm=credentials.get("realm", settings.mrcall_realm)
            )

            logger.info(f"Successfully refreshed MrCall token for owner {owner_id}")
            return get_mrcall_credentials(owner_id)

    except Exception as e:
        logger.error(f"Failed to refresh MrCall token: {e}")
        return None


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
    return supabase.save_provider_credentials(
        owner_id=owner_id,
        provider_key='vonage',
        credentials={
            'api_key': api_key,
            'api_secret': api_secret,
            'from_number': from_number
        }
    )


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
    result = supabase.delete_provider_credentials(owner_id, 'vonage')
    logger.info(f"Deleted Vonage API credentials for owner {owner_id}")
    return result
