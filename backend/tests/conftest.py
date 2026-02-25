"""Shared pytest bootstrap for backend tests."""

from __future__ import annotations

import os

import pytest


def _apply_test_auth_env() -> None:
    """Force API-key auth off for tests regardless of local .env values."""
    os.environ["STOCKSBOT_API_KEY_AUTH_ENABLED"] = "false"
    # Must be an explicit empty string (not unset), otherwise Settings may
    # still pick up STOCKSBOT_API_KEY from dotenv candidates.
    os.environ["STOCKSBOT_API_KEY"] = ""


def _reset_settings_singleton() -> None:
    """Clear cached settings so env overrides are re-read."""
    try:
        from config import settings as settings_module

        settings_module._settings = None
    except Exception:
        # Keep bootstrap resilient even if import ordering changes.
        pass


_apply_test_auth_env()
_reset_settings_singleton()


def pytest_configure(config: pytest.Config) -> None:
    _ = config
    _apply_test_auth_env()
    _reset_settings_singleton()


@pytest.fixture(autouse=True)
def _enforce_test_settings_isolation():
    _apply_test_auth_env()
    _reset_settings_singleton()
    yield
    _reset_settings_singleton()
