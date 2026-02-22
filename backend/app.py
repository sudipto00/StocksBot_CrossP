"""
StocksBot FastAPI Backend
Main application entry point for the sidecar backend.

Production features:
- Real health check with subsystem status
- Request correlation IDs for log tracing
- Structured JSON logging
- Rate limiting per endpoint
- Graceful shutdown with in-flight request draining
"""
import asyncio
import json
import multiprocessing
import os
import secrets
import signal
import sys
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
import logging
import uvicorn

from api.routes import (
    router as api_router,
    start_summary_scheduler,
    stop_summary_scheduler,
    start_optimizer_dispatcher,
    stop_optimizer_dispatcher,
)
from api.middleware import (
    correlation_id_middleware,
    configure_structured_logging,
    limiter,
    rate_limit_exceeded_handler,
)
from api.health import build_health_response, mark_startup
from config.settings import get_settings
from storage.database import init_db, check_integrity, backup_sqlite_database

logger = logging.getLogger(__name__)
SENSITIVE_KEYS = {"api_key", "secret_key", "password", "token", "authorization"}
AUTH_SKIP_PATHS = {
    "/",
    "/status",
    "/errors/frontend",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}

# ── Graceful Shutdown State ──────────────────────────────────────────────────
_shutdown_event = threading.Event()
_SHUTDOWN_TIMEOUT_SECONDS = 10


def _parse_bool_like(value: str | None) -> bool | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "f", "no", "n", "off"}:
        return False
    return None


def _resolve_backend_reload_enabled() -> bool:
    """
    Resolve backend auto-reload mode.
    Precedence:
      1. STOCKSBOT_BACKEND_RELOAD env var
      2. persisted runtime config (`backend_reload_enabled`)
      3. safe default (False)
    """
    env_value = _parse_bool_like(os.getenv("STOCKSBOT_BACKEND_RELOAD"))
    if env_value is not None:
        return env_value

    try:
        from storage.database import SessionLocal
        from storage.models import Config as DBConfig
        db = SessionLocal()
        try:
            row = db.query(DBConfig).filter(DBConfig.key == "runtime_config").first()
            if not row or not row.value:
                return False
            payload = json.loads(row.value)
            raw = payload.get("backend_reload_enabled")
            if isinstance(raw, bool):
                return raw
            return bool(_parse_bool_like(str(raw)))
        finally:
            db.close()
    except Exception:
        return False


def _is_shutting_down() -> bool:
    return _shutdown_event.is_set()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Manage background service lifecycle with graceful shutdown."""
    settings = get_settings()
    configure_structured_logging(settings.log_level)
    mark_startup()
    logger.info("StocksBot backend starting up (env=%s)", settings.environment)

    # ── Database init ────────────────────────────────────────────────────
    try:
        init_db()
        logger.info("Database initialized successfully")
    except (RuntimeError, ValueError, TypeError):
        logger.exception("Failed to initialize database schema")
        raise

    # ── Database integrity check + backup ────────────────────────────────
    try:
        ok, result = check_integrity()
        if not ok:
            logger.critical("Database integrity check failed: %s — continuing anyway", result)
    except Exception:
        logger.exception("Database integrity check could not run")

    try:
        backup_path = backup_sqlite_database()
        logger.info("Startup database backup created: %s", backup_path)
    except Exception:
        logger.warning("Database backup on startup failed (non-blocking)", exc_info=True)

    # ── Startup validation ───────────────────────────────────────────────
    if settings.environment == "production" and not settings.api_auth_key:
        logger.warning(
            "Production environment detected but STOCKSBOT_API_KEY is not set. "
            "API authentication is disabled."
        )

    # ── Start background services ────────────────────────────────────────
    try:
        started = start_summary_scheduler()
        if started:
            logger.info("Summary notification scheduler started")
    except (RuntimeError, ValueError, TypeError):
        logger.exception("Failed to start summary notification scheduler")
    try:
        optimizer_started = start_optimizer_dispatcher()
        if optimizer_started:
            logger.info("Optimizer dispatcher started")
    except (RuntimeError, ValueError, TypeError):
        logger.exception("Failed to start optimizer dispatcher")

    try:
        yield
    finally:
        # ── Graceful shutdown sequence ───────────────────────────────────
        logger.info("Initiating graceful shutdown...")
        _shutdown_event.set()

        # 1. Do NOT cancel optimizer jobs on shutdown — they are persisted in the
        # database and the dispatcher will auto-recover them (requeue orphaned
        # "running" jobs) when the backend restarts.  Force-cancelling here was
        # destroying long-running optimizer work on every watchdog restart, reload,
        # or normal app quit + reopen cycle.

        # 2. Stop the strategy runner gracefully
        try:
            from api.runner_manager import runner_manager
            status = runner_manager.get_status()
            runner_status = str(status.get("status", "stopped")).lower()
            if runner_status in {"running", "sleeping"}:
                from storage.database import SessionLocal
                db = SessionLocal()
                try:
                    runner_manager.stop_runner(db=db)
                    logger.info("Strategy runner stopped gracefully")
                finally:
                    db.close()
        except Exception:
            logger.exception("Error stopping strategy runner during shutdown")

        # 3. Stop optimizer dispatcher (workers will be orphaned but auto-recovered on restart)
        try:
            optimizer_stopped = stop_optimizer_dispatcher()
            if optimizer_stopped:
                logger.info("Optimizer dispatcher stopped")
        except (RuntimeError, ValueError, TypeError):
            logger.exception("Failed to stop optimizer dispatcher")

        # 4. Stop summary scheduler
        try:
            stopped = stop_summary_scheduler()
            if stopped:
                logger.info("Summary notification scheduler stopped")
        except (RuntimeError, ValueError, TypeError):
            logger.exception("Failed to stop summary notification scheduler")

        # 5. Allow in-flight requests to drain
        await asyncio.sleep(0.5)
        logger.info("Graceful shutdown complete")


app = FastAPI(
    title="StocksBot API",
    description="Cross-platform StocksBot backend service",
    version="0.1.0",
    lifespan=_lifespan,
    openapi_tags=[
        {"name": "Config", "description": "Application configuration"},
        {"name": "Broker", "description": "Broker connection and account management"},
        {"name": "Positions", "description": "Portfolio positions"},
        {"name": "Orders", "description": "Order creation and management"},
        {"name": "Notifications", "description": "Notification preferences and delivery"},
        {"name": "Strategies", "description": "Strategy CRUD and configuration"},
        {"name": "Audit", "description": "Audit logs and trade history"},
        {"name": "Runner", "description": "Strategy runner lifecycle"},
        {"name": "Safety", "description": "Kill switch, panic stop, and safety controls"},
        {"name": "Maintenance", "description": "Cleanup and data management"},
        {"name": "Analytics", "description": "Portfolio analytics and metrics"},
        {"name": "Backtesting", "description": "Strategy backtesting and parameter tuning"},
        {"name": "Optimizer", "description": "Strategy optimization jobs"},
        {"name": "Screener", "description": "Market screener and symbol universe"},
        {"name": "Preferences", "description": "Trading preferences and risk profiles"},
        {"name": "Budget", "description": "Budget tracking and limits"},
    ],
)

# ── Rate Limiter ─────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(429, rate_limit_exceeded_handler)

# Compress responses >= 500 bytes (applied first, outermost middleware)
app.add_middleware(GZipMiddleware, minimum_size=500)

# Configure CORS for Tauri frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "tauri://localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _redact_payload(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                redacted[key] = "***REDACTED***"
            else:
                redacted[key] = _redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    return value


def _auth_required() -> bool:
    """Return whether API-key auth must be enforced for requests."""
    settings = get_settings()
    if settings.api_auth_enabled:
        return True
    # If a key is configured explicitly, require it.
    return bool(settings.api_auth_key and settings.api_auth_key.strip())


def _extract_api_key(request: Request) -> str:
    """Extract API key from X-API-Key or Bearer token header."""
    direct_key = request.headers.get("x-api-key", "").strip()
    if direct_key:
        return direct_key
    auth_header = request.headers.get("authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return ""


def _should_skip_auth(path: str) -> bool:
    if path in AUTH_SKIP_PATHS:
        return True
    if path.startswith("/docs") or path.startswith("/redoc") or path.startswith("/openapi"):
        return True
    return False


# ── Correlation ID middleware (outermost - wraps everything) ─────────────────
@app.middleware("http")
async def _correlation_id(request: Request, call_next):
    return await correlation_id_middleware(request, call_next)


@app.middleware("http")
async def api_auth_middleware(request: Request, call_next):
    """
    Optionally enforce API key auth for non-public endpoints.
    """
    if request.method == "OPTIONS" or _should_skip_auth(request.url.path):
        return await call_next(request)

    if not _auth_required():
        return await call_next(request)

    settings = get_settings()
    expected_key = (settings.api_auth_key or "").strip()
    if not expected_key:
        return JSONResponse(
            status_code=503,
            content={"detail": "API auth is enabled but STOCKSBOT_API_KEY is not configured"},
        )

    provided_key = _extract_api_key(request)
    if not provided_key or not secrets.compare_digest(provided_key, expected_key):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    return await call_next(request)


@app.middleware("http")
async def security_logging_middleware(request: Request, call_next):
    """
    Log write operations with redacted payloads to prevent secret leakage.
    """
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        try:
            query_payload = dict(request.query_params.items())
            logger.info("HTTP %s %s query=%s", request.method, request.url.path, _redact_payload(query_payload))
        except (TypeError, ValueError):
            logger.info("HTTP %s %s query=<unavailable>", request.method, request.url.path)
    response: Response = await call_next(request)
    return response


# ── Shutdown rejection middleware ────────────────────────────────────────────
@app.middleware("http")
async def shutdown_rejection_middleware(request: Request, call_next):
    """Reject new write requests during graceful shutdown."""
    if _is_shutting_down() and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        # Allow health checks and status during shutdown
        if request.url.path not in {"/", "/status"}:
            return JSONResponse(
                status_code=503,
                content={"detail": "Server is shutting down. Please retry shortly."},
            )
    return await call_next(request)


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "StocksBot API"}


@app.get("/status")
async def status():
    """
    Production health check endpoint.
    Reports real subsystem status: database, broker, runner, optimizer, scheduler.
    """
    return build_health_response()


# ── Frontend Error Reporting ─────────────────────────────────────────────────
from pydantic import BaseModel, Field
from typing import Optional


class FrontendErrorReport(BaseModel):
    """Frontend error report payload."""
    error: str = Field(..., description="Error message", min_length=1, max_length=2000)
    component: Optional[str] = Field(None, description="Component name", max_length=200)
    stack: Optional[str] = Field(None, description="Stack trace", max_length=5000)
    url: Optional[str] = Field(None, description="Page URL", max_length=500)
    user_agent: Optional[str] = Field(None, description="Browser user agent", max_length=500)


@app.post("/errors/frontend")
async def report_frontend_error(report: FrontendErrorReport):
    """
    Receive and log frontend error reports.
    Provides a structured way to capture UI crashes.
    """
    logger.error(
        "Frontend error: component=%s error=%s url=%s",
        report.component or "unknown",
        report.error[:500],
        report.url or "unknown",
    )
    if report.stack:
        logger.debug("Frontend stack trace: %s", report.stack[:2000])
    return {"received": True}


# Include API routes
app.include_router(api_router)


if __name__ == "__main__":
    multiprocessing.freeze_support()

    # Detect if running as a PyInstaller frozen binary
    is_frozen = getattr(sys, "frozen", False)

    if is_frozen:
        # Frozen binary: pass app object directly, disable reload
        logger.info("Backend bootstrap: frozen binary mode (reload disabled)")
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=8000,
            reload=False,
        )
    else:
        reload_enabled = _resolve_backend_reload_enabled()
        logger.info("Backend bootstrap: uvicorn reload=%s", reload_enabled)
        uvicorn.run(
            "app:app",
            host="127.0.0.1",
            port=8000,
            reload=reload_enabled,
        )
