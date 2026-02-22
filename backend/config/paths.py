"""
Filesystem path helpers for local and bundled desktop runtime.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


APP_IDENTIFIER = "com.stocksbot.app"


def _env_override_path() -> Path | None:
    raw = str(os.getenv("STOCKSBOT_APP_DATA_DIR", "")).strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _ensure_writable_dir(target: Path) -> Path:
    """
    Ensure target directory is writable; fallback to workspace-local directory when sandboxed.
    """
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".stocksbot_write_test"
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        probe.unlink(missing_ok=True)
        return target
    except Exception:
        fallback = (Path.cwd() / ".stocksbot-data").resolve()
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback
        except Exception:
            final_fallback = (Path(tempfile.gettempdir()) / "stocksbot-data").resolve()
            final_fallback.mkdir(parents=True, exist_ok=True)
            return final_fallback


def resolve_app_data_dir() -> Path:
    """
    Resolve per-user application data directory across platforms.
    """
    override = _env_override_path()
    if override is not None:
        return _ensure_writable_dir(override)

    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        appdata = str(os.getenv("APPDATA", "")).strip()
        base = Path(appdata) if appdata else (Path.home() / "AppData" / "Roaming")
    else:
        xdg_data_home = str(os.getenv("XDG_DATA_HOME", "")).strip()
        base = Path(xdg_data_home) if xdg_data_home else (Path.home() / ".local" / "share")

    target = (base / APP_IDENTIFIER).expanduser().resolve()
    return _ensure_writable_dir(target)


def default_database_url() -> str:
    db_path = (resolve_app_data_dir() / "stocksbot.db").resolve()
    # SQLAlchemy sqlite URL requires 3 slashes + absolute path.
    return f"sqlite:///{db_path}"


def default_log_directory() -> str:
    return str((resolve_app_data_dir() / "logs").resolve())


def default_audit_export_directory() -> str:
    return str((resolve_app_data_dir() / "audit_exports").resolve())
