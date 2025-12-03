"""Configuration for tool factory."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from ..config import settings


@dataclass
class ToolConfig:
    """Configuration for initializing Zylch AI tools.

    This dataclass contains all the configuration needed to initialize
    external services and tools, extracted from the global settings.
    """

    # Anthropic
    anthropic_api_key: str
    default_model: str
    classification_model: str
    executive_model: str

    # Google OAuth (Gmail, Calendar)
    google_credentials_path: str
    google_token_path: str
    gmail_accounts: List[str]
    calendar_id: str

    # StarChat (for contact management)
    starchat_api_url: str
    starchat_api_key: str
    starchat_username: str
    starchat_password: str
    starchat_business_id: str
    starchat_auth_method: str

    # Cache
    cache_dir: str
    cache_ttl_days: int

    # Email Archive
    email_archive_backend: str
    email_archive_sqlite_path: str
    email_archive_postgres_url: str
    email_archive_initial_months: int
    email_archive_batch_size: int
    email_archive_enable_fts: bool

    # Pipedrive CRM (optional)
    pipedrive_api_token: Optional[str] = ""
    pipedrive_enabled: bool = False

    # SendGrid (optional)
    sendgrid_api_key: Optional[str] = ""
    sendgrid_from_email: Optional[str] = ""

    # Vonage SMS (optional)
    vonage_api_key: Optional[str] = ""
    vonage_api_secret: Optional[str] = ""
    vonage_from_number: Optional[str] = ""

    # Email Style
    email_style_prompt: Optional[str] = ""

    # My Email Addresses
    my_emails: str = ""
    bot_emails: str = ""

    # Multi-tenant Configuration
    owner_id: str = "owner_default"
    zylch_assistant_id: str = "default_assistant"

    # User Identity (for sharing feature)
    user_email: str = ""
    user_display_name: str = ""

    # Microsoft Graph API (for Outlook)
    auth_provider: str = "google.com"
    graph_token: str = ""
    graph_refresh_token: str = ""

    @classmethod
    def from_settings(cls) -> 'ToolConfig':
        """Create ToolConfig from global settings.

        Returns:
            ToolConfig instance with values from global settings
        """
        return cls(
            # Anthropic
            anthropic_api_key=settings.anthropic_api_key,
            default_model=settings.default_model,
            classification_model=settings.classification_model,
            executive_model=settings.executive_model,

            # Google OAuth
            google_credentials_path=settings.google_credentials_path,
            google_token_path=settings.google_token_path,
            gmail_accounts=settings.gmail_accounts,
            calendar_id=settings.calendar_id,

            # StarChat
            starchat_api_url=settings.starchat_api_url,
            starchat_api_key=settings.starchat_api_key,
            starchat_username=settings.starchat_username,
            starchat_password=settings.starchat_password,
            starchat_business_id=settings.starchat_business_id,
            starchat_auth_method=settings.starchat_auth_method,

            # Cache
            cache_dir=settings.cache_dir,
            cache_ttl_days=settings.cache_ttl_days,

            # Email Archive
            email_archive_backend=settings.email_archive_backend,
            email_archive_sqlite_path=settings.email_archive_sqlite_path,
            email_archive_postgres_url=settings.email_archive_postgres_url,
            email_archive_initial_months=settings.email_archive_initial_months,
            email_archive_batch_size=settings.email_archive_batch_size,
            email_archive_enable_fts=settings.email_archive_enable_fts,

            # Pipedrive
            pipedrive_api_token=settings.pipedrive_api_token,
            pipedrive_enabled=settings.pipedrive_enabled,

            # SendGrid
            sendgrid_api_key=settings.sendgrid_api_key,
            sendgrid_from_email=settings.sendgrid_from_email,

            # Vonage SMS
            vonage_api_key=settings.vonage_api_key,
            vonage_api_secret=settings.vonage_api_secret,
            vonage_from_number=settings.vonage_from_number,

            # Email Style
            email_style_prompt=settings.email_style_prompt,

            # My Emails
            my_emails=settings.my_emails,
            bot_emails=settings.bot_emails,

            # Multi-tenant Configuration
            owner_id=settings.owner_id,
            zylch_assistant_id=settings.zylch_assistant_id,

            # User Identity (for sharing)
            user_email=settings.user_email,
            user_display_name=settings.user_display_name,

            # Microsoft Graph API (for Outlook)
            auth_provider=settings.auth_provider,
            graph_token=settings.graph_token,
            graph_refresh_token=settings.graph_refresh_token,
        )

    def get_cache_path(self) -> Path:
        """Get cache directory as Path object."""
        path = Path(self.cache_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_email_archive_path(self) -> Path:
        """Get email archive database path (for SQLite)."""
        path = Path(self.email_archive_sqlite_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
