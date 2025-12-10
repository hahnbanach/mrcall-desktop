"""
Integration Provider Registry

Centralized registry for all external service integrations.
Provides helper functions to query available providers and user connection status.
"""

import logging
from typing import List, Dict, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# Provider categories
PROVIDER_CATEGORIES = {
    'email': 'Email & Calendar',
    'crm': 'CRM & Sales',
    'messaging': 'Messaging',
    'telephony': 'Phone & SMS',
    'video': 'Video Conferencing',
    'ai': 'AI Services'
}


def get_available_providers(
    supabase_client,
    category: Optional[str] = None,
    include_unavailable: bool = False
) -> List[Dict[str, Any]]:
    """
    Get list of available integration providers from database.

    Args:
        supabase_client: Supabase storage client
        category: Filter by category (email, crm, messaging, etc.)
        include_unavailable: If False, only show is_available=true providers

    Returns:
        List of provider dictionaries with metadata
    """
    try:
        query = supabase_client.client.table('integration_providers').select('*')

        if category:
            query = query.eq('category', category)

        if not include_unavailable:
            query = query.eq('is_available', True)

        result = query.order('display_name').execute()

        return result.data if result.data else []

    except Exception as e:
        logger.error(f"Failed to get available providers: {e}")
        return []


def get_user_connections(supabase_client, owner_id: str) -> List[Dict[str, Any]]:
    """
    Get user's active connections from oauth_tokens table.

    Only returns connections where actual credential data exists (not just empty rows).
    Uses unified credentials JSONB column with fallback to legacy columns.

    Args:
        supabase_client: Supabase storage client
        owner_id: User's Firebase UID

    Returns:
        List of connected provider dictionaries with status
    """
    try:
        # Fetch oauth_tokens rows with unified credentials
        result = supabase_client.client.table('oauth_tokens')\
            .select('provider, email, connection_status, last_sync, error_message, display_name, created_at, '
                   'credentials')\
            .eq('owner_id', owner_id)\
            .execute()

        logger.info(f"get_user_connections for owner {owner_id}: found {len(result.data) if result.data else 0} rows")

        if result.data:
            logger.info(f"All providers found in oauth_tokens: {[r.get('provider') for r in result.data]}")

        if not result.data:
            return []

        # Filter out connections that don't have actual credential data
        valid_connections = []
        for conn in result.data:
            provider = conn['provider']
            has_credentials = False

            logger.info(f"Checking connection for provider {provider}")
            creds_value = conn.get('credentials')
            logger.info(f"  credentials field present: {creds_value is not None}")
            if creds_value:
                logger.info(f"  credentials length: {len(creds_value)}")
            else:
                logger.info(f"  credentials is None/empty")

            # Check unified credentials JSONB
            if conn.get('credentials'):
                try:
                    from zylch.utils.encryption import decrypt
                    import json

                    logger.info(f"  Decrypting credentials...")
                    decrypted_json = decrypt(conn['credentials'])
                    logger.info(f"  Decrypted length: {len(decrypted_json)}")
                    logger.info(f"  Parsing JSON...")
                    all_creds = json.loads(decrypted_json)
                    logger.info(f"  Parsed creds keys: {list(all_creds.keys())}")

                    # Check if provider exists in credentials
                    has_credentials = bool(all_creds.get(provider))
                    logger.info(f"  Provider {provider} in creds: {has_credentials}")
                except Exception as e:
                    logger.error(f"Failed to decrypt credentials for {provider}: {e}", exc_info=True)
                    has_credentials = False

            if has_credentials:
                logger.info(f"  ✅ Provider {provider} has valid credentials")
                # Remove credential fields from response (security)
                conn.pop('credentials', None)
                valid_connections.append(conn)
            else:
                logger.info(f"  ❌ Provider {provider} has no valid credentials")

        return valid_connections

    except Exception as e:
        logger.error(f"Failed to get user connections for {owner_id}: {e}")
        return []


