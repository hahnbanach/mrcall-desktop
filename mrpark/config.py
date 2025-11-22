"""Configuration management for MrPark."""

import json
from pathlib import Path
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """MrPark configuration loaded from .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Anthropic
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
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
    google_token_path: str = Field(
        default="credentials/google_tokens/",
        description="Directory for Google OAuth tokens"
    )

    # Gmail
    gmail_accounts: List[str] = Field(
        default_factory=list,
        description="List of authorized Gmail accounts"
    )

    # Google Calendar
    calendar_id: str = Field(default="primary", description="Calendar ID to use")

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

    # Vonage SMS
    vonage_api_key: str = Field(default="", description="Vonage API key")
    vonage_api_secret: str = Field(default="", description="Vonage API secret")
    vonage_from_number: str = Field(
        default="",
        description="Vonage sender phone number"
    )

    # Webhook Server
    webhook_host: str = Field(default="0.0.0.0", description="Webhook server host")
    webhook_port: int = Field(default=8000, description="Webhook server port")
    webhook_public_url: str = Field(
        default="",
        description="Public URL for webhooks"
    )

    # StarChat
    starchat_api_url: str = Field(
        default="https://mrcall-0.scw.hbsrv.net:443",
        description="StarChat API base URL"
    )
    starchat_api_key: str = Field(default="", description="StarChat API key")
    starchat_username: str = Field(default="admin", description="StarChat username")
    starchat_password: str = Field(default="", description="StarChat password")
    starchat_business_id: str = Field(default="", description="StarChat business ID")
    starchat_auth_method: str = Field(
        default="basic",
        description="Auth method: basic or jwt"
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

    # CRM (Optional)
    pipedrive_api_token: str = Field(default="", description="Pipedrive API token")
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


# Global settings instance
settings = Settings()
