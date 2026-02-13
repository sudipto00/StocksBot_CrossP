"""
StocksBot FastAPI Backend
Main application entry point for the sidecar backend.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
import json
import logging
import uvicorn

from api.routes import router as api_router

logger = logging.getLogger(__name__)
SENSITIVE_KEYS = {"api_key", "secret_key", "password", "token", "authorization"}

app = FastAPI(
    title="StocksBot API",
    description="Cross-platform StocksBot backend service",
    version="0.1.0"
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


@app.middleware("http")
async def security_logging_middleware(request: Request, call_next):
    """
    Log write operations with redacted payloads to prevent secret leakage.
    """
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        try:
            query_payload = dict(request.query_params.items())
            logger.info("HTTP %s %s query=%s", request.method, request.url.path, _redact_payload(query_payload))
        except Exception:
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