def get_connection_status(
    supabase_client,
    owner_id: str,
    include_unavailable: bool = False
) -> Dict[str, Any]:
    """
    Get comprehensive connection status for a user.

    Combines available providers with user's current connections.

    Args:
        supabase_client: Supabase storage client
        owner_id: User's Firebase UID
        include_unavailable: Include "coming soon" providers

    Returns:
        Dict with 'connections' list containing status for each provider
    """
    try:
        # Get all available providers
        available = get_available_providers(
            supabase_client,
            include_unavailable=include_unavailable
        )

        # Get user's current connections
        user_connections = get_user_connections(supabase_client, owner_id)

        # Create lookup dict for user connections
        connected_lookup = {
            conn['provider']: conn
            for conn in user_connections
        }

        logger.info(f"Connected lookup keys: {list(connected_lookup.keys())}")

        # Combine data
        connections = []
        for provider in available:
            provider_key = provider['provider_key']
            logger.info(f"Checking provider_key: {provider_key}")

            # Check if user has this connection
            user_conn = connected_lookup.get(provider_key)
            logger.info(f"  Found user_conn: {user_conn is not None}")

            connection_data = {
                'provider_key': provider_key,
                'display_name': provider['display_name'],
                'category': provider['category'],
                'description': provider.get('description'),
                'icon_url': provider.get('icon_url'),
                'requires_oauth': provider['requires_oauth'],
                'oauth_url': provider.get('oauth_url'),
                'config_fields': provider.get('config_fields'),
                'is_available': provider['is_available'],
                'documentation_url': provider.get('documentation_url')
            }

            if user_conn:
                # User has this connection
                connection_data.update({
                    'status': user_conn.get('connection_status', 'connected'),
                    'connected_email': user_conn.get('email'),
                    'last_sync': user_conn.get('last_sync'),
                    'error_message': user_conn.get('error_message'),
                    'connected_at': user_conn.get('created_at')
                })
            else:
                # User doesn't have this connection
                if provider['is_available']:
                    connection_data['status'] = 'disconnected'
                else:
                    connection_data['status'] = 'coming_soon'

            connections.append(connection_data)

        return {
            'connections': connections,
            'total': len(connections),
            'connected_count': sum(1 for c in connections if c.get('status') == 'connected'),
            'available_count': sum(1 for c in connections if c['is_available'] and c.get('status') == 'disconnected')
        }

    except Exception as e:
        logger.error(f"Failed to get connection status for {owner_id}: {e}")
        return {'connections': [], 'total': 0, 'connected_count': 0, 'available_count': 0}


def detect_provider_from_email(email: str) -> str:
    """
    Detect OAuth provider from email domain.

    Args:
        email: User's email address

    Returns:
        'google' or 'microsoft'
    """
    if not email or '@' not in email:
        return 'google'  # default

    domain = email.lower().split('@')[1]

    # Google domains
    google_domains = ['gmail.com', 'googlemail.com']
    if domain in google_domains:
        return 'google'

    # Microsoft domains
    microsoft_domains = ['outlook.com', 'hotmail.com', 'live.com', 'msn.com']
    if domain in microsoft_domains:
        return 'microsoft'

    # Default to Google (most common for OAuth)
    return 'google'


def get_provider_oauth_url(provider_key: str) -> Optional[str]:
    """
    Get OAuth URL for a provider.

    Args:
        provider_key: Provider identifier ('google', 'microsoft', etc.)

    Returns:
        OAuth URL or None if not OAuth-based
    """
    oauth_urls = {
        'google': '/api/auth/google/authorize',
        'microsoft': '/api/auth/microsoft-login',
        'whatsapp': '/api/auth/whatsapp/authorize',
        'slack': '/api/auth/slack/authorize',
        'teams': '/api/auth/teams/authorize',
        'zoom': '/api/auth/zoom/authorize'
    }

    return oauth_urls.get(provider_key)


def format_connection_status(status: str) -> str:
    """
    Format connection status with emoji.

    Args:
        status: Connection status ('connected', 'disconnected', 'error', 'coming_soon')

    Returns:
        Formatted status string with emoji
    """
    status_map = {
        'connected': '✅ Connected',
        'disconnected': '❌ Not Connected',
        'error': '⚠️ Error',
        'coming_soon': '⏳ Coming Soon',
        'pending': '🔄 Pending'
    }

    return status_map.get(status, status)


def get_category_emoji(category: str) -> str:
    """
    Get emoji for provider category.

    Args:
        category: Provider category

    Returns:
        Emoji string
    """
    emoji_map = {
        'email': '📧',
        'crm': '💼',
        'messaging': '💬',
        'telephony': '📞',
        'video': '🎥',
        'ai': '🤖'
    }

    return emoji_map.get(category, '🔗')
