"""
StocksBot FastAPI Backend
Main application entry point for the sidecar backend.
"""
import secrets
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
import logging
import uvicorn

from api.routes import (
    router as api_router,
    start_summary_scheduler,
    stop_summary_scheduler,
)
from config.settings import get_settings
from storage.database import init_db

logger = logging.getLogger(__name__)
SENSITIVE_KEYS = {"api_key", "secret_key", "password", "token", "authorization"}
AUTH_SKIP_PATHS = {
    "/",
    "/status",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Manage background service lifecycle."""
    try:
        init_db()
    except (RuntimeError, ValueError, TypeError):
        logger.exception("Failed to initialize database schema")
        raise
    try:
        started = start_summary_scheduler()
        if started:
            logger.info("Summary notification scheduler started")
    except (RuntimeError, ValueError, TypeError):
        logger.exception("Failed to start summary notification scheduler")
    try:
        yield
    finally:
        try:
            stopped = stop_summary_scheduler()
            if stopped:
                logger.info("Summary notification scheduler stopped")
        except (RuntimeError, ValueError, TypeError):
            logger.exception("Failed to stop summary notification scheduler")


app = FastAPI(
    title="StocksBot API",
    description="Cross-platform StocksBot backend service",
    version="0.1.0",
    lifespan=_lifespan,
)

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


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "StocksBot API"}


@app.get("/status")
async def status():
    """
    Health check endpoint.
    Returns the status of the backend service.
    """
    return {
        "status": "running",
        "service": "StocksBot Backend",
        "version": "0.1.0"
    }


# Include API routes
app.include_router(api_router)


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )
