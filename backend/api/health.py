"""
Production health check endpoint.

Reports real subsystem status instead of a static response:
- Database connectivity
- Broker connection status
- Background scheduler status
- Optimizer dispatcher status
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import text

from storage.database import SessionLocal

logger = logging.getLogger(__name__)

# Track startup time for uptime reporting
_startup_time: float = time.monotonic()
_startup_utc: str = datetime.now(timezone.utc).isoformat()

_APP_VERSION = "0.1.0"


def mark_startup() -> None:
    """Call once at startup to record the process start time."""
    global _startup_time, _startup_utc
    _startup_time = time.monotonic()
    _startup_utc = datetime.now(timezone.utc).isoformat()


def build_health_response() -> Dict[str, Any]:
    """
    Build a comprehensive health check payload.

    Returns a dict with:
      status: "healthy" | "degraded" | "unhealthy"
      checks: per-subsystem status
      uptime_seconds: process uptime
      version: app version
    """
    checks: Dict[str, Dict[str, Any]] = {}
    overall_healthy = True
    degraded = False

    # ── Database ─────────────────────────────────────────────────────────
    db_ok = False
    db_error = ""
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            db_ok = True
        finally:
            db.close()
    except Exception as exc:
        db_error = str(exc)[:200]
        overall_healthy = False

    checks["database"] = {
        "status": "up" if db_ok else "down",
        "error": db_error or None,
    }

    # ── Broker ───────────────────────────────────────────────────────────
    broker_ok = False
    broker_error = ""
    try:
        from api.routes import get_broker
        broker = get_broker()
        broker_ok = bool(broker.is_connected())
    except RuntimeError as exc:
        broker_error = str(exc)[:200]
        degraded = True
    except Exception as exc:
        broker_error = str(exc)[:200]
        degraded = True

    checks["broker"] = {
        "status": "up" if broker_ok else "degraded",
        "error": broker_error or None,
    }

    # ── Strategy Runner ──────────────────────────────────────────────────
    runner_status = "unknown"
    try:
        from api.runner_manager import runner_manager
        status = runner_manager.get_status()
        runner_status = str(status.get("status", "stopped"))
    except Exception:
        runner_status = "unknown"
        degraded = True

    checks["runner"] = {
        "status": runner_status,
    }

    # ── Optimizer Dispatcher ─────────────────────────────────────────────
    optimizer_running = False
    try:
        from api.routes import _optimizer_dispatcher_is_running
        optimizer_running = _optimizer_dispatcher_is_running()
    except Exception:
        pass

    checks["optimizer_dispatcher"] = {
        "status": "running" if optimizer_running else "stopped",
    }

    # ── Summary Scheduler ────────────────────────────────────────────────
    scheduler_running = False
    try:
        from api.routes import _summary_scheduler_thread
        scheduler_running = _summary_scheduler_thread is not None and _summary_scheduler_thread.is_alive()
    except Exception:
        pass

    checks["summary_scheduler"] = {
        "status": "running" if scheduler_running else "stopped",
    }

    # ── Overall status ───────────────────────────────────────────────────
    if not overall_healthy:
        status = "unhealthy"
    elif degraded:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "service": "StocksBot Backend",
        "version": _APP_VERSION,
        "uptime_seconds": round(time.monotonic() - _startup_time, 1),
        "started_at": _startup_utc,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }
