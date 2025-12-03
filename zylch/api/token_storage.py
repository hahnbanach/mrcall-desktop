"""Token storage utility for multi-tenant OAuth tokens.

Stores tokens in filesystem organized by owner_id:
    credentials/{owner_id}/
        ├── provider.txt           # 'google.com' or 'microsoft.com'
        ├── email.txt              # User email
        ├── graph_token.json       # Microsoft Graph token (if microsoft)
        └── google_tokens/         # Google OAuth tokens (if google)

Future: migrate to StarChat zylch_oauth_tokens table with encryption.
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Base credentials directory
CREDENTIALS_BASE = Path.home() / "zylch" / "credentials"


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


def save_provider(owner_id: str, provider: str) -> None:
    """Save auth provider for user.

    Args:
        owner_id: Firebase UID
        provider: 'google.com' or 'microsoft.com'
    """
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
    user_dir = get_user_credentials_dir(owner_id)
    email_file = user_dir / "email.txt"

    if email_file.exists():
        return email_file.read_text().strip()
    return None


def save_graph_token(owner_id: str, access_token: str, expires_at: Optional[str] = None) -> None:
    """Save Microsoft Graph API token.

    Args:
        owner_id: Firebase UID
        access_token: Microsoft Graph access token
        expires_at: ISO 8601 expiration timestamp (optional)
    """
    user_dir = get_user_credentials_dir(owner_id)
    token_file = user_dir / "graph_token.json"

    token_data = {
        "access_token": access_token,
        "expires_at": expires_at or (datetime.now(timezone.utc).isoformat()),
        "saved_at": datetime.now(timezone.utc).isoformat()
    }

    token_file.write_text(json.dumps(token_data, indent=2))
    logger.info(f"Saved Microsoft Graph token for owner {owner_id}")


def get_graph_token(owner_id: str) -> Optional[Dict[str, Any]]:
    """Get Microsoft Graph API token.

    Args:
        owner_id: Firebase UID

    Returns:
        Dict with 'access_token', 'expires_at', 'saved_at' or None if not found
    """
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
        "has_google_tokens": False
    }

    if provider == "microsoft.com":
        graph_token = get_graph_token(owner_id)
        info["has_graph_token"] = graph_token is not None
        if graph_token:
            info["graph_token_expires_at"] = graph_token.get("expires_at")

    if provider == "google.com":
        google_dir = get_google_tokens_dir(owner_id)
        # Check if any .pickle files exist
        pickle_files = list(google_dir.glob("*.pickle"))
        info["has_google_tokens"] = len(pickle_files) > 0
        info["google_token_count"] = len(pickle_files)

    return info
