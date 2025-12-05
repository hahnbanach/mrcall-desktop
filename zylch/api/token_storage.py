"""Token storage utility for multi-tenant OAuth tokens.

Supports two backends:
1. Supabase (production) - stores tokens in oauth_tokens table
2. Filesystem (local dev) - stores in credentials/{owner_id}/

The backend is automatically selected based on SUPABASE_URL configuration.
"""

import base64
import json
import logging
import pickle
from pathlib import Path
from typing import Optional, Dict, Any, TYPE_CHECKING
from datetime import datetime, timezone

from zylch.config import settings

# Avoid circular imports
if TYPE_CHECKING:
    from zylch.storage.supabase_client import SupabaseStorage

logger = logging.getLogger(__name__)

# Base credentials directory (for filesystem fallback)
CREDENTIALS_BASE = Path.home() / "zylch" / "credentials"

# Shared Supabase storage instance
_supabase_storage: Optional['SupabaseStorage'] = None


def _get_supabase() -> Optional['SupabaseStorage']:
    """Get Supabase storage instance if configured.

    Returns:
        SupabaseStorage instance or None if not configured
    """
    global _supabase_storage

    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None

    if _supabase_storage is None:
        try:
            from zylch.storage.supabase_client import SupabaseStorage
            _supabase_storage = SupabaseStorage()
            logger.info("Token storage using Supabase backend")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase for token storage: {e}")
            return None

    return _supabase_storage


def _use_supabase() -> bool:
    """Check if Supabase backend should be used."""
    return _get_supabase() is not None


def get_user_credentials_dir(owner_id: str) -> Path:
    """Get credentials directory for a specific owner.

    Args:
        owner_id: Firebase UID / owner_id

    Returns:
        Path to user's credentials directory
    """
    user_dir = CREDENTIALS_BASE / owner_id
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def save_provider(owner_id: str, provider: str, email: str = "") -> None:
    """Save auth provider for user.

    Args:
        owner_id: Firebase UID
        provider: 'google.com' or 'microsoft.com'
        email: User's email address (required for Supabase)
    """
    supabase = _get_supabase()
    if supabase:
        # Supabase stores provider as part of oauth_tokens record
        # Just ensure a record exists with the provider
        supabase.store_oauth_token(owner_id, provider, email or "")
        logger.info(f"Saved provider '{provider}' for owner {owner_id} (Supabase)")
        return

    # Filesystem fallback
    user_dir = get_user_credentials_dir(owner_id)
    provider_file = user_dir / "provider.txt"
    provider_file.write_text(provider)
    logger.info(f"Saved provider '{provider}' for owner {owner_id}")


def get_provider(owner_id: str) -> Optional[str]:
    """Get auth provider for user.

    Args:
        owner_id: Firebase UID

    Returns:
        Provider string or None if not found
    """
    supabase = _get_supabase()
    if supabase:
        provider = supabase.get_user_provider(owner_id)
        if provider:
            return provider

    # Filesystem fallback
    user_dir = get_user_credentials_dir(owner_id)
    provider_file = user_dir / "provider.txt"

    if provider_file.exists():
        return provider_file.read_text().strip()
    return None


def save_email(owner_id: str, email: str) -> None:
    """Save user email.

    Args:
        owner_id: Firebase UID
        email: User email address
    """
    supabase = _get_supabase()
    if supabase:
        # Email is stored as part of oauth_tokens, get existing provider
        provider = get_provider(owner_id) or "unknown"
        supabase.store_oauth_token(owner_id, provider, email)
        logger.info(f"Saved email '{email}' for owner {owner_id} (Supabase)")
        return

    # Filesystem fallback
    user_dir = get_user_credentials_dir(owner_id)
    email_file = user_dir / "email.txt"
    email_file.write_text(email)
    logger.info(f"Saved email '{email}' for owner {owner_id}")


def get_email(owner_id: str) -> Optional[str]:
    """Get user email.

    Args:
        owner_id: Firebase UID

    Returns:
        Email string or None if not found
    """
    supabase = _get_supabase()
    if supabase:
        email = supabase.get_user_email_from_token(owner_id)
        if email:
            return email

    # Filesystem fallback
    user_dir = get_user_credentials_dir(owner_id)
    email_file = user_dir / "email.txt"

    if email_file.exists():
        return email_file.read_text().strip()
    return None


def save_graph_token(owner_id: str, access_token: str, expires_at: Optional[str] = None, refresh_token: Optional[str] = None) -> None:
    """Save Microsoft Graph API token.

    Args:
        owner_id: Firebase UID
        access_token: Microsoft Graph access token
        expires_at: ISO 8601 expiration timestamp (optional)
        refresh_token: Microsoft Graph refresh token (optional)
    """
    supabase = _get_supabase()
    if supabase:
        email = get_email(owner_id) or ""
        supabase.store_oauth_token(
            owner_id=owner_id,
            provider="microsoft.com",
            email=email,
            graph_access_token=access_token,
            graph_refresh_token=refresh_token,
            graph_expires_at=expires_at
        )
        logger.info(f"Saved Microsoft Graph token for owner {owner_id} (Supabase)")
        return

    # Filesystem fallback
    user_dir = get_user_credentials_dir(owner_id)
    token_file = user_dir / "graph_token.json"

    token_data = {
        "access_token": access_token,
        "expires_at": expires_at or (datetime.now(timezone.utc).isoformat()),
        "refresh_token": refresh_token,
        "saved_at": datetime.now(timezone.utc).isoformat()
    }

    token_file.write_text(json.dumps(token_data, indent=2))
    logger.info(f"Saved Microsoft Graph token for owner {owner_id}")


