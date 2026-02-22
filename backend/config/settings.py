"""
Application Settings and Configuration.

Loads configuration from environment variables and config files.
Supports Alpaca broker credentials and other app settings.
"""

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from .paths import default_database_url


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    Environment variables:
        ALPACA_API_KEY: Alpaca API key (paper or live)
        ALPACA_SECRET_KEY: Alpaca secret key
        ALPACA_PAPER: Use paper trading (default: true)
        DATABASE_URL: Database connection URL (default: sqlite)
    """
    
    # Alpaca Configuration
    alpaca_api_key: Optional[str] = Field(default=None, alias="ALPACA_API_KEY")
    alpaca_secret_key: Optional[str] = Field(default=None, alias="ALPACA_SECRET_KEY")
    alpaca_paper: bool = Field(default=True, alias="ALPACA_PAPER")
    
    # Validators to strip whitespace from credentials
    @classmethod
    def validate_api_key(cls, v):
        """Strip whitespace from API key to prevent authentication failures."""
        return v.strip() if v else v
    
    @classmethod
    def validate_secret_key(cls, v):
        """Strip whitespace from secret key to prevent authentication failures."""
        return v.strip() if v else v
    
    # Database Configuration
    database_url: str = Field(
        default=default_database_url(),
        alias="DATABASE_URL"
    )
    
    # Application Configuration
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # API authentication (optional for local desktop dev/test)
    api_auth_enabled: bool = Field(default=False, alias="STOCKSBOT_API_KEY_AUTH_ENABLED")
    api_auth_key: Optional[str] = Field(default=None, alias="STOCKSBOT_API_KEY")
    backend_reload: bool = Field(default=False, alias="STOCKSBOT_BACKEND_RELOAD")

    # Notification delivery (email + sms)
    summary_notifications_enabled: bool = Field(default=True, alias="STOCKSBOT_SUMMARY_NOTIFICATIONS_ENABLED")
    summary_scheduler_enabled: bool = Field(default=True, alias="STOCKSBOT_SUMMARY_SCHEDULER_ENABLED")
    summary_scheduler_poll_seconds: int = Field(default=60, alias="STOCKSBOT_SUMMARY_SCHEDULER_POLL_SECONDS")
    summary_scheduler_retry_seconds: int = Field(default=1800, alias="STOCKSBOT_SUMMARY_SCHEDULER_RETRY_SECONDS")

    # SMTP email delivery configuration
    smtp_host: Optional[str] = Field(default=None, alias="STOCKSBOT_SMTP_HOST")
    smtp_port: int = Field(default=587, alias="STOCKSBOT_SMTP_PORT")
    smtp_username: Optional[str] = Field(default=None, alias="STOCKSBOT_SMTP_USERNAME")
    smtp_password: Optional[str] = Field(default=None, alias="STOCKSBOT_SMTP_PASSWORD")
    smtp_from_email: Optional[str] = Field(default=None, alias="STOCKSBOT_SMTP_FROM_EMAIL")
    smtp_use_tls: bool = Field(default=True, alias="STOCKSBOT_SMTP_USE_TLS")
    smtp_use_ssl: bool = Field(default=False, alias="STOCKSBOT_SMTP_USE_SSL")
    smtp_timeout_seconds: int = Field(default=15, alias="STOCKSBOT_SMTP_TIMEOUT_SECONDS")

    # Twilio SMS delivery configuration
    twilio_account_sid: Optional[str] = Field(default=None, alias="STOCKSBOT_TWILIO_ACCOUNT_SID")
    twilio_auth_token: Optional[str] = Field(default=None, alias="STOCKSBOT_TWILIO_AUTH_TOKEN")
    twilio_from_number: Optional[str] = Field(default=None, alias="STOCKSBOT_TWILIO_FROM_NUMBER")
    twilio_timeout_seconds: int = Field(default=15, alias="STOCKSBOT_TWILIO_TIMEOUT_SECONDS")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """
    Get application settings singleton.
    
    Returns:
        Settings instance
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def has_alpaca_credentials() -> bool:
    """
    Check if Alpaca credentials are configured.
    
    Returns:
        True if both API key and secret are set
    """
    settings = get_settings()
    return (
        settings.alpaca_api_key is not None
        and settings.alpaca_secret_key is not None
        and settings.alpaca_api_key != ""
        and settings.alpaca_secret_key != ""
    )
