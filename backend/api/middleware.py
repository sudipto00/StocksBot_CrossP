"""
Production middleware for StocksBot API.

Provides:
- Request correlation IDs for log tracing
- Structured JSON logging
- Rate limiting per endpoint
- Request/response timing
"""
import logging
import time
import uuid
from contextvars import ContextVar
from starlette.requests import Request
from starlette.responses import Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# ── Context var for correlation ID (accessible from any coroutine/thread) ────
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """Get the current request correlation ID."""
    return request_id_ctx.get("")


# ── Rate Limiter ─────────────────────────────────────────────────────────────
# Uses in-memory storage (suitable for single-process desktop app).
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["120/minute"],
    storage_uri="memory://",
)


def rate_limit_exceeded_handler(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Custom handler for rate limit exceeded errors."""
    return JSONResponse(
        status_code=429,
        content={
            "detail": f"Rate limit exceeded: {exc.detail}",
            "retry_after": str(getattr(exc, "retry_after", 60)),
        },
    )


# ── Correlation ID + Timing Middleware ───────────────────────────────────────
async def correlation_id_middleware(request: Request, call_next) -> Response:
    """
    Attach a unique correlation ID to every request.
    - Sets X-Request-ID response header
    - Populates request_id_ctx for structured logging
    - Logs request timing
    """
    rid = request.headers.get("x-request-id", "").strip()
    if not rid:
        rid = uuid.uuid4().hex[:16]
    token = request_id_ctx.set(rid)
    start = time.monotonic()
    try:
        response: Response = await call_next(request)
        elapsed_ms = (time.monotonic() - start) * 1000
        response.headers["X-Request-ID"] = rid
        # Log at DEBUG for GETs, INFO for writes
        log_level = logging.DEBUG if request.method == "GET" else logging.INFO
        logger.log(
            log_level,
            "req=%s method=%s path=%s status=%d duration_ms=%.1f",
            rid,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response
    except Exception:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.exception(
            "req=%s method=%s path=%s duration_ms=%.1f unhandled_exception",
            rid,
            request.method,
            request.url.path,
            elapsed_ms,
        )
        raise
    finally:
        request_id_ctx.reset(token)


# ── Structured JSON Log Formatter ────────────────────────────────────────────
class StructuredFormatter(logging.Formatter):
    """
    JSON-like structured log formatter that includes correlation ID.
    Falls back to human-readable format when JSON import unavailable.
    """

    def format(self, record: logging.LogRecord) -> str:
        import json as _json

        rid = request_id_ctx.get("")
        payload = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if rid:
            payload["request_id"] = rid
        if record.exc_info and record.exc_info[1]:
            payload["exception"] = self.formatException(record.exc_info)
        return _json.dumps(payload, default=str)


def configure_structured_logging(log_level: str = "INFO") -> None:
    """
    Reconfigure root logger to use structured JSON formatting.
    Preserves existing file handlers but upgrades their formatter.
    """
    root = logging.getLogger()
    level = getattr(logging, log_level.upper(), logging.INFO)
    root.setLevel(level)

    formatter = StructuredFormatter()
    for handler in root.handlers:
        handler.setFormatter(formatter)

    # Add console handler if none exists
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root.handlers):
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(formatter)
        root.addHandler(console)
