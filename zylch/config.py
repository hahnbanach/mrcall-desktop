"""Configuration management for Zylch AI."""

import json
from pathlib import Path
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Zylch AI configuration loaded from .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Log level: DEBUG, INFO, WARNING, ERROR"
    )

    # Anthropic - REMOVED from .env, now BYOK only via Supabase
    # Users set their Anthropic API key via /connect anthropic command
    default_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Default model for general tasks"
    )
    classification_model: str = Field(
        default="claude-3-5-haiku-20241022",
        description="Fast model for classification"
    )
    executive_model: str = Field(
        default="claude-opus-4-20250514",
        description="Premium model for executive communications"
    )

    # Google OAuth (shared by Gmail, Calendar, etc.)
    google_credentials_path: str = Field(
        default="credentials/google_oauth.json",
        description="Path to Google OAuth credentials (used for Gmail, Calendar, etc.)"
    )
    # google_token_path: REMOVED - all tokens stored in Supabase, no filesystem
    google_client_id: str = Field(
        default="",
        description="Google OAuth client ID (for server-side OAuth flow)"
    )
    google_client_secret: str = Field(
        default="",
        description="Google OAuth client secret (for server-side OAuth flow)"
    )
    google_oauth_redirect_uri: str = Field(
        default="",
        description="Google OAuth redirect URI (e.g., https://api.zylch.ai/api/auth/google/callback)"
    )

    # Gmail
    gmail_accounts: List[str] = Field(
        default_factory=list,
        description="List of authorized Gmail accounts"
    )

    # Google Calendar
    calendar_id: str = Field(default="primary", description="Calendar ID to use")

    # Firebase Authentication (for dashboard integration)
    firebase_service_account_path: str = Field(
        default="",
        description="Path to Firebase service account JSON file"
    )
    firebase_service_account_json: str = Field(
        default="",
        description="Firebase service account JSON as string (for cloud deployments)"
    )
    firebase_service_account_base64: str = Field(
        default="",
        description="Firebase service account JSON as Base64 (for cloud deployments - avoids escaping issues)"
    )
    firebase_project_id: str = Field(
        default="",
        description="Firebase project ID"
    )

    # Firebase Client SDK (for CLI browser-based login)
    firebase_api_key: str = Field(
        default="",
        description="Firebase API key for client SDK"
    )
    firebase_auth_domain: str = Field(
        default="",
        description="Firebase auth domain (e.g., project-id.firebaseapp.com)"
    )

    # Supabase (multi-tenant database)
    supabase_url: str = Field(
        default="",
        description="Supabase project URL"
    )
    supabase_anon_key: str = Field(
        default="",
        description="Supabase anon/public key"
    )
    supabase_service_role_key: str = Field(
        default="",
        description="Supabase service role key (secret, for backend)"
    )

    # Encryption (for sensitive data at rest)
    encryption_key: str = Field(
        default="",
        description="Fernet encryption key for OAuth tokens and API keys. Generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
    )

    # Microsoft Graph API (for Outlook email)
    graph_token: str = Field(
        default="",
        description="Microsoft Graph API access token (from login)"
    )
    graph_refresh_token: str = Field(
        default="",
        description="Microsoft Graph API refresh token"
    )
    auth_provider: str = Field(
        default="google",
        description="Authentication provider (google or microsoft)"
    )

    # CORS Configuration (for dashboard integration)
    cors_allowed_origins: str = Field(
        default="http://localhost:8080,http://localhost:3000",
        description="Comma-separated list of allowed CORS origins"
    )

    # Email signature
    made_by_zylch_email: str = Field(
        default="Written with the help of Zylch AI",
        description="Signature appended to all outgoing emails"
    )

    # SendGrid
    sendgrid_api_key: str = Field(default="", description="SendGrid API key")
    sendgrid_from_email: str = Field(
        default="noreply@example.com",
        description="Default sender email"
    )
    sendgrid_webhook_secret: str = Field(
        default="",
        description="Webhook signature verification secret"
    )

    # Vonage SMS: credentials are stored per-user in Supabase via /connect vonage
    # No env vars needed - credentials loaded at tool execution time

    # API Server (for thin client)
    api_server_url: str = Field(
        default="http://localhost:8000",
        description="Zylch API server URL for CLI thin client"
    )

    # Webhook Server
    webhook_host: str = Field(default="0.0.0.0", description="Webhook server host")
    webhook_port: int = Field(default=8000, description="Webhook server port")
    webhook_public_url: str = Field(
        default="",
        description="Public URL for webhooks"
    )

    # StarChat - REMOVED (future: OAuth2.0 integration)
    # StarChat credentials will be per-user via /connect starchat (OAuth2.0)
    # For now, StarChat features are disabled until OAuth2.0 is implemented

    # Multi-tenant Configuration
    owner_id: str = Field(
        default="owner_default",
        description="Owner ID (Firebase UID or placeholder)"
    )
    zylch_assistant_id: str = Field(
        default="default_assistant",
        description="Zylch assistant ID"
    )

    # User Identity (for sharing feature)
    user_email: str = Field(
        default="",
        description="Current user's email address (for sharing system)"
    )
    user_display_name: str = Field(
        default="",
        description="Current user's display name (for sharing system)"
    )

    # Cache
    cache_dir: str = Field(default="cache/", description="Cache directory")
    cache_ttl_days: int = Field(default=30, description="Cache TTL in days")

    # Campaign Data
    campaigns_file: str = Field(
        default="data/campaigns.json",
        description="Campaign configuration file"
    )
    templates_file: str = Field(
        default="data/templates.json",
        description="Email templates file"
    )

    # CRM (Optional) - Pipedrive API token REMOVED from .env, now BYOK via Supabase
    # Users set their Pipedrive API key via /connect pipedrive command
    pipedrive_enabled: bool = Field(default=False, description="Enable Pipedrive")

    # Apollo (Future)
    apollo_api_key: str = Field(default="", description="Apollo.io API key")
    apollo_enabled: bool = Field(default=False, description="Enable Apollo.io")

    # Email Style Preferences
    email_style_prompt: str = Field(
        default="",
        description="Custom email writing style instructions"
    )

    # My Email Addresses (for contact identification)
    my_emails: str = Field(
        default="",
        description="Comma-separated list of my email addresses (supports wildcards like *@domain.com)"
    )

    # Bot Email Patterns (to downgrade priority)
    bot_emails: str = Field(
        default="*@noreply.*,*@no-reply.*,noreply@*,no-reply@*,*@notifications.*,notifications@*,*@updates.*,updates@*,*@alerts.*,alerts@*,*@automated.*,automated@*",
        description="Comma-separated list of bot email patterns (supports wildcards)"
    )

    # Skill System Configuration
    skill_router_model: str = Field(
        default="claude-3-5-haiku-20241022",
        description="Model for intent classification (router)"
    )
    skill_execution_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Model for skill execution"
    )
    skill_pattern_model: str = Field(
        default="claude-3-5-haiku-20241022",
        description="Model for pattern matching"
    )

    # Performance Optimization
    enable_prompt_caching: bool = Field(default=True, description="Enable prompt caching")
    enable_batch_processing: bool = Field(default=False, description="Enable batch processing")
    claude_queue_enabled: bool = Field(default=False, description="Enable API request queue")

    # Pattern Learning System
    pattern_store_enabled: bool = Field(default=True, description="Enable pattern store")
    pattern_store_path: str = Field(default=".swarm/patterns.db", description="Pattern store path")
    pattern_confidence_threshold: float = Field(default=0.5, description="Pattern confidence threshold")
    pattern_max_results: int = Field(default=3, description="Max pattern results")

    # Storage Backend
    storage_backend: str = Field(default="json", description="Storage backend: json, sqlite, hybrid")
    sqlite_db_path: str = Field(default=".swarm/threads.db", description="SQLite database path")

    # Skill System Feature Flags
    skill_mode_enabled: bool = Field(default=False, description="Enable skill-based interface")

    # Alpha Testers Allowlist
    alpha_testers_file: str = Field(
        default="data/alpha_testers.txt",
        description="Path to file containing allowed alpha tester emails (one per line)"
    )
    alpha_testers_enabled: bool = Field(
        default=True,
        description="Enable alpha testers allowlist check"
    )

    # Email Archive Configuration
    email_archive_backend: str = Field(
        default="sqlite",
        description="Email archive backend: sqlite or postgres"
    )
    email_archive_sqlite_path: str = Field(
        default="cache/emails/archive.db",
        description="SQLite database path for email archive"
    )
    email_archive_postgres_url: str = Field(
        default="",
        description="PostgreSQL connection URL for email archive"
    )
    email_archive_initial_months: int = Field(
        default=1,
        description="Months of email to fetch during initial sync"
    )
    email_archive_batch_size: int = Field(
        default=500,
        description="Messages per batch during archive sync"
    )
    email_archive_enable_fts: bool = Field(
        default=True,
        description="Enable full-text search in email archive"
    )

    def get_cache_path(self) -> Path:
        """Get cache directory as Path object."""
        path = Path(self.cache_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_campaigns_path(self) -> Path:
        """Get campaigns file path."""
        path = Path(self.campaigns_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_templates_path(self) -> Path:
        """Get templates file path."""
        path = Path(self.templates_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_email_archive_path(self) -> Path:
        """Get email archive database path (for SQLite)."""
        path = Path(self.email_archive_sqlite_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_alpha_testers(self) -> set:
        """Get set of allowed alpha tester emails.

        Returns:
            Set of lowercase email addresses from the alpha testers file.
            Returns empty set if file doesn't exist or allowlist is disabled.
        """
        if not self.alpha_testers_enabled:
            return set()

        try:
            # Try relative path first, then absolute from module location
            path = Path(self.alpha_testers_file)
            if not path.exists():
                # Try relative to this module's directory
                module_dir = Path(__file__).parent.parent
                path = module_dir / self.alpha_testers_file
            if not path.exists():
                return set()

            emails = set()
            with open(path, 'r') as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if line and not line.startswith('#'):
                        emails.add(line.lower())
            return emails
        except Exception:
            return set()

    def is_alpha_tester(self, email: str) -> bool:
        """Check if email is in the alpha testers list.

        Args:
            email: Email address to check

        Returns:
            True if allowlist is disabled OR email is in the list.
            False if allowlist is enabled AND email is not in the list.
        """
        if not self.alpha_testers_enabled:
            return True  # Everyone allowed when disabled

        if not email:
            return False

        allowed = self.get_alpha_testers()
        return email.lower() in allowed


# Global settings instance
settings = Settings()
