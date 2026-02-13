"""
Logging and retention helper service.
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta
import logging


_FILE_HANDLER_TAG = "stocksbot_file_handler"


def configure_file_logging(log_directory: str) -> Path:
    """Configure root logger to also write into a rolling backend log file path."""
    log_dir = Path(log_directory).expanduser().resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "stocksbot.log"

    root_logger = logging.getLogger()
    existing = next((h for h in root_logger.handlers if getattr(h, "name", "") == _FILE_HANDLER_TAG), None)
    if existing:
        root_logger.removeHandler(existing)
        existing.close()

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.name = _FILE_HANDLER_TAG
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root_logger.addHandler(file_handler)
    if root_logger.level > logging.INFO:
        root_logger.setLevel(logging.INFO)
    return log_dir


def cleanup_old_files(directory: str, retention_days: int) -> int:
    """Delete files older than retention_days in directory. Returns deleted file count."""
    target_dir = Path(directory).expanduser().resolve()
    if not target_dir.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=retention_days)
    deleted = 0
    for path in target_dir.iterdir():
        if not path.is_file():
            continue
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime)
            if modified < cutoff:
                path.unlink(missing_ok=True)
                deleted += 1
        except Exception:
            continue
    return deleted

