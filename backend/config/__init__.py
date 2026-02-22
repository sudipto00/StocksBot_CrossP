"""
Configuration module for StocksBot backend.

Provides settings management using pydantic-settings.
Supports loading from environment variables and .env files.
"""

from .settings import Settings, get_settings, has_alpaca_credentials
from .paths import (
    APP_IDENTIFIER,
    resolve_app_data_dir,
    default_database_url,
    default_log_directory,
    default_audit_export_directory,
)

__all__ = [
    "Settings",
    "get_settings",
    "has_alpaca_credentials",
    "APP_IDENTIFIER",
    "resolve_app_data_dir",
    "default_database_url",
    "default_log_directory",
    "default_audit_export_directory",
]
