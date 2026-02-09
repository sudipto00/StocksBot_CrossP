"""
Configuration module for StocksBot backend.

Provides settings management using pydantic-settings.
Supports loading from environment variables and .env files.
"""

from .settings import Settings, get_settings, has_alpaca_credentials

__all__ = ["Settings", "get_settings", "has_alpaca_credentials"]