def get_graph_token(owner_id: str) -> Optional[Dict[str, Any]]:
    """Get Microsoft Graph API token.

    Args:
        owner_id: Firebase UID

    Returns:
        Dict with 'access_token', 'expires_at', 'refresh_token' or None if not found
    """
    supabase = _get_supabase()
    if supabase:
        token_data = supabase.get_graph_token(owner_id)
        if token_data:
            return token_data

    # Filesystem fallback
    user_dir = get_user_credentials_dir(owner_id)
    token_file = user_dir / "graph_token.json"

    if token_file.exists():
        try:
            return json.loads(token_file.read_text())
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse graph token for owner {owner_id}: {e}")
            return None

    return None


def get_google_tokens_dir(owner_id: str) -> Path:
    """Get Google tokens directory for user.

    Args:
        owner_id: Firebase UID

    Returns:
        Path to google_tokens directory
    """
    user_dir = get_user_credentials_dir(owner_id)
    google_dir = user_dir / "google_tokens"
    google_dir.mkdir(parents=True, exist_ok=True)
    return google_dir


def delete_user_credentials(owner_id: str) -> None:
    """Delete all credentials for a user (logout).

    Args:
        owner_id: Firebase UID
    """
    supabase = _get_supabase()
    if supabase:
        # Delete from Supabase for both providers
        supabase.delete_oauth_token(owner_id, "google.com")
        supabase.delete_oauth_token(owner_id, "microsoft.com")
        logger.info(f"Deleted OAuth tokens for owner {owner_id} (Supabase)")

    # Also clean up filesystem (for local dev or migration)
    user_dir = get_user_credentials_dir(owner_id)
    if user_dir.exists():
        import shutil
        shutil.rmtree(user_dir)
        logger.info(f"Deleted all credentials for owner {owner_id}")


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
        "storage_backend": "supabase" if _use_supabase() else "filesystem"
    }

    if provider == "microsoft.com":
        graph_token = get_graph_token(owner_id)
        info["has_graph_token"] = graph_token is not None
        if graph_token:
            info["graph_token_expires_at"] = graph_token.get("expires_at")

    if provider == "google.com":
        # Check Supabase first
        supabase = _get_supabase()
        if supabase:
            google_token = supabase.get_google_token(owner_id)
            info["has_google_tokens"] = google_token is not None
        else:
            # Filesystem fallback
            google_dir = get_google_tokens_dir(owner_id)
            pickle_files = list(google_dir.glob("*.pickle"))
            info["has_google_tokens"] = len(pickle_files) > 0
            info["google_token_count"] = len(pickle_files)

    return info


def save_google_credentials(owner_id: str, credentials, email: str = "") -> None:
    """Save Google OAuth credentials.

    Args:
        owner_id: Firebase UID
        credentials: google.oauth2.credentials.Credentials object
        email: User's email address
    """
    supabase = _get_supabase()
    if supabase:
        # Pickle and base64 encode credentials
        pickled = pickle.dumps(credentials)
        token_data = base64.b64encode(pickled).decode('utf-8')
        supabase.store_oauth_token(
            owner_id=owner_id,
            provider="google.com",
            email=email or get_email(owner_id) or "",
            google_token_data=token_data
        )
        logger.info(f"Saved Google credentials for owner {owner_id} (Supabase)")
        return

    # Filesystem fallback - save to token.pickle in google_tokens dir
    google_dir = get_google_tokens_dir(owner_id)
    token_file = google_dir / "token.pickle"
    with open(token_file, 'wb') as f:
        pickle.dump(credentials, f)
    logger.info(f"Saved Google credentials for owner {owner_id}")


def get_google_credentials(owner_id: str):
    """Get Google OAuth credentials.

    Args:
        owner_id: Firebase UID

    Returns:
        google.oauth2.credentials.Credentials object or None if not found
    """
    supabase = _get_supabase()
    if supabase:
        token_data = supabase.get_google_token(owner_id)
        if token_data:
            try:
                pickled = base64.b64decode(token_data)
                credentials = pickle.loads(pickled)
                return credentials
            except Exception as e:
                logger.error(f"Failed to unpickle Google credentials for owner {owner_id}: {e}")
                return None

    # Filesystem fallback
    google_dir = get_google_tokens_dir(owner_id)
    token_file = google_dir / "token.pickle"

    if token_file.exists():
        try:
            with open(token_file, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            logger.error(f"Failed to load Google credentials for owner {owner_id}: {e}")
            return None

    return None


def has_google_credentials(owner_id: str) -> bool:
    """Check if user has Google OAuth credentials.

    Args:
        owner_id: Firebase UID

    Returns:
        True if credentials exist
    """
    supabase = _get_supabase()
    if supabase:
        token_data = supabase.get_google_token(owner_id)
        return token_data is not None

    # Filesystem fallback
    google_dir = get_google_tokens_dir(owner_id)
    token_file = google_dir / "token.pickle"
    return token_file.exists()
