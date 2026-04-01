"""Configuration management for Zylch AI."""

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
        description="Log level: DEBUG, INFO, WARNING, ERROR",
    )

    # Database (SQLite default for standalone)
    database_url: str = Field(
        default="",
        description=(
            "SQLAlchemy database URL"
            " (default: sqlite:///~/.zylch/zylch.db)"
        ),
    )

    # Encryption (for sensitive data at rest)
    encryption_key: str = Field(
        default="",
        description=(
            "Fernet encryption key for API keys."
            " Generate: python -c"
            " 'from cryptography.fernet import Fernet;"
            " print(Fernet.generate_key().decode())'"
        ),
    )

    # Owner / assistant identity (local single-user)
    owner_id: str = Field(
        default="owner_default",
        description="Owner ID for data isolation",
    )
    zylch_assistant_id: str = Field(
        default="default_assistant",
        description="Zylch assistant ID",
    )

    # User identity
    user_email: str = Field(
        default="",
        description="User email address",
    )
    user_display_name: str = Field(
        default="",
        description="User display name",
    )

    # My email addresses (for contact identification)
    my_emails: str = Field(
        default="",
        description=(
            "Comma-separated list of my email addresses"
            " (supports wildcards like *@domain.com)"
        ),
    )

    # Performance
    enable_prompt_caching: bool = Field(
        default=True,
        description="Enable prompt caching",
    )

    # LLM API keys
    anthropic_api_key: str = Field(
        default="",
        description="Anthropic API key",
    )
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key",
    )
    system_llm_provider: str = Field(
        default="anthropic",
        description=(
            "LLM provider (anthropic, openai)"
        ),
    )

    # LLM models
    default_model: str = Field(
        default="claude-opus-4-6",
        description="Default model for all AI operations",
    )
    anthropic_model: str = Field(
        default="claude-opus-4-6",
        description="Anthropic model to use",
    )
    openai_model: str = Field(
        default="gpt-4.1",
        description="OpenAI model to use",
    )

    # IMAP/SMTP Email
    email_address: str = Field(
        default="",
        description="Email address for IMAP/SMTP access",
    )
    email_password: str = Field(
        default="",
        description=(
            "App password for IMAP/SMTP"
            " (NOT account password)"
        ),
    )
    imap_host: str = Field(
        default="",
        description=(
            "IMAP server hostname"
            " (auto-detected from email domain)"
        ),
    )
    imap_port: int = Field(
        default=993,
        description="IMAP server port (default 993)",
    )
    smtp_host: str = Field(
        default="",
        description=(
            "SMTP server hostname"
            " (auto-detected from email domain)"
        ),
    )
    smtp_port: int = Field(
        default=587,
        description="SMTP server port (default 587)",
    )

    # Email archive
    email_archive_batch_size: int = Field(
        default=10,
        description=(
            "Emails to fetch per batch"
            " during archive sync"
        ),
    )

    # MrCall / StarChat (optional channel)
    mrcall_base_url: str = Field(
        default="https://test-env-0.scw.hbsrv.net",
        env="MRCALL_BASE_URL",
        description="StarChat API base URL for MrCall",
    )
    starchat_verify_ssl: bool = Field(
        default=True,
        env="STARCHAT_VERIFY_SSL",
        description=(
            "Verify SSL for StarChat API calls"
        ),
    )


# Global settings instance
settings = Settings()
