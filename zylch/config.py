"""Configuration management for Zylch AI."""

from pathlib import Path

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

    # Google OAuth (shared by Gmail, Calendar, etc.)
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

    # Firebase Authentication (for dashboard integration)
    firebase_service_account_base64: str = Field(
        default="",
        description="Firebase service account JSON as Base64 (for Railway - avoids escaping issues)"
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

    # MrCall OAuth (via StarChat API)
    mrcall_client_id: str = Field(
        default="",
        env="MRCALL_CLIENT_ID",
        description="MrCall OAuth client ID"
    )
    mrcall_client_secret: str = Field(
        default="",
        env="MRCALL_CLIENT_SECRET",
        description="MrCall OAuth client secret"
    )
    mrcall_realm: str = Field(
        default="mrcall0",
        env="MRCALL_REALM",
        description="MrCall realm for StarChat API"
    )
    mrcall_base_url: str = Field(
        default="https://test-env-0.scw.hbsrv.net",
        env="MRCALL_BASE_URL",
        description="StarChat API base URL for MrCall"
    )
    mrcall_oauth_authorize_url: str = Field(
        default="https://dashboard-test.mrcall.ai/oauth/authorize",
        env="MRCALL_OAUTH_AUTHORIZE_URL",
        description="MrCall Dashboard OAuth authorize URL (consent page is served by Dashboard, not API)"
    )

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

    # My Email Addresses (for contact identification)
    my_emails: str = Field(
        default="",
        description="Comma-separated list of my email addresses (supports wildcards like *@domain.com)"
    )

    # Performance Optimization
    enable_prompt_caching: bool = Field(default=True, description="Enable prompt caching")

    # Alpha Testers Allowlist
    alpha_testers_file: str = Field(
        default="data/alpha_testers.txt",
        description="Path to file containing allowed alpha tester emails (one per line)"
    )
    alpha_testers_enabled: bool = Field(
        default=True,
        description="Enable alpha testers allowlist check"
    )

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
        except Exception as e:
            # Log the error but return empty set to fail safe (allowlist enabled but empty = no one gets in)
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to read alpha testers file: {e}")
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
