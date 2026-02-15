"""Configuration for tool factory.

BYOK (Bring Your Own Key) Model:
- Anthropic API key: Per-user via /connect anthropic (Supabase)
- Pipedrive token: Per-user via /connect pipedrive (Supabase)
- SendGrid key: Per-user via /connect sendgrid (Supabase)
- Vonage credentials: Per-user via /connect vonage (Supabase)
- Microsoft Graph tokens: Per-user via OAuth (Supabase oauth_tokens)
- Google OAuth: Per-user via OAuth (Supabase oauth_tokens)

These credentials are NOT read from env vars - they must be fetched from Supabase.
"""

from dataclasses import dataclass
from typing import Optional

from ..config import settings


@dataclass
class ToolConfig:
    """Configuration for initializing Zylch AI tools.

    This dataclass contains all the configuration needed to initialize
    external services and tools, extracted from the global settings.

    BYOK credentials (anthropic_api_key, pipedrive_api_token, sendgrid_api_key,
    graph_token, graph_refresh_token) are NOT populated from settings.
    Use from_settings_with_owner() to fetch them from Supabase.
    """

    # ============================================
    # Optional fields (with defaults)
    # ============================================

    # BYOK Credentials (fetched from Supabase, not env vars)
    # LLM Provider (anthropic, openai, mistral)
    llm_provider: str = ""
    # Anthropic (BYOK via /connect anthropic)
    anthropic_api_key: str = ""

    # Pipedrive CRM (BYOK via /connect pipedrive)
    pipedrive_api_token: str = ""

    # SendGrid (BYOK via /connect sendgrid)
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = ""

    # Microsoft Graph API (BYOK via OAuth)
    auth_provider: str = "google"
    graph_token: str = ""
    graph_refresh_token: str = ""

    # Vonage SMS: credentials stored per-user in Supabase via /connect vonage
    # (no fields here - fetched directly in sms_tools.py)

    # My Email Addresses
    my_emails: str = ""

    # Multi-tenant Configuration
    owner_id: str = "owner_default"
    zylch_assistant_id: str = "default_assistant"

    # User Identity (for sharing feature)
    user_email: str = ""
    user_display_name: str = ""

    # LLM Model
    default_model: str = "claude-opus-4-6-20260205"

    @classmethod
    def from_settings(cls) -> 'ToolConfig':
        """Create ToolConfig from global settings (without BYOK credentials).

        BYOK credentials (anthropic_api_key, pipedrive_api_token, etc.) are
        left empty - use from_settings_with_owner() to fetch them from Supabase.

        Returns:
            ToolConfig instance with values from global settings
        """
        return cls(
            # My Emails
            my_emails=settings.my_emails,

            # Multi-tenant Configuration
            owner_id=settings.owner_id,
            zylch_assistant_id=settings.zylch_assistant_id,

            # User Identity (for sharing)
            user_email=settings.user_email,
            user_display_name=settings.user_display_name,

            # LLM Model
            default_model=settings.default_model,

            # BYOK credentials left empty - use from_settings_with_owner()
        )

    @classmethod
    def from_settings_with_owner(cls, owner_id: str, storage=None) -> 'ToolConfig':
        """Create ToolConfig from settings AND fetch BYOK credentials from Supabase.

        This method fetches per-user credentials (Anthropic, Pipedrive, SendGrid,
        MS Graph) from Supabase and populates them in the config.

        Args:
            owner_id: Firebase UID for the user
            storage: Optional SupabaseStorage instance (creates new if not provided)

        Returns:
            ToolConfig instance with BYOK credentials populated
        """
        # Start with base settings
        config = cls.from_settings()
        config.owner_id = owner_id

        # Get storage instance
        if storage is None:
            from ..storage.supabase_client import SupabaseStorage
            storage = SupabaseStorage.get_instance()

        # Fetch BYOK credentials from Supabase
        # LLM Provider (detect active provider)
        from ..api.token_storage import get_active_llm_provider
        provider, api_key = get_active_llm_provider(owner_id)
        if provider and api_key:
            config.llm_provider = provider
            config.anthropic_api_key = api_key  # Store in anthropic_api_key for backward compat

        # Anthropic (legacy check - only if not already set by get_active_llm_provider)
        if not config.anthropic_api_key:
            anthropic_key = storage.get_anthropic_key(owner_id)
            if anthropic_key:
                config.anthropic_api_key = anthropic_key
                config.llm_provider = "anthropic"

        # System-level fallback if user has no key configured
        # (useful for integrations like MrCall where operator provides the key)
        if not config.anthropic_api_key and settings.anthropic_api_key:
            config.llm_provider = "anthropic"
            config.anthropic_api_key = settings.anthropic_api_key

        # Pipedrive
        pipedrive_token = storage.get_pipedrive_key(owner_id)
        if pipedrive_token:
            config.pipedrive_api_token = pipedrive_token

        # SendGrid
        sendgrid_key = storage.get_sendgrid_key(owner_id)
        if sendgrid_key:
            config.sendgrid_api_key = sendgrid_key
        sendgrid_from = storage.get_sendgrid_from_email(owner_id)
        if sendgrid_from:
            config.sendgrid_from_email = sendgrid_from

        # Microsoft Graph tokens
        ms_token = storage.get_oauth_token(owner_id, 'microsoft')
        if ms_token:
            config.auth_provider = 'microsoft'
            config.graph_token = ms_token.get('access_token', '')
            config.graph_refresh_token = ms_token.get('refresh_token', '')

        return config
