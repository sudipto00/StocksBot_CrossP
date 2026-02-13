"""
Application Settings and Configuration.

Loads configuration from environment variables and config files.
Supports Alpaca broker credentials and other app settings.
"""

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


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
        default="sqlite:///./stocksbot.db",
        alias="DATABASE_URL"
    )
    
    # Application Configuration
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # API authentication (optional for local desktop dev/test)
    api_auth_enabled: bool = Field(default=False, alias="STOCKSBOT_API_KEY_AUTH_ENABLED")
    api_auth_key: Optional[str] = Field(default=None, alias="STOCKSBOT_API_KEY")
    
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
