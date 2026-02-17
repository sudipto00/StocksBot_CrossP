"""
API Routes.
Defines all REST API endpoints for StocksBot.
"""
from datetime import datetime, timedelta, timezone
import json
import math
import logging
import os
import re
import secrets
import threading
import time
import asyncio
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, Query, Header, WebSocket, WebSocketDisconnect
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from storage.database import SessionLocal, get_db
from storage.service import StorageService
from storage.models import AuditLog as DBAuditLog, Trade as DBTrade
from services.broker import BrokerInterface, PaperBroker
from services.order_execution import (
    OrderExecutionService,
    OrderValidationError,
    BrokerError,
    set_global_kill_switch,
    get_global_kill_switch,
    set_global_trading_enabled,
)
from config.settings import get_settings, has_alpaca_credentials
from services.logging_service import configure_file_logging, cleanup_old_files
from services.notification_delivery import NotificationDeliveryService
from services.budget_tracker import get_budget_tracker
from config.risk_profiles import get_all_profiles

from .models import (
    StatusResponse,
    ConfigResponse,
    ConfigUpdateRequest,
    PositionsResponse,
    Position,
    PositionSide,
    OrdersResponse,
    Order,
    OrderRequest,
    OrderSide,
    OrderType,
    OrderStatus,
    NotificationRequest,
    NotificationResponse,
    NotificationSeverity,
    SummaryNotificationPreferencesRequest,
    SummaryNotificationPreferencesResponse,
    SummaryNotificationFrequency,
    SummaryNotificationChannel,
    BrokerCredentialsRequest,
    BrokerCredentialsStatusResponse,
    BrokerAccountResponse,
    # Strategy models
    Strategy,
    StrategyStatus,
    StrategyCreateRequest,
    StrategyUpdateRequest,
    StrategiesResponse,
    # Audit models
    AuditLog,
    AuditEventType,
    AuditLogsResponse,
    TradeHistoryItem,
    TradeHistoryResponse,
    # Runner models
    RunnerStatusResponse,
    RunnerActionResponse,
    RunnerStartRequest,
    WebSocketAuthTicketResponse,
    # Strategy configuration models
    StrategyConfigResponse,
    StrategyConfigUpdateRequest,
    StrategyMetricsResponse,
    BacktestRequest,
    BacktestResponse,
    ParameterTuneRequest,
    ParameterTuneResponse,
    StrategyOptimizationRequest,
    StrategyOptimizationResponse,
    StrategyOptimizationCandidate,
    StrategyOptimizationWalkForwardReport,
    StrategyOptimizationJobStartResponse,
    StrategyOptimizationJobStatusResponse,
    StrategyOptimizationJobCancelResponse,
    StrategyParameter,
    ScreenerPreset,
    AssetType,
    ScreenerMode,
    PresetUniverseMode,
    StockPreset,
    EtfPreset,
    TradingPreferencesResponse,
)
from .runner_manager import runner_manager
from services.strategy_analytics import StrategyAnalyticsService
from services.strategy_optimizer import (
    StrategyOptimizerService,
    OptimizationContext,
    OptimizationCancelledError,
)
from services.market_screener import MarketScreener
from config.strategy_config import get_default_parameters

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# Broker Initialization
# ============================================================================

_broker_instance: Optional[BrokerInterface] = None
_runtime_broker_credentials = {
    "paper": {"api_key": None, "secret_key": None},
    "live": {"api_key": None, "secret_key": None},
}
_state_lock = threading.RLock()


def _set_config_snapshot(cfg: ConfigResponse) -> None:
    """Atomically replace runtime config snapshot."""
    global _config
    with _state_lock:
        _config = cfg.model_copy(deep=True)


def _get_config_snapshot() -> ConfigResponse:
    """Read a stable runtime config snapshot."""
    with _state_lock:
        return _config.model_copy(deep=True)


def _get_runtime_credentials(mode: str) -> Dict[str, Optional[str]]:
    """Read runtime broker credentials for a mode under lock."""
    with _state_lock:
        creds = _runtime_broker_credentials.get(mode, {})
        return {
            "api_key": creds.get("api_key"),
            "secret_key": creds.get("secret_key"),
        }


def _set_runtime_credentials(mode: str, api_key: str, secret_key: str) -> None:
    """Store runtime broker credentials for a mode under lock."""
    with _state_lock:
        _runtime_broker_credentials[mode]["api_key"] = api_key
        _runtime_broker_credentials[mode]["secret_key"] = secret_key
    with _market_screener_instances_lock:
        _market_screener_instances.clear()
    with _preference_recommendation_cache_lock:
        _preference_recommendation_cache.clear()


def _resolve_alpaca_credentials_for_mode(mode: str) -> Optional[Dict[str, str]]:
    """Resolve runtime-keychain credentials first, then environment credentials."""
    runtime_creds = _get_runtime_credentials(mode)
    runtime_api_key = (runtime_creds.get("api_key") or "").strip()
    runtime_secret_key = (runtime_creds.get("secret_key") or "").strip()
    if runtime_api_key and runtime_secret_key:
        return {"api_key": runtime_api_key, "secret_key": runtime_secret_key}
    if has_alpaca_credentials():
        settings = get_settings()
        env_api_key = (settings.alpaca_api_key or "").strip()
        env_secret_key = (settings.alpaca_secret_key or "").strip()
        if env_api_key and env_secret_key:
            return {"api_key": env_api_key, "secret_key": env_secret_key}
    return None


def _invalidate_broker_instance() -> None:
    """Invalidate cached broker instance and disconnect previous instance safely."""
    global _broker_instance
    stale_broker: Optional[BrokerInterface] = None
    with _state_lock:
        stale_broker = _broker_instance
        _broker_instance = None
    with _market_screener_instances_lock:
        _market_screener_instances.clear()
    with _preference_recommendation_cache_lock:
        _preference_recommendation_cache.clear()
    if stale_broker is not None:
        try:
            stale_broker.disconnect()
        except RuntimeError:
            pass


def get_broker() -> BrokerInterface:
    """
    Get or create broker instance.
    
    Returns:
        Configured broker instance (Paper or Alpaca)
    """
    global _broker_instance, _config
    with _state_lock:
        if _broker_instance is not None:
            return _broker_instance

        config = _config.model_copy(deep=True)
        mode = "paper" if config.paper_trading else "live"
        broker_preference = str(config.broker or "paper").strip().lower()
        if broker_preference not in {"paper", "alpaca"}:
            broker_preference = "paper"

        if broker_preference == "alpaca":
            creds = _resolve_alpaca_credentials_for_mode(mode)
            if not creds:
                raise RuntimeError(
                    f"Broker is set to alpaca ({mode}) but no Alpaca credentials are loaded. "
                    "Load keys from Keychain in Settings."
                )
            from integrations.alpaca_broker import AlpacaBroker
            broker = AlpacaBroker(
                api_key=creds["api_key"],
                secret_key=creds["secret_key"],
                paper=config.paper_trading,
            )
            broker_name = "alpaca"
        else:
            broker = PaperBroker(simulate_market_hours=_paper_market_hours_enabled_for_runtime())
            broker_name = "paper"

        if not broker.connect():
            raise RuntimeError("Failed to connect to broker")
        _broker_instance = broker
        _config = _config.model_copy(update={"broker": broker_name})
        return _broker_instance


def get_order_execution_service(
    db: Session = Depends(get_db)
) -> OrderExecutionService:
    """
    Get order execution service with broker and storage.
    
    Args:
        db: Database session
        
    Returns:
        OrderExecutionService instance
    """
    storage = StorageService(db)
    set_global_kill_switch(_load_kill_switch(storage))
    
    # Get config for risk limits
    config = _load_runtime_config(storage)
    _set_config_snapshot(config)
    set_global_trading_enabled(bool(config.trading_enabled))
    if config.trading_enabled:
        broker = get_broker()
    else:
        # Use local paper broker while trading is disabled to avoid credential-gated failures.
        broker = PaperBroker(simulate_market_hours=_paper_market_hours_enabled_for_runtime())
        broker.connect()
    
    # Keep budget checks opt-in at endpoint level to avoid global-state bleed
    # across tests and long-running UI sessions.
    enable_budget = False

    max_position_size, risk_limit_daily = _balance_adjusted_limits(
        broker=broker,
        requested_max_position_size=config.max_position_size,
        requested_risk_limit_daily=config.risk_limit_daily,
    )
    
    return OrderExecutionService(
        broker=broker,
        storage=storage,
        max_position_size=max_position_size,
        risk_limit_daily=risk_limit_daily,
        enable_budget_tracking=enable_budget
    )


# ============================================================================
# Configuration Endpoints
# ============================================================================

# In-memory config store (TODO: Replace with persistent storage)
_config = ConfigResponse(
    environment="development",
    trading_enabled=False,
    paper_trading=True,
    max_position_size=10000.0,
    risk_limit_daily=500.0,
    tick_interval_seconds=60.0,
    streaming_enabled=False,
    strict_alpaca_data=True,
    log_directory="./logs",
    audit_export_directory="./audit_exports",
    log_retention_days=30,
    audit_retention_days=90,
    broker="paper",
)
set_global_trading_enabled(bool(_config.trading_enabled))
configure_file_logging(_config.log_directory)
_last_housekeeping_run: Optional[datetime] = None
_CONFIG_KEY = "runtime_config"
_KILL_SWITCH_KEY = "safety_kill_switch"
_BROKER_SYNC_KEY = "last_broker_sync_at"
_idempotency_cache: Dict[str, Dict[str, Any]] = {}
_idempotency_lock = threading.Lock()
_last_broker_sync_at: Optional[str] = None
_ws_auth_tickets: Dict[str, float] = {}
_ws_auth_ticket_lock = threading.Lock()
_WS_AUTH_TICKET_TTL_SECONDS = 90
_chart_points_cache: Dict[str, Dict[str, Any]] = {}
_chart_points_cache_lock = threading.Lock()
_CHART_POINTS_CACHE_TTL_SECONDS = 60
_broker_account_cache: Optional[Dict[str, Any]] = None
_broker_account_cache_lock = threading.Lock()
_BROKER_ACCOUNT_CACHE_TTL_SECONDS = 8
_market_screener_instances: Dict[str, MarketScreener] = {}
_market_screener_instances_lock = threading.Lock()
_preference_recommendation_cache: Dict[str, Dict[str, Any]] = {}
_preference_recommendation_cache_lock = threading.Lock()
_PREFERENCE_RECOMMENDATION_CACHE_TTL_SECONDS = 10
_optimizer_jobs: Dict[str, Dict[str, Any]] = {}
_optimizer_jobs_lock = threading.Lock()
_OPTIMIZER_MAX_JOB_HISTORY = 40

_SUMMARY_NOTIFICATION_PREFERENCES_KEY = "summary_notification_preferences"
_SUMMARY_NOTIFICATION_SCHEDULE_STATE_KEY = "summary_notification_schedule_state"
_summary_notification_preferences = SummaryNotificationPreferencesResponse(
    enabled=False,
    frequency=SummaryNotificationFrequency.DAILY,
    channel=SummaryNotificationChannel.EMAIL,
    recipient="",
)
_summary_scheduler_thread: Optional[threading.Thread] = None
_summary_scheduler_stop_event = threading.Event()
_summary_scheduler_lock = threading.Lock()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")


def _is_api_auth_required() -> bool:
    settings = get_settings()
    if settings.api_auth_enabled:
        return True
    return bool(settings.api_auth_key and settings.api_auth_key.strip())


def _extract_api_key_from_headers(headers: Any) -> str:
    direct = (headers.get("x-api-key") or "").strip()
    if direct:
        return direct
    auth_header = (headers.get("authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return ""


def _extract_api_key_from_websocket(websocket: WebSocket) -> str:
    """Extract API key for websocket auth from headers only."""
    return _extract_api_key_from_headers(websocket.headers)


def _is_api_key_valid(provided_key: str) -> bool:
    settings = get_settings()
    expected = (settings.api_auth_key or "").strip()
    if not expected:
        return False
    return bool(provided_key) and secrets.compare_digest(provided_key, expected)


def _idempotency_cache_get(endpoint: str, key: Optional[str]) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    cache_key = f"{endpoint}:{key.strip()}"
    now = time.time()
    with _idempotency_lock:
        entry = _idempotency_cache.get(cache_key)
        if not entry:
            return None
        if entry["expires_at"] < now:
            _idempotency_cache.pop(cache_key, None)
            return None
        return entry["payload"]


def _idempotency_cache_set(endpoint: str, key: Optional[str], payload: Dict[str, Any], ttl_seconds: int = 300) -> None:
    if not key:
        return
    cache_key = f"{endpoint}:{key.strip()}"
    with _idempotency_lock:
        _idempotency_cache[cache_key] = {
            "payload": payload,
            "expires_at": time.time() + ttl_seconds,
        }


def _chart_cache_get(cache_key: str) -> Optional[List[Dict[str, Any]]]:
    """Read cached screener chart points for a key when still fresh."""
    now_ts = time.time()
    with _chart_points_cache_lock:
        entry = _chart_points_cache.get(cache_key)
        if not entry:
            return None
        if float(entry.get("expires_at", 0.0)) <= now_ts:
            _chart_points_cache.pop(cache_key, None)
            return None
        points = entry.get("points", [])
    if not isinstance(points, list):
        return None
    return [dict(point) for point in points if isinstance(point, dict)]


def _chart_cache_set(cache_key: str, points: List[Dict[str, Any]], ttl_seconds: int = _CHART_POINTS_CACHE_TTL_SECONDS) -> None:
    """Store screener chart points in a short-lived in-memory cache."""
    ttl = max(5, int(ttl_seconds))
    normalized_points = [dict(point) for point in points if isinstance(point, dict)]
    with _chart_points_cache_lock:
        _chart_points_cache[cache_key] = {
            "points": normalized_points,
            "expires_at": time.time() + ttl,
        }


def _broker_account_cache_get(cache_key: str) -> Optional[Dict[str, Any]]:
    """Return cached broker-account payload when still fresh."""
    now_ts = time.time()
    with _broker_account_cache_lock:
        entry = _broker_account_cache
        if not entry:
            return None
        if str(entry.get("cache_key")) != str(cache_key):
            return None
        if float(entry.get("expires_at", 0.0)) <= now_ts:
            return None
        payload = entry.get("payload")
    return dict(payload) if isinstance(payload, dict) else None


def _broker_account_cache_set(cache_key: str, payload: Dict[str, Any], ttl_seconds: int = _BROKER_ACCOUNT_CACHE_TTL_SECONDS) -> None:
    """Store broker-account payload in short-lived memory cache."""
    ttl = max(2, int(ttl_seconds))
    with _broker_account_cache_lock:
        global _broker_account_cache
        _broker_account_cache = {
            "cache_key": str(cache_key),
            "payload": dict(payload),
            "expires_at": time.time() + ttl,
        }


def _preference_recommendation_cache_get(cache_key: str) -> Optional[Dict[str, Any]]:
    """Read cached recommendation payload when still fresh."""
    now_ts = time.time()
    with _preference_recommendation_cache_lock:
        entry = _preference_recommendation_cache.get(cache_key)
        if not entry:
            return None
        if float(entry.get("expires_at", 0.0)) <= now_ts:
            _preference_recommendation_cache.pop(cache_key, None)
            return None
        payload = entry.get("payload")
    return dict(payload) if isinstance(payload, dict) else None


def _preference_recommendation_cache_set(
    cache_key: str,
    payload: Dict[str, Any],
    ttl_seconds: int = _PREFERENCE_RECOMMENDATION_CACHE_TTL_SECONDS,
) -> None:
    """Store recommendation payload in short-lived memory cache."""
    ttl = max(2, int(ttl_seconds))
    with _preference_recommendation_cache_lock:
        _preference_recommendation_cache[cache_key] = {
            "payload": dict(payload),
            "expires_at": time.time() + ttl,
        }


def _optimizer_prune_jobs_locked() -> None:
    """Keep optimizer in-memory job history bounded."""
    if len(_optimizer_jobs) <= _OPTIMIZER_MAX_JOB_HISTORY:
        return
    completed = [
        (job_id, row)
        for job_id, row in _optimizer_jobs.items()
        if str(row.get("status")) in {"completed", "failed", "canceled"}
    ]
    completed.sort(
        key=lambda item: str(item[1].get("completed_at") or item[1].get("created_at") or "")
    )
    while len(_optimizer_jobs) > _OPTIMIZER_MAX_JOB_HISTORY and completed:
        job_id, _ = completed.pop(0)
        _optimizer_jobs.pop(job_id, None)


def _optimizer_create_job(strategy_id: str, request_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create and register a queued optimizer job."""
    created_at = datetime.now(timezone.utc).isoformat()
    job_id = secrets.token_hex(12)
    row = {
        "job_id": job_id,
        "strategy_id": strategy_id,
        "status": "queued",
        "progress_pct": 0.0,
        "completed_iterations": 0,
        "total_iterations": 0,
        "elapsed_seconds": 0.0,
        "eta_seconds": None,
        "avg_seconds_per_iteration": None,
        "message": "Queued",
        "cancel_requested": False,
        "error": None,
        "created_at": created_at,
        "started_at": None,
        "completed_at": None,
        "request": dict(request_payload),
        "result": None,
    }
    with _optimizer_jobs_lock:
        _optimizer_jobs[job_id] = row
        _optimizer_prune_jobs_locked()
    return dict(row)


def _optimizer_get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Get optimizer job snapshot by ID."""
    with _optimizer_jobs_lock:
        row = _optimizer_jobs.get(job_id)
        return dict(row) if row else None


def _optimizer_update_job(job_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Atomically update optimizer job fields and return snapshot."""
    with _optimizer_jobs_lock:
        row = _optimizer_jobs.get(job_id)
        if row is None:
            return None
        row.update(updates)
        return dict(row)


def _optimizer_progress_snapshot(row: Dict[str, Any]) -> StrategyOptimizationJobStatusResponse:
    """Normalize optimizer in-memory row to API response model."""
    result_payload = row.get("result")
    result_model: Optional[StrategyOptimizationResponse] = None
    if isinstance(result_payload, StrategyOptimizationResponse):
        result_model = result_payload
    elif isinstance(result_payload, dict):
        try:
            result_model = StrategyOptimizationResponse(**result_payload)
        except Exception:
            result_model = None
    return StrategyOptimizationJobStatusResponse(
        job_id=str(row.get("job_id")),
        strategy_id=str(row.get("strategy_id")),
        status=str(row.get("status") or "failed"),  # type: ignore[arg-type]
        progress_pct=float(row.get("progress_pct") or 0.0),
        completed_iterations=int(row.get("completed_iterations") or 0),
        total_iterations=int(row.get("total_iterations") or 0),
        elapsed_seconds=float(row.get("elapsed_seconds") or 0.0),
        eta_seconds=(
            float(row["eta_seconds"])
            if isinstance(row.get("eta_seconds"), (int, float))
            else None
        ),
        avg_seconds_per_iteration=(
            float(row["avg_seconds_per_iteration"])
            if isinstance(row.get("avg_seconds_per_iteration"), (int, float))
            else None
        ),
        message=str(row.get("message") or ""),
        cancel_requested=bool(row.get("cancel_requested")),
        error=str(row["error"]) if row.get("error") else None,
        created_at=str(row.get("created_at") or ""),
        started_at=str(row["started_at"]) if row.get("started_at") else None,
        completed_at=str(row["completed_at"]) if row.get("completed_at") else None,
        result=result_model,
    )


def _prune_ws_auth_tickets_locked(now_ts: float) -> None:
    """Prune expired websocket auth tickets under caller-held lock."""
    expired = [token for token, expires_at in _ws_auth_tickets.items() if expires_at <= now_ts]
    for token in expired:
        _ws_auth_tickets.pop(token, None)


def _issue_ws_auth_ticket(ttl_seconds: int = _WS_AUTH_TICKET_TTL_SECONDS) -> tuple[str, datetime]:
    """Issue a short-lived one-time websocket auth ticket."""
    now_ts = time.time()
    ttl = max(5, int(ttl_seconds))
    expires_at_ts = now_ts + ttl
    ticket = secrets.token_urlsafe(32)
    with _ws_auth_ticket_lock:
        _prune_ws_auth_tickets_locked(now_ts)
        _ws_auth_tickets[ticket] = expires_at_ts
    return ticket, datetime.fromtimestamp(expires_at_ts, tz=timezone.utc)


def _consume_ws_auth_ticket(ticket: str) -> bool:
    """Atomically validate and consume a websocket auth ticket."""
    normalized = str(ticket or "").strip()
    if not normalized:
        return False
    now_ts = time.time()
    with _ws_auth_ticket_lock:
        _prune_ws_auth_tickets_locked(now_ts)
        expires_at_ts = _ws_auth_tickets.pop(normalized, None)
    if expires_at_ts is None:
        return False
    return expires_at_ts > now_ts


def _load_runtime_config(storage: StorageService) -> ConfigResponse:
    """Load runtime config from DB config store or fallback to defaults."""
    entry = storage.config.get_by_key(_CONFIG_KEY)
    if not entry or not entry.value:
        return _get_config_snapshot()
    try:
        raw = json.loads(entry.value)
        return ConfigResponse(**raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _get_config_snapshot()


def _save_runtime_config(storage: StorageService, cfg: ConfigResponse) -> None:
    """Persist runtime config into DB config store."""
    storage.config.upsert(
        key=_CONFIG_KEY,
        value=json.dumps(cfg.model_dump()),
        value_type="json",
        description="Runtime backend config persisted for restart consistency",
    )


def _load_kill_switch(storage: StorageService) -> bool:
    entry = storage.config.get_by_key(_KILL_SWITCH_KEY)
    if not entry:
        return get_global_kill_switch()
    return str(entry.value).strip().lower() == "true"


def _save_kill_switch(storage: StorageService, active: bool) -> None:
    storage.config.upsert(
        key=_KILL_SWITCH_KEY,
        value=str(bool(active)).lower(),
        value_type="bool",
        description="Global trading kill switch",
    )


def _set_last_broker_sync(ts_iso: Optional[str]) -> None:
    global _last_broker_sync_at
    with _state_lock:
        _last_broker_sync_at = ts_iso


def _get_last_broker_sync() -> Optional[str]:
    with _state_lock:
        return _last_broker_sync_at


def _ensure_utc_datetime(value: Optional[datetime]) -> Optional[datetime]:
    """Normalize datetimes to UTC for stable API serialization."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _balance_adjusted_limits(
    broker: BrokerInterface,
    requested_max_position_size: float,
    requested_risk_limit_daily: float,
) -> tuple[float, float]:
    """Clamp configured guardrails against live account balance and buying power."""
    try:
        account = broker.get_account_info()
        equity = float(account.get("equity", account.get("portfolio_value", 0.0)) or 0.0)
        buying_power = float(account.get("buying_power", 0.0) or 0.0)
    except (RuntimeError, ValueError, TypeError, KeyError):
        return requested_max_position_size, requested_risk_limit_daily

    adjusted_max_position_size = float(requested_max_position_size)
    adjusted_risk_limit_daily = float(requested_risk_limit_daily)
    if buying_power > 0:
        adjusted_max_position_size = min(adjusted_max_position_size, buying_power)
    if equity > 0:
        adjusted_max_position_size = min(adjusted_max_position_size, max(100.0, equity * 0.25))
        adjusted_risk_limit_daily = min(adjusted_risk_limit_daily, max(50.0, equity * 0.05))

    return max(1.0, adjusted_max_position_size), max(1.0, adjusted_risk_limit_daily)


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Best-effort float parsing."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _load_account_snapshot(broker: Optional[BrokerInterface]) -> Dict[str, float]:
    """Load account equity/buying-power snapshot without raising."""
    if broker is None:
        return {"equity": 0.0, "buying_power": 0.0, "cash": 0.0}
    try:
        info = broker.get_account_info()
    except (RuntimeError, ValueError, TypeError, KeyError):
        return {"equity": 0.0, "buying_power": 0.0, "cash": 0.0}
    return {
        "equity": _safe_float(info.get("equity", info.get("portfolio_value", 0.0)), 0.0),
        "buying_power": _safe_float(info.get("buying_power", 0.0), 0.0),
        "cash": _safe_float(info.get("cash", 0.0), 0.0),
    }


def _load_holdings_snapshot(storage: StorageService, broker: Optional[BrokerInterface]) -> List[Dict[str, Any]]:
    """
    Load current holdings with market values, preferring broker truth and falling back to local positions.
    """
    holdings: List[Dict[str, Any]] = []
    if broker is not None:
        try:
            broker_positions = broker.get_positions()
            for raw in broker_positions:
                symbol = str(raw.get("symbol", "")).strip().upper()
                if not symbol:
                    continue
                quantity = abs(_safe_float(raw.get("quantity", 0.0), 0.0))
                current_price = _safe_float(raw.get("current_price", raw.get("price", 0.0)), 0.0)
                avg_entry_price = _safe_float(raw.get("avg_entry_price", 0.0), 0.0)
                market_value = _safe_float(raw.get("market_value", 0.0), 0.0)
                if market_value <= 0 and quantity > 0:
                    market_value = quantity * (current_price if current_price > 0 else avg_entry_price)
                holdings.append({
                    "symbol": symbol,
                    "quantity": quantity,
                    "current_price": current_price,
                    "avg_entry_price": avg_entry_price,
                    "market_value": max(0.0, market_value),
                    "asset_type": str(raw.get("asset_type", "")).lower(),
                })
            if holdings:
                return holdings
        except (RuntimeError, ValueError, TypeError, KeyError):
            holdings = []

    # Fallback to local stored positions.
    local_positions = storage.get_open_positions()
    for position in local_positions:
        symbol = str(position.symbol).strip().upper()
        quantity = abs(_safe_float(position.quantity, 0.0))
        avg_entry_price = _safe_float(position.avg_entry_price, 0.0)
        cost_basis = _safe_float(position.cost_basis, 0.0)
        holdings.append({
            "symbol": symbol,
            "quantity": quantity,
            "current_price": avg_entry_price,
            "avg_entry_price": avg_entry_price,
            "market_value": max(0.0, cost_basis),
            "asset_type": "",
        })
    return holdings


def _paper_market_hours_enabled_for_runtime() -> bool:
    """
    Enable market-hours simulation in normal runtime, disable under pytest.
    Keeps tests deterministic and independent of wall-clock market session.
    """
    return "PYTEST_CURRENT_TEST" not in os.environ


def _collect_symbol_capabilities(
    broker: Optional[BrokerInterface],
    assets: List[Dict[str, Any]],
) -> Dict[str, Dict[str, bool]]:
    """Resolve tradable/fractionable capabilities for symbols in the candidate universe."""
    capabilities: Dict[str, Dict[str, bool]] = {}
    if broker is None:
        return capabilities
    for asset in assets:
        symbol = str(asset.get("symbol", "")).strip().upper()
        if not symbol or symbol in capabilities:
            continue
        raw: Dict[str, Any] = {}
        try:
            raw_caps = broker.get_symbol_capabilities(symbol)
            if isinstance(raw_caps, dict):
                raw = raw_caps
        except (RuntimeError, ValueError, TypeError, KeyError, AttributeError):
            raw = {}

        if "tradable" not in raw:
            try:
                raw["tradable"] = bool(broker.is_symbol_tradable(symbol))
            except (RuntimeError, ValueError, TypeError, KeyError, AttributeError):
                raw["tradable"] = True
        if "fractionable" not in raw:
            try:
                raw["fractionable"] = bool(broker.is_symbol_fractionable(symbol))
            except (RuntimeError, ValueError, TypeError, KeyError, AttributeError):
                raw["fractionable"] = True

        capabilities[symbol] = {
            "tradable": bool(raw.get("tradable", True)),
            "fractionable": bool(raw.get("fractionable", True)),
        }
    return capabilities


def _should_require_fractionable_symbols(
    asset_type: "AssetType",
    prefs: "TradingPreferencesResponse",
    account_snapshot: Dict[str, float],
) -> bool:
    """
    Determine when screener should strictly require fractional-ready symbols.

    Enforced for stock micro/small-budget workflows where fractional execution is
    the key way to keep a broad, affordable universe.
    """
    if asset_type != AssetType.STOCK:
        return False
    weekly_budget = _safe_float(prefs.weekly_budget, 200.0)
    buying_power = _safe_float(account_snapshot.get("buying_power", 0.0), 0.0)
    equity = _safe_float(account_snapshot.get("equity", 0.0), 0.0)
    return (
        prefs.stock_preset == StockPreset.MICRO_BUDGET
        or weekly_budget <= 300.0
        or buying_power <= 5_000.0
        or equity <= 20_000.0
    )


def _capture_portfolio_snapshot(storage: StorageService, broker: Optional[BrokerInterface]) -> Optional[Dict[str, float]]:
    """Persist one portfolio snapshot row and return normalized snapshot values."""
    if broker is None:
        return None

    def _snapshot_to_payload(snapshot_row: Any) -> Dict[str, float]:
        return {
            "equity": _safe_float(getattr(snapshot_row, "equity", 0.0), 0.0),
            "cash": _safe_float(getattr(snapshot_row, "cash", 0.0), 0.0),
            "buying_power": _safe_float(getattr(snapshot_row, "buying_power", 0.0), 0.0),
            "market_value": _safe_float(getattr(snapshot_row, "market_value", 0.0), 0.0),
            "unrealized_pnl": _safe_float(getattr(snapshot_row, "unrealized_pnl", 0.0), 0.0),
            "realized_pnl_total": _safe_float(getattr(snapshot_row, "realized_pnl_total", 0.0), 0.0),
            "open_positions": float(_safe_float(getattr(snapshot_row, "open_positions", 0.0), 0.0)),
        }

    now_utc = datetime.now(timezone.utc)
    latest = storage.get_latest_portfolio_snapshot()
    try:
        market_open = bool(broker.is_market_open())
    except (RuntimeError, ValueError, TypeError, KeyError):
        market_open = True

    # Keep equity curve stable off-hours by reusing the last persisted snapshot.
    if not market_open and latest is not None:
        return _snapshot_to_payload(latest)

    account_snapshot = _load_account_snapshot(broker)
    holdings_snapshot = _load_holdings_snapshot(storage, broker)
    market_value = sum(_safe_float(h.get("market_value", 0.0), 0.0) for h in holdings_snapshot)
    unrealized_pnl = 0.0
    for h in holdings_snapshot:
        qty = abs(_safe_float(h.get("quantity", 0.0), 0.0))
        current_price = _safe_float(h.get("current_price", 0.0), 0.0)
        avg_entry_price = _safe_float(h.get("avg_entry_price", 0.0), 0.0)
        row_market_value = _safe_float(h.get("market_value", qty * current_price), 0.0)
        unrealized_pnl += row_market_value - (qty * avg_entry_price)

    trades = storage.get_all_trades(limit=5000)
    realized_pnl_total = sum(_safe_float(trade.realized_pnl, 0.0) for trade in trades)

    # Avoid duplicate writes when repeated UI polling samples within a few seconds.
    if latest is not None and latest.timestamp is not None:
        latest_ts = _ensure_utc_datetime(latest.timestamp)
        if latest_ts is not None and (now_utc - latest_ts).total_seconds() < 5:
            if (
                abs(_safe_float(latest.equity, 0.0) - _safe_float(account_snapshot.get("equity", 0.0), 0.0)) < 1e-9
                and abs(_safe_float(latest.market_value, 0.0) - market_value) < 1e-9
                and abs(_safe_float(latest.realized_pnl_total, 0.0) - realized_pnl_total) < 1e-9
            ):
                return _snapshot_to_payload(latest)

    snapshot = storage.record_portfolio_snapshot(
        equity=_safe_float(account_snapshot.get("equity", 0.0), 0.0),
        cash=_safe_float(account_snapshot.get("cash", 0.0), 0.0),
        buying_power=_safe_float(account_snapshot.get("buying_power", 0.0), 0.0),
        market_value=market_value,
        unrealized_pnl=unrealized_pnl,
        realized_pnl_total=realized_pnl_total,
        open_positions=len(holdings_snapshot),
        timestamp=now_utc,
    )
    return _snapshot_to_payload(snapshot)


def _normalize_symbols(raw_symbols: List[str], max_symbols: int = 200) -> List[str]:
    """Normalize and validate a list of symbols."""
    normalized_symbols: List[str] = []
    seen = set()
    for raw_symbol in raw_symbols:
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            continue
        if not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", symbol):
            raise HTTPException(status_code=400, detail=f"Invalid symbol format: {raw_symbol}")
        if symbol not in seen:
            normalized_symbols.append(symbol)
            seen.add(symbol)
    if len(normalized_symbols) > max_symbols:
        raise HTTPException(status_code=400, detail=f"Symbol list cannot exceed {max_symbols} symbols")
    return normalized_symbols


def _execution_block_reason(symbol: str, broker: BrokerInterface) -> Optional[str]:
    """Return first blocking safety reason for execution, if any."""
    config = _get_config_snapshot()
    if not bool(config.trading_enabled):
        mode = "paper" if bool(config.paper_trading) else "live"
        return (
            "Trading is disabled in Settings. "
            f"{mode.title()} mode only selects the account mode; it does not enable execution."
        )
    if get_global_kill_switch():
        return "Trading is blocked: kill switch is active"
    if not broker.is_connected():
        return "Broker is not connected"
    if not broker.is_symbol_tradable(symbol):
        return f"Symbol {symbol} is not tradable"
    if not broker.is_market_open():
        return "Market is closed"
    return None


def _to_order_status(raw_status: Any) -> OrderStatus:
    """Normalize broker/storage order status to API status enum."""
    normalized = str(raw_status or "pending").strip().lower()
    mapping = {
        "pending": OrderStatus.PENDING,
        "open": OrderStatus.SUBMITTED,
        "submitted": OrderStatus.SUBMITTED,
        "accepted": OrderStatus.SUBMITTED,
        "new": OrderStatus.SUBMITTED,
        "filled": OrderStatus.FILLED,
        "partially_filled": OrderStatus.PARTIALLY_FILLED,
        "partial_fill": OrderStatus.PARTIALLY_FILLED,
        "canceled": OrderStatus.CANCELLED,
        "cancelled": OrderStatus.CANCELLED,
        "expired": OrderStatus.CANCELLED,
        "rejected": OrderStatus.REJECTED,
    }
    return mapping.get(normalized, OrderStatus.PENDING)


def _to_utc_datetime(value: Any) -> datetime:
    """Best-effort datetime parser for mixed DB/broker payloads."""
    if isinstance(value, datetime):
        return _ensure_utc_datetime(value) or datetime.now(timezone.utc)
    if isinstance(value, str):
        candidate = value.strip()
        if candidate:
            if candidate.endswith("Z"):
                candidate = f"{candidate[:-1]}+00:00"
            try:
                parsed = datetime.fromisoformat(candidate)
                return _ensure_utc_datetime(parsed) or datetime.now(timezone.utc)
            except ValueError:
                pass
    return datetime.now(timezone.utc)


def _to_order_side(raw_side: Any) -> OrderSide:
    normalized = str(raw_side or "").strip().lower()
    return OrderSide.SELL if normalized == "sell" else OrderSide.BUY


def _to_order_type(raw_type: Any) -> OrderType:
    normalized = str(raw_type or "").strip().lower()
    mapping = {
        "market": OrderType.MARKET,
        "limit": OrderType.LIMIT,
        "stop": OrderType.STOP,
        "stop_limit": OrderType.STOP_LIMIT,
        "stop-limit": OrderType.STOP_LIMIT,
    }
    return mapping.get(normalized, OrderType.MARKET)


def _api_order_from_storage_row(row: Any) -> Order:
    """Map DB order row to API model."""
    return Order(
        id=str(row.id),
        symbol=str(row.symbol).upper(),
        side=OrderSide(str(row.side.value).lower()),
        type=OrderType(str(row.type.value).lower()),
        quantity=float(row.quantity),
        price=float(row.price) if row.price is not None else None,
        status=_to_order_status(getattr(row.status, "value", row.status)),
        filled_quantity=float(row.filled_quantity or 0.0),
        avg_fill_price=float(row.avg_fill_price) if row.avg_fill_price is not None else None,
        created_at=_ensure_utc_datetime(row.created_at) or datetime.now(timezone.utc),
        updated_at=_ensure_utc_datetime(row.updated_at) or datetime.now(timezone.utc),
    )


def _api_order_from_broker_row(raw: Dict[str, Any]) -> Optional[Order]:
    """Map broker order payload to API model."""
    if not isinstance(raw, dict):
        return None
    order_id = str(raw.get("id", "")).strip()
    symbol = str(raw.get("symbol", "")).strip().upper()
    if not order_id or not symbol:
        return None
    created_at = _to_utc_datetime(raw.get("created_at"))
    updated_at = _to_utc_datetime(raw.get("updated_at") or raw.get("filled_at") or created_at)
    quantity = _safe_float(raw.get("quantity", 0.0), 0.0)
    if quantity <= 0:
        return None
    return Order(
        id=order_id,
        symbol=symbol,
        side=_to_order_side(raw.get("side")),
        type=_to_order_type(raw.get("type")),
        quantity=quantity,
        price=_safe_float(raw.get("price"), 0.0) if raw.get("price") is not None else None,
        status=_to_order_status(raw.get("status")),
        filled_quantity=max(0.0, _safe_float(raw.get("filled_quantity", 0.0), 0.0)),
        avg_fill_price=_safe_float(raw.get("avg_fill_price"), 0.0) if raw.get("avg_fill_price") is not None else None,
        created_at=created_at,
        updated_at=updated_at,
    )


def _load_summary_notification_preferences(storage: StorageService) -> SummaryNotificationPreferencesResponse:
    """Load summary notification preferences from DB config."""
    config_entry = storage.config.get_by_key(_SUMMARY_NOTIFICATION_PREFERENCES_KEY)
    if not config_entry:
        return _summary_notification_preferences
    try:
        return SummaryNotificationPreferencesResponse(**json.loads(config_entry.value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return _summary_notification_preferences


def _run_housekeeping(storage: StorageService, force: bool = False) -> Dict[str, int]:
    """Periodic cleanup for audit rows and retained files."""
    global _last_housekeeping_run
    now = datetime.now(timezone.utc)
    if not force and _last_housekeeping_run and (now - _last_housekeeping_run).total_seconds() < 3600:
        return {"audit_rows_deleted": 0, "log_files_deleted": 0, "audit_files_deleted": 0}
    _last_housekeeping_run = now
    config = _get_config_snapshot()
    audit_rows_deleted = storage.audit_logs.delete_old_logs(days=config.audit_retention_days)
    log_files_deleted = cleanup_old_files(config.log_directory, config.log_retention_days)
    audit_files_deleted = cleanup_old_files(config.audit_export_directory, config.audit_retention_days)
    return {
        "audit_rows_deleted": int(audit_rows_deleted),
        "log_files_deleted": int(log_files_deleted),
        "audit_files_deleted": int(audit_files_deleted),
    }


def _delete_all_files(directory: str) -> int:
    """Delete all files/symlinks in a directory (non-recursive)."""
    path = Path(directory).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        return 0
    deleted = 0
    for child in path.iterdir():
        try:
            if child.is_file() or child.is_symlink():
                child.unlink()
                deleted += 1
        except OSError:
            continue
    return deleted


def _run_reconciliation(storage: StorageService, broker: BrokerInterface) -> Dict[str, Any]:
    """Compare local open positions with broker positions and log discrepancies."""
    broker_positions = broker.get_positions()
    local_positions = storage.get_open_positions()
    broker_qty: Dict[str, float] = {}
    local_qty: Dict[str, float] = {}
    for row in broker_positions:
        sym = str(row.get("symbol", "")).upper()
        if not sym:
            continue
        broker_qty[sym] = broker_qty.get(sym, 0.0) + float(row.get("quantity", 0.0))
    for row in local_positions:
        sym = str(row.symbol).upper()
        local_qty[sym] = local_qty.get(sym, 0.0) + float(row.quantity or 0.0)

    symbols = sorted(set(broker_qty.keys()) | set(local_qty.keys()))
    discrepancies: List[Dict[str, Any]] = []
    for sym in symbols:
        bq = float(broker_qty.get(sym, 0.0))
        lq = float(local_qty.get(sym, 0.0))
        if abs(bq - lq) > 1e-6:
            discrepancies.append({"symbol": sym, "broker_quantity": bq, "local_quantity": lq})

    if discrepancies:
        storage.create_audit_log(
            event_type="error",
            description=f"Reconciliation found {len(discrepancies)} discrepancy(ies)",
            details={"source": "reconciliation", "discrepancies": discrepancies[:100]},
        )
    return {
        "checked_symbols": len(symbols),
        "discrepancy_count": len(discrepancies),
        "discrepancies": discrepancies,
        "reconciled_at": datetime.now(timezone.utc).isoformat(),
    }


def _save_summary_notification_preferences(
    storage: StorageService,
    preferences: SummaryNotificationPreferencesResponse,
) -> None:
    """Persist summary notification preferences to DB config."""
    storage.config.upsert(
        key=_SUMMARY_NOTIFICATION_PREFERENCES_KEY,
        value=json.dumps(preferences.model_dump()),
        value_type="json",
        description="Daily/weekly transaction summary notification preferences",
    )


def _load_summary_notification_schedule_state(storage: StorageService) -> Dict[str, Any]:
    """Load summary scheduler state from DB config."""
    entry = storage.config.get_by_key(_SUMMARY_NOTIFICATION_SCHEDULE_STATE_KEY)
    if not entry or not entry.value:
        return {}
    try:
        raw = json.loads(entry.value)
        return raw if isinstance(raw, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _save_summary_notification_schedule_state(storage: StorageService, state: Dict[str, Any]) -> None:
    """Persist summary scheduler state into DB config."""
    storage.config.upsert(
        key=_SUMMARY_NOTIFICATION_SCHEDULE_STATE_KEY,
        value=json.dumps(state),
        value_type="json",
        description="Summary notification scheduler checkpoint state",
    )


def _collect_summary_trade_stats(
    storage: StorageService,
    start: datetime,
    end: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Collect summary trade stats within [start, end) in UTC."""
    trades = storage.get_all_trades(limit=5000)
    scoped: List[DBTrade] = []
    for trade in trades:
        executed_at = _ensure_utc_datetime(trade.executed_at)
        if executed_at is None:
            continue
        if executed_at < start:
            continue
        if end is not None and executed_at >= end:
            continue
        scoped.append(trade)

    trade_count = len(scoped)
    gross_notional = sum(float(t.quantity or 0.0) * float(t.price or 0.0) for t in scoped)
    realized_pnl = sum(float(t.realized_pnl or 0.0) for t in scoped if t.realized_pnl is not None)
    return {
        "trade_count": trade_count,
        "gross_notional": gross_notional,
        "realized_pnl": realized_pnl,
    }


def _completed_summary_period_window(
    frequency: SummaryNotificationFrequency,
    now_utc: datetime,
) -> tuple[datetime, datetime, str]:
    """Get completed UTC summary window [start, end) and stable period identifier."""
    if frequency == SummaryNotificationFrequency.DAILY:
        end = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=1)
        period_id = start.date().isoformat()
        return start, end, period_id

    current_week_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now_utc.weekday())
    end = current_week_start
    start = end - timedelta(days=7)
    iso_week = start.isocalendar()
    period_id = f"{iso_week.year}-W{iso_week.week:02d}"
    return start, end, period_id


def _parse_utc_iso_timestamp(raw: Any) -> Optional[datetime]:
    """Parse an ISO timestamp string as UTC datetime when possible."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return _ensure_utc_datetime(parsed)


def _send_summary_with_stats(
    storage: StorageService,
    prefs: SummaryNotificationPreferencesResponse,
    stats: Dict[str, Any],
    subject: str,
    summary_body: str,
    source: str,
) -> NotificationResponse:
    """Deliver summary through configured channel and write audit logs."""
    trade_count = int(stats.get("trade_count", 0))
    gross_notional = float(stats.get("gross_notional", 0.0))
    realized_pnl = float(stats.get("realized_pnl", 0.0))
    try:
        delivery = NotificationDeliveryService()
        delivery_result = delivery.send_summary(
            channel=prefs.channel,
            recipient=prefs.recipient,
            subject=subject,
            body=summary_body,
        )
    except RuntimeError as exc:
        storage.create_audit_log(
            event_type="error",
            description=f"Summary notification failed ({prefs.channel.value})",
            details={
                "source": source,
                "recipient": prefs.recipient,
                "trade_count": trade_count,
                "gross_notional": gross_notional,
                "realized_pnl": realized_pnl,
                "error": str(exc),
            },
        )
        return NotificationResponse(
            success=False,
            message=f"Summary delivery failed: {exc}",
        )

    storage.create_audit_log(
        event_type="config_updated",
        description=f"Sent {prefs.frequency.value} {prefs.channel.value} summary notification",
        details={
            "source": source,
            "recipient": prefs.recipient,
            "trade_count": trade_count,
            "gross_notional": gross_notional,
            "realized_pnl": realized_pnl,
            "delivery": delivery_result,
        },
    )
    return NotificationResponse(
        success=True,
        message=f"{delivery_result}: {summary_body}",
    )


def _dispatch_scheduled_summary(
    storage: StorageService,
    now_utc: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Best-effort scheduler cycle for automatic daily/weekly summary delivery."""
    prefs = _load_summary_notification_preferences(storage)
    if not prefs.enabled:
        return {"status": "skipped", "reason": "disabled"}
    if not prefs.recipient:
        return {"status": "skipped", "reason": "missing_recipient"}

    now = _ensure_utc_datetime(now_utc) or datetime.now(timezone.utc)
    start, end, period_id = _completed_summary_period_window(prefs.frequency, now)
    if end <= start or now < end:
        return {"status": "skipped", "reason": "window_not_closed"}

    frequency_key = prefs.frequency.value
    sent_period_key = f"{frequency_key}_last_sent_period"
    sent_at_key = f"{frequency_key}_last_sent_at"
    failed_period_key = f"{frequency_key}_last_failed_period"
    failed_at_key = f"{frequency_key}_last_failed_at"

    state = _load_summary_notification_schedule_state(storage)
    if str(state.get(sent_period_key) or "") == period_id:
        return {"status": "skipped", "reason": "already_sent", "period_id": period_id}

    retry_seconds = max(60, int(get_settings().summary_scheduler_retry_seconds))
    last_failed_period = str(state.get(failed_period_key) or "")
    last_failed_at = _parse_utc_iso_timestamp(state.get(failed_at_key))
    if (
        last_failed_period == period_id
        and last_failed_at is not None
        and (now - last_failed_at).total_seconds() < retry_seconds
    ):
        return {"status": "skipped", "reason": "retry_backoff", "period_id": period_id}

    stats = _collect_summary_trade_stats(storage, start=start, end=end)
    if prefs.frequency == SummaryNotificationFrequency.DAILY:
        period_label = f"{start.date().isoformat()} UTC"
    else:
        period_label = f"{start.date().isoformat()} to {(end - timedelta(days=1)).date().isoformat()} UTC"
    summary = (
        f"{prefs.frequency.value.title()} summary ({period_label}): {stats['trade_count']} trade(s), "
        f"gross ${stats['gross_notional']:.2f}, realized P&L ${stats['realized_pnl']:.2f}"
    )
    subject = f"StocksBot {prefs.frequency.value.title()} Trade Summary ({period_label})"
    result = _send_summary_with_stats(
        storage=storage,
        prefs=prefs,
        stats=stats,
        subject=subject,
        summary_body=summary,
        source="scheduler",
    )
    if result.success:
        state[sent_period_key] = period_id
        state[sent_at_key] = now.isoformat()
        state.pop(failed_period_key, None)
        state.pop(failed_at_key, None)
        _save_summary_notification_schedule_state(storage, state)
        return {
            "status": "sent",
            "period_id": period_id,
            "frequency": frequency_key,
            "trade_count": int(stats["trade_count"]),
            "message": result.message,
        }

    state[failed_period_key] = period_id
    state[failed_at_key] = now.isoformat()
    _save_summary_notification_schedule_state(storage, state)
    return {
        "status": "failed",
        "period_id": period_id,
        "frequency": frequency_key,
        "message": result.message,
    }


def run_scheduled_summary_dispatch_cycle() -> Dict[str, Any]:
    """
    Execute one scheduler cycle using an internal DB session.
    Safe to call from background threads.
    """
    db = SessionLocal()
    try:
        storage = StorageService(db)
        return _dispatch_scheduled_summary(storage=storage)
    except (RuntimeError, ValueError, TypeError, SQLAlchemyError) as exc:
        logger.exception("Scheduled summary dispatch cycle failed")
        return {"status": "error", "message": str(exc)}
    finally:
        db.close()


def _summary_scheduler_loop() -> None:
    """Background loop for automatic daily/weekly summary notification dispatch."""
    settings = get_settings()
    poll_seconds = max(15, int(settings.summary_scheduler_poll_seconds))
    logger.info("Summary scheduler started (poll=%ss)", poll_seconds)
    while not _summary_scheduler_stop_event.is_set():
        cycle_result = run_scheduled_summary_dispatch_cycle()
        status = cycle_result.get("status")
        if status == "failed":
            logger.warning("Summary scheduler delivery failed: %s", cycle_result.get("message", "unknown"))
        elif status == "error":
            logger.error("Summary scheduler cycle error: %s", cycle_result.get("message", "unknown"))
        _summary_scheduler_stop_event.wait(timeout=poll_seconds)
    logger.info("Summary scheduler stopped")


def start_summary_scheduler() -> bool:
    """Start automatic summary scheduler thread (idempotent)."""
    global _summary_scheduler_thread
    settings = get_settings()
    if not settings.summary_scheduler_enabled:
        return False
    # Keep test runs deterministic and avoid side-thread churn in pytest.
    if "PYTEST_CURRENT_TEST" in os.environ:
        return False
    with _summary_scheduler_lock:
        if _summary_scheduler_thread and _summary_scheduler_thread.is_alive():
            return False
        _summary_scheduler_stop_event.clear()
        _summary_scheduler_thread = threading.Thread(
            target=_summary_scheduler_loop,
            daemon=True,
            name="stocksbot-summary-scheduler",
        )
        _summary_scheduler_thread.start()
        return True


def stop_summary_scheduler() -> bool:
    """Stop automatic summary scheduler thread (idempotent)."""
    global _summary_scheduler_thread
    with _summary_scheduler_lock:
        thread = _summary_scheduler_thread
        if thread is None or not thread.is_alive():
            return False
        _summary_scheduler_stop_event.set()
        thread.join(timeout=5.0)
        _summary_scheduler_thread = None
        return True


@router.get("/config", response_model=ConfigResponse)
async def get_config(db: Session = Depends(get_db)):
    """
    Get current configuration.
    TODO: Load from persistent storage.
    """
    storage = StorageService(db)
    config = _load_runtime_config(storage)
    _set_config_snapshot(config)
    return config


@router.post("/config", response_model=ConfigResponse)
async def update_config(
    request: ConfigUpdateRequest,
    db: Session = Depends(get_db),
    x_idempotency_key: Optional[str] = Header(default=None),
):
    """
    Update configuration.
    TODO: Persist to storage and validate changes.
    """
    cached = _idempotency_cache_get("/config", x_idempotency_key)
    if cached is not None:
        return ConfigResponse(**cached)

    storage = StorageService(db)
    config = _load_runtime_config(storage)

    if request.trading_enabled is not None:
        config.trading_enabled = request.trading_enabled
    if request.paper_trading is not None:
        config.paper_trading = request.paper_trading
    if request.max_position_size is not None:
        if not math.isfinite(request.max_position_size):
            raise HTTPException(status_code=400, detail="max_position_size must be a finite number")
        if request.max_position_size < 1 or request.max_position_size > 10_000_000:
            raise HTTPException(status_code=400, detail="max_position_size must be within [1, 10000000]")
        config.max_position_size = request.max_position_size
    if request.risk_limit_daily is not None:
        if not math.isfinite(request.risk_limit_daily):
            raise HTTPException(status_code=400, detail="risk_limit_daily must be a finite number")
        if request.risk_limit_daily < 1 or request.risk_limit_daily > 1_000_000:
            raise HTTPException(status_code=400, detail="risk_limit_daily must be within [1, 1000000]")
        config.risk_limit_daily = request.risk_limit_daily
    if request.tick_interval_seconds is not None:
        if not math.isfinite(request.tick_interval_seconds):
            raise HTTPException(status_code=400, detail="tick_interval_seconds must be a finite number")
        if request.tick_interval_seconds < 5 or request.tick_interval_seconds > 3600:
            raise HTTPException(status_code=400, detail="tick_interval_seconds must be within [5, 3600]")
        config.tick_interval_seconds = request.tick_interval_seconds
        runner_manager.set_tick_interval(config.tick_interval_seconds)
    if request.streaming_enabled is not None:
        config.streaming_enabled = request.streaming_enabled
        runner_manager.set_streaming_enabled(config.streaming_enabled)
    if request.strict_alpaca_data is not None:
        config.strict_alpaca_data = bool(request.strict_alpaca_data)
    if request.log_directory is not None:
        candidate = request.log_directory.strip()
        if not candidate:
            raise HTTPException(status_code=400, detail="log_directory cannot be empty")
        config.log_directory = str(configure_file_logging(candidate))
    if request.audit_export_directory is not None:
        candidate = request.audit_export_directory.strip()
        if not candidate:
            raise HTTPException(status_code=400, detail="audit_export_directory cannot be empty")
        export_dir = Path(candidate).expanduser().resolve()
        export_dir.mkdir(parents=True, exist_ok=True)
        config.audit_export_directory = str(export_dir)
    if request.log_retention_days is not None:
        config.log_retention_days = int(request.log_retention_days)
    if request.audit_retention_days is not None:
        config.audit_retention_days = int(request.audit_retention_days)
    if request.broker is not None:
        broker_value = str(request.broker).strip().lower()
        if broker_value not in {"paper", "alpaca"}:
            raise HTTPException(status_code=400, detail="broker must be either 'paper' or 'alpaca'")
        config.broker = broker_value

    # Recreate broker on next use when mode changes.
    _set_config_snapshot(config)
    set_global_trading_enabled(bool(config.trading_enabled))
    _invalidate_broker_instance()
    _run_housekeeping(storage, force=True)
    _save_runtime_config(storage, config)
    _idempotency_cache_set("/config", x_idempotency_key, config.model_dump())

    return config


@router.get("/broker/credentials/status", response_model=BrokerCredentialsStatusResponse)
async def get_broker_credentials_status():
    """
    Get status of runtime broker credentials loaded from desktop keychain.
    """
    paper_creds = _get_runtime_credentials("paper")
    live_creds = _get_runtime_credentials("live")
    paper_available = bool(paper_creds.get("api_key") and paper_creds.get("secret_key"))
    live_available = bool(live_creds.get("api_key") and live_creds.get("secret_key"))
    config = _get_config_snapshot()
    active_mode = "paper" if config.paper_trading else "live"
    using_runtime_credentials = paper_available if active_mode == "paper" else live_available

    return BrokerCredentialsStatusResponse(
        paper_available=paper_available,
        live_available=live_available,
        active_mode=active_mode,
        using_runtime_credentials=using_runtime_credentials,
    )


@router.post("/broker/credentials", response_model=BrokerCredentialsStatusResponse)
async def set_broker_credentials(request: BrokerCredentialsRequest):
    """
    Set runtime Alpaca credentials from desktop keychain flow.
    Credentials are held in-memory only and never persisted to DB.
    """
    mode = request.mode.strip().lower()
    if mode not in ("paper", "live"):
        raise HTTPException(status_code=400, detail="Mode must be 'paper' or 'live'")

    api_key = request.api_key.strip()
    secret_key = request.secret_key.strip()
    if len(api_key) < 8 or len(secret_key) < 8:
        raise HTTPException(status_code=400, detail="API key and secret key appear too short")
    if len(api_key) > 512 or len(secret_key) > 512:
        raise HTTPException(status_code=400, detail="API key and secret key are too long")
    if any(ch.isspace() for ch in api_key) or any(ch.isspace() for ch in secret_key):
        raise HTTPException(status_code=400, detail="API key and secret key cannot contain whitespace")

    _set_runtime_credentials(mode, api_key, secret_key)

    # Ensure broker instance is recreated with latest credentials.
    _invalidate_broker_instance()

    return await get_broker_credentials_status()


@router.get("/broker/account", response_model=BrokerAccountResponse)
async def get_broker_account(db: Session = Depends(get_db)):
    """
    Get active broker account balances (cash/equity/buying power).
    Returns an informative disconnected payload if unavailable.
    """
    status = await get_broker_credentials_status()
    config = _get_config_snapshot()
    mode = "paper" if config.paper_trading else "live"
    cache_key = f"{str(config.broker).lower()}:{mode}:{int(bool(config.strict_alpaca_data))}:{int(bool(status.using_runtime_credentials))}"
    cached = _broker_account_cache_get(cache_key)
    if cached is not None:
        return BrokerAccountResponse(**cached)
    try:
        broker = get_broker()
        config = _get_config_snapshot()
        market_open = True
        try:
            market_open = bool(broker.is_market_open())
        except (RuntimeError, ValueError, TypeError, KeyError):
            market_open = True

        if not market_open:
            storage = StorageService(db)
            latest = storage.get_latest_portfolio_snapshot()
            if latest is not None:
                response = BrokerAccountResponse(
                    broker=config.broker,
                    mode=mode,
                    connected=True,
                    using_runtime_credentials=status.using_runtime_credentials,
                    currency="USD",
                    cash=float(_safe_float(latest.cash, 0.0)),
                    equity=float(_safe_float(latest.equity, 0.0)),
                    buying_power=float(_safe_float(latest.buying_power, 0.0)),
                    message="Market closed: showing last persisted portfolio snapshot",
                )
                _broker_account_cache_set(cache_key, response.model_dump())
                return response

        info = broker.get_account_info()
        cash = float(info.get("cash", 0.0))
        equity = float(info.get("equity", info.get("portfolio_value", 0.0)))
        buying_power = float(info.get("buying_power", 0.0))
        currency = str(info.get("currency", "USD"))
        response = BrokerAccountResponse(
            broker=config.broker,
            mode=mode,
            connected=True,
            using_runtime_credentials=status.using_runtime_credentials,
            currency=currency,
            cash=cash,
            equity=equity,
            buying_power=buying_power,
            message="Account fetched successfully",
        )
        _broker_account_cache_set(cache_key, response.model_dump())
        return response
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        response = BrokerAccountResponse(
            broker=config.broker,
            mode=mode,
            connected=False,
            using_runtime_credentials=status.using_runtime_credentials,
            currency="USD",
            cash=0.0,
            equity=0.0,
            buying_power=0.0,
            message=f"Broker account unavailable: {exc}",
        )
        _broker_account_cache_set(cache_key, response.model_dump())
        return response
    finally:
        _set_last_broker_sync(datetime.now(timezone.utc).isoformat())


# ============================================================================
# Positions Endpoints
# ============================================================================

@router.get("/positions", response_model=PositionsResponse)
async def get_positions(db: Session = Depends(get_db)):
    """
    Get current positions from broker, with local fallback if broker is unavailable.
    """
    snapshot_as_of = datetime.now(timezone.utc)
    broker_positions: List[Dict[str, Any]] = []
    data_source = "broker"
    degraded = False
    degraded_reason: Optional[str] = None
    try:
        broker = get_broker()
        broker_positions = broker.get_positions()
    except RuntimeError as exc:
        data_source = "local_fallback"
        degraded = True
        degraded_reason = f"Broker positions unavailable: {exc}"
        storage = StorageService(db)
        local_positions = storage.get_open_positions()
        for position in local_positions:
            broker_positions.append({
                "symbol": position.symbol,
                "quantity": float(position.quantity),
                "side": position.side.value if hasattr(position.side, "value") else str(position.side),
                "avg_entry_price": float(position.avg_entry_price),
                "current_price": None,
                "market_value": float(position.cost_basis),
                "cost_basis": float(position.cost_basis),
                "unrealized_pnl": 0.0,
                "unrealized_pnl_percent": 0.0,
                "current_price_available": False,
                "valuation_source": "cost_basis_fallback",
            })
    positions: List[Position] = []
    for raw in broker_positions:
        qty = float(raw.get("quantity", 0.0))
        current_price_raw = raw.get("current_price", raw.get("price", None))
        current_price_available = current_price_raw is not None
        if current_price_available:
            current_price = float(current_price_raw)
            if not math.isfinite(current_price) or current_price <= 0:
                current_price = 0.0
                current_price_available = False
        else:
            current_price = 0.0
        avg_entry_price = float(raw.get("avg_entry_price", 0.0))
        cost_basis = float(raw.get("cost_basis", abs(qty) * avg_entry_price))
        if "market_value" in raw:
            market_value = float(raw.get("market_value", 0.0))
        elif current_price_available:
            market_value = abs(qty) * current_price
        else:
            market_value = cost_basis
        if "unrealized_pnl" in raw:
            unrealized_pnl = float(raw.get("unrealized_pnl", 0.0))
        elif current_price_available:
            unrealized_pnl = market_value - cost_basis
        else:
            unrealized_pnl = 0.0
        unrealized_pnl_percent = float(
            raw.get(
                "unrealized_pnl_percent",
                ((unrealized_pnl / cost_basis) * 100.0) if current_price_available and cost_basis > 0 else 0.0,
            )
        )
        side_raw = str(raw.get("side", "long")).lower()
        side = PositionSide.SHORT if side_raw == "short" else PositionSide.LONG
        valuation_source = str(raw.get("valuation_source", "broker_mark" if current_price_available else "cost_basis_fallback"))
        positions.append(
            Position(
                symbol=str(raw.get("symbol", "")).upper(),
                side=side,
                quantity=abs(qty),
                avg_entry_price=avg_entry_price,
                current_price=current_price,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_percent=unrealized_pnl_percent,
                cost_basis=cost_basis,
                market_value=market_value,
                current_price_available=current_price_available,
                valuation_source=valuation_source,
            )
        )

    total_value = sum(p.market_value for p in positions)
    total_pnl = sum(p.unrealized_pnl for p in positions)
    total_cost = sum(p.cost_basis for p in positions)
    total_pnl_percent = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0

    return PositionsResponse(
        positions=positions,
        total_value=total_value,
        total_pnl=total_pnl,
        total_pnl_percent=total_pnl_percent,
        as_of=snapshot_as_of,
        data_source=data_source,
        degraded=degraded,
        degraded_reason=degraded_reason,
    )


# ============================================================================
# Orders Endpoints
# ============================================================================

@router.get("/orders", response_model=OrdersResponse)
async def get_orders(db: Session = Depends(get_db)):
    """
    Get recent orders from local storage and enrich with broker state when available.
    """
    storage = StorageService(db)
    local_rows = storage.get_recent_orders(limit=500)
    orders = [_api_order_from_storage_row(row) for row in local_rows]

    by_external_id: Dict[str, int] = {}
    for idx, row in enumerate(local_rows):
        external_id = str(getattr(row, "external_id", "") or "").strip()
        if external_id:
            by_external_id[external_id] = idx

    try:
        broker = get_broker()
        broker_rows = broker.get_orders()
    except (RuntimeError, ValueError, TypeError):
        broker_rows = []

    for raw in broker_rows:
        broker_order = _api_order_from_broker_row(raw)
        if broker_order is None:
            continue
        external_id = str(raw.get("id", "")).strip()
        local_index = by_external_id.get(external_id)
        if local_index is not None and 0 <= local_index < len(orders):
            local_order = orders[local_index]
            local_order.status = broker_order.status
            local_order.filled_quantity = broker_order.filled_quantity
            local_order.avg_fill_price = broker_order.avg_fill_price
            local_order.updated_at = broker_order.updated_at
            continue
        orders.append(broker_order)

    orders.sort(key=lambda row: row.updated_at, reverse=True)
    return OrdersResponse(orders=orders, total_count=len(orders))


@router.post("/orders", response_model=Order)
async def create_order(
    request: OrderRequest,
    execution_service: OrderExecutionService = Depends(get_order_execution_service)
):
    """
    Create and execute a new order.
    
    This endpoint:
    1. Validates the order against account and risk limits
    2. Submits the order to the configured broker (Paper or Alpaca)
    3. Persists the order to the database
    4. Returns the created order with broker confirmation
    
    Args:
        request: Order request with symbol, side, type, quantity, and price
        execution_service: Order execution service (injected)
        
    Returns:
        Created order with status
        
    Raises:
        HTTPException: If validation fails or broker execution fails
    """
    try:
        # Refresh config snapshot from request-scoped storage to avoid stale
        # process-level config bleed across long-lived sessions/tests.
        try:
            runtime_config = _load_runtime_config(execution_service.storage)
            _set_config_snapshot(runtime_config)
        except Exception:
            pass

        block_reason = _execution_block_reason(request.symbol, execution_service.broker)
        if block_reason:
            raise HTTPException(status_code=409, detail=block_reason)

        # Execute order
        order = execution_service.submit_order(
            symbol=request.symbol,
            side=request.side.value,
            order_type=request.type.value,
            quantity=request.quantity,
            price=request.price
        )
        
        # Map to response model
        return Order(
            id=str(order.id),
            symbol=order.symbol,
            side=OrderSide(order.side.value),
            type=OrderType(order.type.value),
            quantity=order.quantity,
            price=order.price,
            status=_to_order_status(order.status.value),
            filled_quantity=order.filled_quantity or 0.0,
            avg_fill_price=order.avg_fill_price,
            created_at=_ensure_utc_datetime(order.created_at),
            updated_at=_ensure_utc_datetime(order.updated_at),
        )
        
    except OrderValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except BrokerError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (RuntimeError, ValueError, TypeError) as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


# ============================================================================
# Notifications Endpoints
# ============================================================================

@router.post("/notifications", response_model=NotificationResponse)
async def request_notification(request: NotificationRequest, db: Session = Depends(get_db)):
    """
    Request a notification to be sent to the user.
    Uses configured summary notification channel + recipient.
    """
    storage = StorageService(db)
    prefs = _load_summary_notification_preferences(storage)

    if not prefs.enabled:
        return NotificationResponse(success=False, message="Summary notifications are disabled")
    if not prefs.recipient:
        return NotificationResponse(success=False, message="Recipient is required")

    title = request.title.strip()
    message = request.message.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    subject = f"[{request.severity.value.upper()}] {title}"
    body = f"{title}\n\n{message}"

    try:
        delivery = NotificationDeliveryService()
        delivery_result = delivery.send_summary(
            channel=prefs.channel,
            recipient=prefs.recipient,
            subject=subject,
            body=body,
        )
    except RuntimeError as exc:
        storage.create_audit_log(
            event_type="error",
            description=f"Notification delivery failed ({prefs.channel.value})",
            details={
                "title": title,
                "severity": request.severity.value,
                "recipient": prefs.recipient,
                "channel": prefs.channel.value,
                "error": str(exc),
            },
        )
        return NotificationResponse(success=False, message=f"Notification delivery failed: {exc}")

    storage.create_audit_log(
        event_type="config_updated",
        description=f"Sent {prefs.channel.value} notification",
        details={
            "title": title,
            "severity": request.severity.value,
            "recipient": prefs.recipient,
            "channel": prefs.channel.value,
            "delivery": delivery_result,
        },
    )

    return NotificationResponse(success=True, message=delivery_result)


@router.get("/notifications/summary/preferences", response_model=SummaryNotificationPreferencesResponse)
async def get_summary_notification_preferences(db: Session = Depends(get_db)):
    """Get daily/weekly summary notification preferences."""
    storage = StorageService(db)
    return _load_summary_notification_preferences(storage)


@router.post("/notifications/summary/preferences", response_model=SummaryNotificationPreferencesResponse)
async def update_summary_notification_preferences(
    request: SummaryNotificationPreferencesRequest,
    db: Session = Depends(get_db),
):
    """Update summary notification preferences."""
    global _summary_notification_preferences
    storage = StorageService(db)
    current = _load_summary_notification_preferences(storage)

    if request.enabled is not None:
        current.enabled = request.enabled
    if request.frequency is not None:
        current.frequency = request.frequency
    if request.channel is not None:
        current.channel = request.channel
    if request.recipient is not None:
        current.recipient = request.recipient.strip()

    if current.enabled:
        if not current.recipient:
            raise HTTPException(status_code=400, detail="Recipient is required when summary notifications are enabled")
        if current.channel == SummaryNotificationChannel.EMAIL and not _EMAIL_RE.match(current.recipient):
            raise HTTPException(status_code=400, detail="Recipient must be a valid email address for email notifications")
        if current.channel == SummaryNotificationChannel.SMS and not _PHONE_RE.match(current.recipient):
            raise HTTPException(status_code=400, detail="Recipient must be an E.164-like phone number for SMS notifications")

    _summary_notification_preferences = current
    _save_summary_notification_preferences(storage, current)
    storage.create_audit_log(
        event_type="config_updated",
        description="Summary notification preferences updated",
        details=current.model_dump(),
    )
    return current


@router.post("/notifications/summary/send-now", response_model=NotificationResponse)
async def send_summary_notification_now(db: Session = Depends(get_db)):
    """
    Generate and deliver a summary notification immediately.
    Uses current in-progress daily/weekly window.
    """
    storage = StorageService(db)
    prefs = _load_summary_notification_preferences(storage)

    if not prefs.enabled:
        return NotificationResponse(success=False, message="Summary notifications are disabled")
    if not prefs.recipient:
        return NotificationResponse(success=False, message="Recipient is required")

    now = datetime.now(timezone.utc)
    if prefs.frequency == SummaryNotificationFrequency.DAILY:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = start - timedelta(days=start.weekday())
    stats = _collect_summary_trade_stats(storage=storage, start=start, end=None)
    summary = (
        f"{prefs.frequency.value.title()} summary: {stats['trade_count']} trade(s), "
        f"gross ${stats['gross_notional']:.2f}, realized P&L ${stats['realized_pnl']:.2f}"
    )
    subject = f"StocksBot {prefs.frequency.value.title()} Trade Summary"
    return _send_summary_with_stats(
        storage=storage,
        prefs=prefs,
        stats=stats,
        subject=subject,
        summary_body=summary,
        source="manual_send_now",
    )


# ============================================================================
# Strategy Endpoints
# ============================================================================

@router.get("/strategies", response_model=StrategiesResponse)
async def get_strategies(db: Session = Depends(get_db)):
    """
    Get all strategies from database.
    """
    storage = StorageService(db)
    db_strategies = storage.strategies.get_all()

    strategies = []
    for db_strat in db_strategies:
        strategies.append(Strategy(
            id=str(db_strat.id),
            name=db_strat.name,
            description=db_strat.description or "",
            status=StrategyStatus.ACTIVE if db_strat.is_active else StrategyStatus.STOPPED,
            symbols=db_strat.config.get('symbols', []) if db_strat.config else [],
            created_at=_ensure_utc_datetime(db_strat.created_at),
            updated_at=_ensure_utc_datetime(db_strat.updated_at),
        ))

    return StrategiesResponse(
        strategies=strategies,
        total_count=len(strategies),
    )


@router.post("/strategies", response_model=Strategy)
async def create_strategy(request: StrategyCreateRequest, db: Session = Depends(get_db)):
    """
    Create a new strategy and persist to database.
    """
    storage = StorageService(db)

    existing = storage.strategies.get_by_name(request.name)
    if existing:
        raise HTTPException(status_code=400, detail="Strategy with this name already exists")
    symbols = _normalize_symbols(request.symbols or [])

    db_strategy = storage.strategies.create(
        name=request.name,
        description=request.description or "",
        strategy_type="custom",
        config={"symbols": symbols},
    )

    storage.create_audit_log(
        event_type="strategy_started",
        description=f"Strategy created: {request.name}",
        details={"strategy_id": db_strategy.id, "symbols": symbols},
    )

    return Strategy(
        id=str(db_strategy.id),
        name=db_strategy.name,
        description=db_strategy.description or "",
        status=StrategyStatus.STOPPED,
        symbols=symbols,
        created_at=_ensure_utc_datetime(db_strategy.created_at),
        updated_at=_ensure_utc_datetime(db_strategy.updated_at),
    )


@router.get("/strategies/{strategy_id}", response_model=Strategy)
async def get_strategy(strategy_id: str, db: Session = Depends(get_db)):
    """
    Get a specific strategy by ID from database.
    """
    storage = StorageService(db)

    try:
        strategy_id_int = int(strategy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid strategy ID")

    db_strategy = storage.strategies.get_by_id(strategy_id_int)
    if not db_strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    return Strategy(
        id=str(db_strategy.id),
        name=db_strategy.name,
        description=db_strategy.description or "",
        status=StrategyStatus.ACTIVE if db_strategy.is_active else StrategyStatus.STOPPED,
        symbols=db_strategy.config.get('symbols', []) if db_strategy.config else [],
        created_at=_ensure_utc_datetime(db_strategy.created_at),
        updated_at=_ensure_utc_datetime(db_strategy.updated_at),
    )


@router.put("/strategies/{strategy_id}", response_model=Strategy)
async def update_strategy(strategy_id: str, request: StrategyUpdateRequest, db: Session = Depends(get_db)):
    """
    Update a strategy in the database.
    """
    storage = StorageService(db)

    try:
        strategy_id_int = int(strategy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid strategy ID")

    db_strategy = storage.strategies.get_by_id(strategy_id_int)
    if not db_strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    if request.name is not None:
        db_strategy.name = request.name
    if request.description is not None:
        db_strategy.description = request.description
    if request.symbols is not None:
        if not db_strategy.config:
            db_strategy.config = {}
        db_strategy.config["symbols"] = _normalize_symbols(request.symbols)
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(db_strategy, "config")
    if request.status is not None:
        db_strategy.is_active = (request.status == StrategyStatus.ACTIVE)
        storage.create_audit_log(
            event_type="strategy_started" if db_strategy.is_active else "strategy_stopped",
            description=f"Strategy {'started' if db_strategy.is_active else 'stopped'}: {db_strategy.name}",
            details={"strategy_id": db_strategy.id},
        )

    db_strategy = storage.strategies.update(db_strategy)

    return Strategy(
        id=str(db_strategy.id),
        name=db_strategy.name,
        description=db_strategy.description or "",
        status=StrategyStatus.ACTIVE if db_strategy.is_active else StrategyStatus.STOPPED,
        symbols=db_strategy.config.get('symbols', []) if db_strategy.config else [],
        created_at=_ensure_utc_datetime(db_strategy.created_at),
        updated_at=_ensure_utc_datetime(db_strategy.updated_at),
    )


@router.delete("/strategies/{strategy_id}")
async def delete_strategy(strategy_id: str, db: Session = Depends(get_db)):
    """
    Delete a strategy from the database.
    """
    storage = StorageService(db)

    try:
        strategy_id_int = int(strategy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid strategy ID")

    db_strategy = storage.strategies.get_by_id(strategy_id_int)
    if not db_strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    try:
        # Normalize to stopped state before delete to avoid stale active-state confusion.
        if db_strategy.is_active:
            db_strategy.is_active = False
            storage.strategies.update(db_strategy)

        storage.create_audit_log(
            event_type="strategy_stopped",
            description=f"Strategy deleted: {db_strategy.name}",
            details={"strategy_id": db_strategy.id},
        )

        storage.strategies.delete(strategy_id_int)

        # Keep runner in-memory state in sync with DB.
        runner_manager.remove_strategy_by_name(db_strategy.name)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete strategy: {str(exc)}")

    return {"message": "Strategy deleted"}


# ============================================================================
# Audit Log Endpoints
# ============================================================================

@router.get("/audit/logs", response_model=AuditLogsResponse)
async def get_audit_logs(
    limit: int = 100,
    event_type: Optional[AuditEventType] = None,
    db: Session = Depends(get_db)
):
    """
    Get audit logs from database with filtering and pagination.
    """
    storage = StorageService(db)
    _run_housekeeping(storage)

    event_type_str = event_type.value if event_type else None
    db_logs = storage.get_audit_logs(limit=limit, event_type=event_type_str)
    total_count = storage.count_audit_logs(event_type=event_type_str)

    logs = []
    for db_log in db_logs:
        logs.append(AuditLog(
            id=str(db_log.id),
            timestamp=_ensure_utc_datetime(db_log.timestamp),
            event_type=AuditEventType(
                db_log.event_type.value if hasattr(db_log.event_type, "value") else str(db_log.event_type)
            ),
            description=db_log.description,
            details=db_log.details or {},
        ))

    return AuditLogsResponse(
        logs=logs,
        total_count=total_count,
    )


@router.get("/audit/trades", response_model=TradeHistoryResponse)
async def get_audit_trades(
    limit: int = Query(default=5000, ge=1, le=10000),
    db: Session = Depends(get_db)
):
    """
    Get complete trade history for audit mode.
    """
    storage = StorageService(db)
    db_trades = storage.get_all_trades(limit=limit)

    trades = []
    for trade in db_trades:
        trades.append(
            TradeHistoryItem(
                id=str(trade.id),
                order_id=str(trade.order_id),
                symbol=trade.symbol,
                side=OrderSide(trade.side.value if hasattr(trade.side, "value") else str(trade.side)),
                quantity=trade.quantity,
                price=trade.price,
                commission=trade.commission or 0.0,
                fees=trade.fees or 0.0,
                executed_at=_ensure_utc_datetime(trade.executed_at),
                realized_pnl=trade.realized_pnl,
            )
        )

    return TradeHistoryResponse(
        trades=trades,
        total_count=len(trades),
    )


# ============================================================================
# Strategy Runner Endpoints
# ============================================================================

@router.get("/runner/status", response_model=RunnerStatusResponse)
async def get_runner_status():
    """
    Get strategy runner status.
    Returns current status and loaded strategies.
    """
    status = runner_manager.get_status()
    return RunnerStatusResponse(**status)


@router.get("/runner/preflight")
async def get_runner_preflight(db: Session = Depends(get_db)):
    """
    Validate active strategies against live execution constraints before runner start.
    """
    storage = StorageService(db)
    config = _load_runtime_config(storage)
    _set_config_snapshot(config)
    prefs = _load_trading_preferences(storage)
    active_strategies = storage.get_active_strategies()
    existing_position_count = len(storage.get_open_positions())

    broker_error = ""
    broker: Optional[BrokerInterface] = None
    try:
        broker = get_broker()
    except RuntimeError as exc:
        broker_error = str(exc)
        broker = None

    account_snapshot = _load_account_snapshot(broker)
    equity = _safe_float(account_snapshot.get("equity", 0.0), 0.0)
    buying_power = _safe_float(account_snapshot.get("buying_power", 0.0), 0.0)
    weekly_budget = _safe_float(prefs.weekly_budget, 200.0)
    budget_tracker = get_budget_tracker(weekly_budget)
    budget_tracker.set_weekly_budget(weekly_budget)
    remaining_weekly_budget = _safe_float(
        budget_tracker.get_budget_status().get("remaining_budget", weekly_budget),
        weekly_budget,
    )
    budget_candidates = [v for v in (buying_power, remaining_weekly_budget, equity * 0.20) if v > 0]
    portfolio_budget_cap = min(budget_candidates) if budget_candidates else 0.0

    capability_cache: Dict[str, Dict[str, bool]] = {}

    def _symbol_capabilities(symbol: str) -> Dict[str, bool]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return {"tradable": False, "fractionable": False}
        if normalized in capability_cache:
            return capability_cache[normalized]
        raw = _collect_symbol_capabilities(broker, [{"symbol": normalized}]).get(normalized, {})
        payload = {
            "tradable": bool(raw.get("tradable", True)),
            "fractionable": bool(raw.get("fractionable", True)),
        }
        capability_cache[normalized] = payload
        return payload

    preset_defaults = runner_manager._strategy_param_defaults_from_prefs({
        "asset_type": prefs.asset_type.value,
        "stock_preset": prefs.stock_preset.value,
        "etf_preset": prefs.etf_preset.value,
    })
    allowed_params = set(preset_defaults.keys())
    require_fractionable = _should_require_fractionable_symbols(prefs.asset_type, prefs, account_snapshot)

    strategy_rows: List[Dict[str, Any]] = []
    eligible_strategy_count = 0
    total_symbols = 0
    eligible_symbols = 0

    for db_strategy in active_strategies:
        strategy_config = db_strategy.config or {}
        raw_symbols = strategy_config.get("symbols", [])
        symbols = runner_manager._normalize_symbols(raw_symbols if isinstance(raw_symbols, list) else [])
        params = strategy_config.get("parameters", {}) if isinstance(strategy_config.get("parameters", {}), dict) else {}
        validated_params: Dict[str, float] = {}
        for key, value in params.items():
            if key not in allowed_params:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric):
                validated_params[key] = numeric
        merged_params = {**preset_defaults, **validated_params}
        dynamic_position_size = runner_manager._dynamic_position_size(
            requested_position_size=float(merged_params.get("position_size", 1000.0)),
            symbol_count=max(1, len(symbols)),
            existing_position_count=existing_position_count,
            remaining_weekly_budget=remaining_weekly_budget,
            buying_power=buying_power,
            equity=equity,
            risk_per_trade_pct=float(merged_params.get("risk_per_trade", 1.0)),
            stop_loss_pct=float(merged_params.get("stop_loss_pct", 2.0)),
        )
        dca_tranches = max(1, int(_safe_float(merged_params.get("dca_tranches", 1), 1)))
        per_tranche_target = max(1.0, dynamic_position_size / dca_tranches)

        symbol_rows: List[Dict[str, Any]] = []
        strategy_eligible_symbols = 0
        for symbol in symbols:
            total_symbols += 1
            capabilities = _symbol_capabilities(symbol)
            broker_tradable = bool(capabilities.get("tradable", True))
            fractionable = bool(capabilities.get("fractionable", True))
            price = 0.0
            if broker is not None:
                try:
                    quote = broker.get_market_data(symbol)
                    price = max(0.0, _safe_float(quote.get("price", 0.0), 0.0))
                except (RuntimeError, ValueError, TypeError, KeyError):
                    price = 0.0

            if fractionable:
                required_ticket = (
                    min(per_tranche_target, max(1.0, portfolio_budget_cap * 0.60))
                    if portfolio_budget_cap > 0
                    else per_tranche_target
                )
                affordable = portfolio_budget_cap <= 0 or portfolio_budget_cap >= 1.0
            else:
                required_ticket = max(price, per_tranche_target)
                affordable = portfolio_budget_cap <= 0 or required_ticket <= portfolio_budget_cap * 1.10

            eligible = broker_tradable and affordable and (fractionable or not require_fractionable)
            reasons: List[str] = []
            if not broker_tradable:
                reasons.append("not broker tradable")
            if require_fractionable and not fractionable:
                reasons.append("not fractionable")
            if not affordable:
                reasons.append("budget constrained")

            symbol_rows.append({
                "symbol": symbol,
                "price": round(price, 4),
                "broker_tradable": broker_tradable,
                "fractionable": fractionable,
                "required_ticket": round(required_ticket, 2),
                "affordable": affordable,
                "eligible": eligible,
                "reasons": reasons,
            })
            if eligible:
                strategy_eligible_symbols += 1
                eligible_symbols += 1

        strategy_ready = len(symbols) > 0 and strategy_eligible_symbols > 0
        if strategy_ready:
            eligible_strategy_count += 1

        strategy_rows.append({
            "strategy_id": db_strategy.id,
            "name": db_strategy.name,
            "status": (
                getattr(getattr(db_strategy, "status", "active"), "value", None)
                or str(getattr(db_strategy, "status", "active"))
            ),
            "symbol_count": len(symbols),
            "eligible_symbol_count": strategy_eligible_symbols,
            "dynamic_position_size": dynamic_position_size,
            "dca_tranches": dca_tranches,
            "symbols": symbol_rows,
            "ready": strategy_ready,
        })

    runner_ready = bool(
        broker is not None
        and not broker_error
        and strategy_rows
        and eligible_strategy_count == len(strategy_rows)
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runner_ready": runner_ready,
        "broker_ready": broker is not None and not broker_error,
        "broker_error": broker_error,
        "require_fractionable": require_fractionable,
        "portfolio_context": {
            "equity": equity,
            "buying_power": buying_power,
            "weekly_budget": weekly_budget,
            "remaining_weekly_budget": remaining_weekly_budget,
            "portfolio_budget_cap": portfolio_budget_cap,
        },
        "summary": {
            "active_strategy_count": len(strategy_rows),
            "ready_strategy_count": eligible_strategy_count,
            "total_symbols": total_symbols,
            "eligible_symbols": eligible_symbols,
        },
        "strategies": strategy_rows,
    }


@router.get("/maintenance/storage")
async def get_storage_settings():
    """Get configured log/audit storage paths and a quick file inventory."""
    config = _get_config_snapshot()
    log_dir = Path(config.log_directory).expanduser().resolve()
    audit_dir = Path(config.audit_export_directory).expanduser().resolve()
    log_files = []
    audit_files = []
    if log_dir.exists():
        log_files = sorted(
            [{"name": p.name, "size_bytes": p.stat().st_size, "modified_at": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()} for p in log_dir.iterdir() if p.is_file()],
            key=lambda row: row["modified_at"],
            reverse=True,
        )[:50]
    if audit_dir.exists():
        audit_files = sorted(
            [{"name": p.name, "size_bytes": p.stat().st_size, "modified_at": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()} for p in audit_dir.iterdir() if p.is_file()],
            key=lambda row: row["modified_at"],
            reverse=True,
        )[:50]
    return {
        "log_directory": str(log_dir),
        "audit_export_directory": str(audit_dir),
        "log_retention_days": config.log_retention_days,
        "audit_retention_days": config.audit_retention_days,
        "log_files": log_files,
        "audit_files": audit_files,
    }


@router.post("/maintenance/cleanup")
async def run_maintenance_cleanup(db: Session = Depends(get_db)):
    """Run immediate retention cleanup based on configured periods."""
    storage = StorageService(db)
    result = _run_housekeeping(storage, force=True)
    return {"success": True, **result}


@router.post("/maintenance/reset-audit-data")
async def reset_audit_data(
    clear_event_logs: bool = Query(default=True),
    clear_trade_history: bool = Query(default=True),
    clear_log_files: bool = Query(default=True),
    clear_audit_export_files: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    """
    Hard reset audit/testing artifacts.

    Intended for repeated test cycles. Refuses to run while strategy runner
    is active to avoid races while new events are still being written.
    """
    status = runner_manager.get_status()
    runner_status = str(status.get("status", "stopped")).lower()
    if runner_status in {"running", "sleeping"}:
        raise HTTPException(status_code=409, detail="Stop runner before resetting audit data")
    if not any([clear_event_logs, clear_trade_history, clear_log_files, clear_audit_export_files]):
        raise HTTPException(status_code=400, detail="At least one reset option must be enabled")

    audit_rows_deleted = 0
    trade_rows_deleted = 0
    log_files_deleted = 0
    audit_files_deleted = 0
    try:
        if clear_event_logs:
            audit_rows_deleted = int(db.query(DBAuditLog).delete(synchronize_session=False) or 0)
        if clear_trade_history:
            trade_rows_deleted = int(db.query(DBTrade).delete(synchronize_session=False) or 0)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to reset audit database rows: {exc}")

    config = _get_config_snapshot()
    if clear_log_files:
        log_files_deleted = _delete_all_files(config.log_directory)
    if clear_audit_export_files:
        audit_files_deleted = _delete_all_files(config.audit_export_directory)

    return {
        "success": True,
        "runner_status": runner_status,
        "audit_rows_deleted": int(audit_rows_deleted),
        "trade_rows_deleted": int(trade_rows_deleted),
        "log_files_deleted": int(log_files_deleted),
        "audit_files_deleted": int(audit_files_deleted),
        "cleared": {
            "event_logs": bool(clear_event_logs),
            "trade_history": bool(clear_trade_history),
            "log_files": bool(clear_log_files),
            "audit_export_files": bool(clear_audit_export_files),
        },
    }


@router.get("/safety/status")
async def get_safety_status(db: Session = Depends(get_db)):
    """Get trading safety controls status."""
    storage = StorageService(db)
    active = _load_kill_switch(storage)
    set_global_kill_switch(active)
    return {
        "kill_switch_active": active,
        "last_broker_sync_at": _last_broker_sync_at,
    }


@router.get("/safety/preflight")
async def safety_preflight(symbol: str, db: Session = Depends(get_db)):
    """Return execution block reason for a candidate symbol."""
    storage = StorageService(db)
    set_global_kill_switch(_load_kill_switch(storage))
    config = _load_runtime_config(storage)
    _set_config_snapshot(config)
    set_global_trading_enabled(bool(config.trading_enabled))
    if not config.trading_enabled:
        mode = "paper" if bool(config.paper_trading) else "live"
        return {
            "allowed": False,
            "reason": (
                "Trading is disabled in Settings. "
                f"{mode.title()} mode only selects the account mode; it does not enable execution."
            ),
        }
    broker = get_broker()
    reason = _execution_block_reason(symbol.strip().upper(), broker)
    return {"allowed": reason is None, "reason": reason or ""}


@router.post("/safety/kill-switch")
async def set_safety_kill_switch(
    active: bool,
    db: Session = Depends(get_db),
    x_idempotency_key: Optional[str] = Header(default=None),
):
    """Enable or disable global kill switch."""
    cached = _idempotency_cache_get("/safety/kill-switch", x_idempotency_key)
    if cached is not None:
        return cached
    storage = StorageService(db)
    set_global_kill_switch(active)
    _save_kill_switch(storage, active)
    storage.create_audit_log(
        event_type="config_updated",
        description=f"Kill switch {'enabled' if active else 'disabled'}",
        details={"kill_switch_active": active},
    )
    payload = {"success": True, "kill_switch_active": active}
    _idempotency_cache_set("/safety/kill-switch", x_idempotency_key, payload)
    return payload


@router.post("/safety/panic-stop", response_model=RunnerActionResponse)
async def panic_stop(
    db: Session = Depends(get_db),
    x_idempotency_key: Optional[str] = Header(default=None),
):
    """
    Emergency stop: enables kill switch, stops runner, and liquidates positions.
    """
    cached = _idempotency_cache_get("/safety/panic-stop", x_idempotency_key)
    if cached is not None:
        return RunnerActionResponse(**cached)

    storage = StorageService(db)
    set_global_kill_switch(True)
    _save_kill_switch(storage, True)
    _ = runner_manager.stop_runner(db=db)
    selloff = await selloff_all_positions()
    payload = {
        "success": True,
        "message": f"Panic stop executed. {selloff.message}",
        "status": "stopped",
    }
    storage.create_audit_log(
        event_type="error",
        description="Panic stop executed",
        details={"selloff_message": selloff.message},
    )
    _idempotency_cache_set("/safety/panic-stop", x_idempotency_key, payload)
    return RunnerActionResponse(**payload)


@router.post("/reconciliation/run")
async def run_reconciliation(db: Session = Depends(get_db)):
    """Run manual reconciliation against broker state."""
    storage = StorageService(db)
    broker = get_broker()
    result = _run_reconciliation(storage, broker)
    return {"success": True, **result}


@router.post("/auth/ws-ticket", response_model=WebSocketAuthTicketResponse)
async def create_ws_auth_ticket():
    """Issue one-time websocket auth ticket for browser clients."""
    if not _is_api_auth_required():
        raise HTTPException(status_code=400, detail="API auth is not enabled")
    ticket, expires_at = _issue_ws_auth_ticket()
    return WebSocketAuthTicketResponse(
        ticket=ticket,
        expires_at=expires_at,
        expires_in_seconds=_WS_AUTH_TICKET_TTL_SECONDS,
    )


@router.websocket("/ws/system-health")
async def ws_system_health(websocket: WebSocket):
    """Realtime health snapshot stream for UI surfaces."""
    if _is_api_auth_required():
        ticket = (websocket.query_params.get("ticket") or "").strip()
        ticket_valid = _consume_ws_auth_ticket(ticket)
        provided_key = _extract_api_key_from_websocket(websocket)
        if not ticket_valid and not _is_api_key_valid(provided_key):
            await websocket.close(code=4401)
            return
    await websocket.accept()
    try:
        while True:
            status = runner_manager.get_status()
            payload = {
                "runner_status": status.get("status", "unknown"),
                "broker_connected": bool(status.get("broker_connected", False)),
                "poll_success_count": int(status.get("poll_success_count", 0)),
                "poll_error_count": int(status.get("poll_error_count", 0)),
                "last_poll_error": str(status.get("last_poll_error", "")),
                "last_successful_poll_at": status.get("last_successful_poll_at"),
                "sleeping": bool(status.get("sleeping", False)),
                "sleep_since": status.get("sleep_since"),
                "next_market_open_at": status.get("next_market_open_at"),
                "last_resume_at": status.get("last_resume_at"),
                "market_session_open": status.get("market_session_open"),
                "kill_switch_active": get_global_kill_switch(),
                "last_broker_sync_at": _get_last_broker_sync(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await websocket.send_json(payload)
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        return


@router.post("/runner/start", response_model=RunnerActionResponse)
async def start_runner(
    request: Optional[RunnerStartRequest] = None,
    db: Session = Depends(get_db),
    x_idempotency_key: Optional[str] = Header(default=None),
):
    """
    Start the strategy runner.
    Loads active strategies and begins execution loop.
    Idempotent - safe to call multiple times.
    """
    cached = _idempotency_cache_get("/runner/start", x_idempotency_key)
    if cached is not None:
        return RunnerActionResponse(**cached)

    storage = StorageService(db)
    config = _load_runtime_config(storage)
    _set_config_snapshot(config)
    set_global_trading_enabled(bool(config.trading_enabled))
    if not config.trading_enabled:
        active_strategy_count = len(storage.get_active_strategies())
        if active_strategy_count > 0:
            mode = "paper" if bool(config.paper_trading) else "live"
            payload = {
                "success": False,
                "message": (
                    "Trading is disabled in Settings. "
                    f"{mode.title()} mode only selects the account mode; "
                    "turn on Trading Enabled and save Settings before starting runner."
                ),
                "status": "stopped",
            }
            _idempotency_cache_set("/runner/start", x_idempotency_key, payload)
            return RunnerActionResponse(**payload)
    try:
        broker = get_broker()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    max_position_size, risk_limit_daily = _balance_adjusted_limits(
        broker=broker,
        requested_max_position_size=config.max_position_size,
        requested_risk_limit_daily=config.risk_limit_daily,
    )
    mode = "paper" if config.paper_trading else "live"
    require_real_data = bool(config.strict_alpaca_data and str(config.broker).lower() == "alpaca")
    alpaca_creds = _resolve_alpaca_credentials_for_mode(mode) if str(config.broker).lower() == "alpaca" else None
    if require_real_data and not alpaca_creds:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Strict Alpaca data mode is enabled for {mode} but Alpaca credentials are unavailable. "
                "Load/save Alpaca keys in Settings before starting runner."
            ),
        )
    workspace_symbols_override: Optional[List[str]] = None
    if request is not None and bool(request.use_workspace_universe):
        prefs = _load_trading_preferences(storage)
        account_snapshot = _load_account_snapshot(broker)
        equity = _safe_float(account_snapshot.get("equity", 0.0), 0.0)
        buying_power = _safe_float(account_snapshot.get("buying_power", 0.0), 0.0)
        synthetic_initial_capital = max(
            100.0,
            buying_power if buying_power > 0 else (
                equity if equity > 0 else (_safe_float(prefs.weekly_budget, 200.0) * 4.0)
            ),
        )
        today = datetime.now(timezone.utc).date().isoformat()
        workspace_request = BacktestRequest(
            start_date=today,
            end_date=today,
            initial_capital=synthetic_initial_capital,
            use_workspace_universe=True,
            asset_type=request.asset_type,
            screener_mode=request.screener_mode,
            stock_preset=request.stock_preset,
            etf_preset=request.etf_preset,
            screener_limit=request.screener_limit,
            seed_only=request.seed_only,
            preset_universe_mode=request.preset_universe_mode,
            min_dollar_volume=request.min_dollar_volume,
            max_spread_bps=request.max_spread_bps,
            max_sector_weight_pct=request.max_sector_weight_pct,
            auto_regime_adjust=request.auto_regime_adjust,
        )
        screener = MarketScreener(
            alpaca_client=alpaca_creds,
            require_real_data=require_real_data,
        )
        try:
            workspace_symbols_override, _ = _resolve_workspace_universe_for_backtest(
                storage=storage,
                screener=screener,
                prefs=prefs,
                request=workspace_request,
                broker=broker,
                initial_capital=synthetic_initial_capital,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        if not workspace_symbols_override:
            raise HTTPException(
                status_code=400,
                detail="Workspace universe resolution produced zero symbols. Adjust Screener settings or switch Runner Universe Source.",
            )
    result = runner_manager.start_runner(
        db=db,
        broker=broker,
        max_position_size=max_position_size,
        risk_limit_daily=risk_limit_daily,
        tick_interval=config.tick_interval_seconds,
        streaming_enabled=config.streaming_enabled,
        alpaca_client=alpaca_creds,
        require_real_data=require_real_data,
        symbol_universe_override=workspace_symbols_override,
    )
    _idempotency_cache_set("/runner/start", x_idempotency_key, result)
    return RunnerActionResponse(**result)


@router.post("/runner/stop", response_model=RunnerActionResponse)
async def stop_runner(
    db: Session = Depends(get_db),
    x_idempotency_key: Optional[str] = Header(default=None),
):
    """
    Stop the strategy runner.
    Stops all strategies and the execution loop.
    Idempotent - safe to call multiple times.
    """
    cached = _idempotency_cache_get("/runner/stop", x_idempotency_key)
    if cached is not None:
        return RunnerActionResponse(**cached)
    result = runner_manager.stop_runner(db=db)
    _idempotency_cache_set("/runner/stop", x_idempotency_key, result)
    return RunnerActionResponse(**result)


@router.post("/portfolio/selloff", response_model=RunnerActionResponse)
async def selloff_all_positions(x_idempotency_key: Optional[str] = Header(default=None)):
    """
    Explicitly liquidate all open positions.
    This is opt-in and not triggered automatically on strategy switches.
    """
    try:
        cached = _idempotency_cache_get("/portfolio/selloff", x_idempotency_key)
        if cached is not None:
            return RunnerActionResponse(**cached)
        broker = get_broker()
        positions = broker.get_positions()
        closed = 0
        for pos in positions:
            qty = float(pos.get("quantity", 0))
            if qty == 0:
                continue
            side = "sell" if qty > 0 else "buy"
            broker.submit_order(
                symbol=pos.get("symbol"),
                side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=abs(qty),
                price=None,
            )
            closed += 1

        response = RunnerActionResponse(
            success=True,
            message=f"Closed {closed} position(s)",
            status="stopped",
        )
        _idempotency_cache_set("/portfolio/selloff", x_idempotency_key, response.model_dump())
        return response
    except (RuntimeError, ValueError, TypeError) as e:
        return RunnerActionResponse(
            success=False,
            message=f"Selloff failed: {str(e)}",
            status="error",
        )


# ============================================================================
# Portfolio Analytics Endpoints
# ============================================================================

@router.get("/analytics/portfolio")
async def get_portfolio_analytics(
    days: Optional[int] = Query(default=None, ge=1, le=3650),
    db: Session = Depends(get_db)
):
    """
    Get portfolio analytics time series data.
    Returns equity curve and P&L over time.
    """
    storage = StorageService(db)

    trades = storage.get_recent_trades(limit=5000)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days is not None else None
    scoped_trades = []
    for trade in trades:
        if not trade.executed_at:
            continue
        executed_at = (
            trade.executed_at.replace(tzinfo=timezone.utc)
            if trade.executed_at.tzinfo is None
            else trade.executed_at.astimezone(timezone.utc)
        )
        if cutoff is not None and executed_at < cutoff:
            continue
        scoped_trades.append(trade)

    scoped_trades.sort(
        key=lambda trade: _ensure_utc_datetime(trade.executed_at) or datetime.min.replace(tzinfo=timezone.utc)
    )

    total_realized_pnl = sum(_safe_float(trade.realized_pnl, 0.0) for trade in scoped_trades)
    total_realized_all = sum(_safe_float(trade.realized_pnl, 0.0) for trade in trades)
    broker: Optional[BrokerInterface]
    try:
        broker = get_broker()
    except (RuntimeError, ValueError, TypeError, KeyError):
        broker = None

    # Persist live account snapshot first, then build chart from persisted snapshots.
    try:
        _capture_portfolio_snapshot(storage, broker)
    except (RuntimeError, ValueError, TypeError, KeyError):
        pass

    snapshot_rows = storage.get_portfolio_snapshots_since(cutoff=cutoff, limit=5000)
    if not snapshot_rows:
        latest_snapshot = storage.get_latest_portfolio_snapshot()
        if latest_snapshot is not None:
            snapshot_rows = [latest_snapshot]

    if snapshot_rows:
        time_series: List[Dict[str, Any]] = []
        first_equity = _safe_float(snapshot_rows[0].equity, 0.0)
        first_realized_total = _safe_float(snapshot_rows[0].realized_pnl_total, 0.0)
        previous_realized_total = first_realized_total

        for index, snapshot in enumerate(snapshot_rows):
            ts = _ensure_utc_datetime(snapshot.timestamp) or datetime.now(timezone.utc)
            equity = _safe_float(snapshot.equity, first_equity)
            realized_total = _safe_float(snapshot.realized_pnl_total, previous_realized_total)
            realized_pnl_delta = 0.0 if index == 0 else (realized_total - previous_realized_total)
            cumulative_pnl = realized_total - first_realized_total
            time_series.append({
                "timestamp": ts.isoformat(),
                "equity": equity,
                "pnl": realized_pnl_delta,
                "cumulative_pnl": cumulative_pnl,
                "symbol": "PORTFOLIO",
            })
            previous_realized_total = realized_total

        current_equity = _safe_float(snapshot_rows[-1].equity, 0.0)
        if current_equity <= 0.0:
            account_snapshot = _load_account_snapshot(broker)
            current_equity = _safe_float(account_snapshot.get("equity", 0.0), 0.0)

        return {
            "time_series": time_series,
            "total_trades": len(scoped_trades),
            "current_equity": current_equity,
            "total_pnl": total_realized_pnl,
        }

    holdings_snapshot = _load_holdings_snapshot(storage, broker)
    holdings_value = sum(_safe_float(h.get("market_value", 0.0), 0.0) for h in holdings_snapshot)
    account_snapshot = _load_account_snapshot(broker)
    current_equity = _safe_float(account_snapshot.get("equity", 0.0), 0.0)
    if current_equity <= 0.0:
        current_equity = max(0.0, holdings_value + total_realized_all)

    time_series = []
    cumulative_pnl = 0.0
    opening_equity = max(0.0, current_equity - total_realized_pnl)
    if not scoped_trades and current_equity > 0.0:
        opening_equity = current_equity
    equity = opening_equity

    if scoped_trades:
        baseline_ts = (
            cutoff
            if cutoff is not None
            else (_ensure_utc_datetime(scoped_trades[0].executed_at) or datetime.now(timezone.utc))
        )
    else:
        baseline_ts = cutoff or datetime.now(timezone.utc)
    time_series.append({
        "timestamp": baseline_ts.isoformat(),
        "equity": opening_equity,
        "pnl": 0.0,
        "cumulative_pnl": 0.0,
        "symbol": "PORTFOLIO",
    })

    for trade in scoped_trades:
        realized_pnl = _safe_float(trade.realized_pnl, 0.0)
        cumulative_pnl += realized_pnl
        equity += realized_pnl
        executed_at = _ensure_utc_datetime(trade.executed_at) or datetime.now(timezone.utc)

        time_series.append({
            "timestamp": executed_at.isoformat(),
            "equity": equity,
            "pnl": realized_pnl,
            "cumulative_pnl": cumulative_pnl,
            "symbol": trade.symbol,
        })

    return {
        "time_series": time_series,
        "total_trades": len(scoped_trades),
        "current_equity": current_equity,
        "total_pnl": cumulative_pnl,
    }


@router.get("/analytics/summary")
async def get_portfolio_summary(db: Session = Depends(get_db)):
    """
    Get portfolio summary statistics.
    Returns aggregate metrics and performance stats.
    """
    storage = StorageService(db)

    broker: Optional[BrokerInterface]
    try:
        broker = get_broker()
    except (RuntimeError, ValueError, TypeError, KeyError):
        broker = None

    try:
        _capture_portfolio_snapshot(storage, broker)
    except (RuntimeError, ValueError, TypeError, KeyError):
        pass

    holdings_snapshot = _load_holdings_snapshot(storage, broker)
    account_snapshot = _load_account_snapshot(broker)
    positions = storage.get_open_positions()
    trades = storage.get_recent_trades(limit=1000)

    total_trades = len(trades)
    total_pnl = sum(t.realized_pnl or 0.0 for t in trades)
    winning_trades = len([t for t in trades if (t.realized_pnl or 0.0) > 0])
    losing_trades = len([t for t in trades if (t.realized_pnl or 0.0) < 0])
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

    total_position_value = sum(_safe_float(h.get("market_value", 0.0), 0.0) for h in holdings_snapshot)
    total_positions = len(holdings_snapshot) if holdings_snapshot else len(positions)
    equity = _safe_float(account_snapshot.get("equity", 0.0), 0.0)
    if equity <= 0.0:
        latest_snapshot = storage.get_latest_portfolio_snapshot()
        if latest_snapshot is not None:
            equity = _safe_float(latest_snapshot.equity, 0.0)
        if equity <= 0.0:
            equity = max(0.0, total_position_value + total_pnl)

    return {
        'total_trades': total_trades,
        'total_pnl': total_pnl,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': win_rate,
        'total_positions': total_positions,
        'total_position_value': total_position_value,
        'equity': equity,
    }


# ============================================================================
# Strategy Configuration Endpoints
# ============================================================================

def _adaptive_strategy_parameter_defaults(
    storage: StorageService,
    symbol_count: int,
) -> Dict[str, float]:
    """
    Compute portfolio-aware default parameter values for Strategy UI.

    These defaults are used when a strategy parameter has not been explicitly
    saved yet, so Strategy config forms reflect the current preset + account
    context.
    """
    prefs = _load_trading_preferences(storage)
    prefs_payload = {
        "asset_type": prefs.asset_type.value,
        "stock_preset": prefs.stock_preset.value,
        "etf_preset": prefs.etf_preset.value,
    }
    defaults = runner_manager._strategy_param_defaults_from_prefs(prefs_payload)

    broker: Optional[BrokerInterface]
    try:
        broker = get_broker()
    except (RuntimeError, ValueError, TypeError, KeyError):
        broker = None
    account_snapshot = _load_account_snapshot(broker)
    equity = _safe_float(account_snapshot.get("equity", 0.0), 0.0)
    buying_power = _safe_float(account_snapshot.get("buying_power", 0.0), 0.0)
    weekly_budget = _safe_float(prefs.weekly_budget, 200.0)
    budget_tracker = get_budget_tracker(weekly_budget)
    budget_tracker.set_weekly_budget(weekly_budget)
    remaining_weekly_budget = _safe_float(
        budget_tracker.get_budget_status().get("remaining_budget", weekly_budget),
        weekly_budget,
    )
    existing_position_count = len(storage.get_open_positions())

    adaptive_position_size = runner_manager._dynamic_position_size(
        requested_position_size=_safe_float(defaults.get("position_size", 1000.0), 1000.0),
        symbol_count=max(1, int(symbol_count)),
        existing_position_count=existing_position_count,
        remaining_weekly_budget=remaining_weekly_budget,
        buying_power=buying_power,
        equity=equity,
        risk_per_trade_pct=_safe_float(defaults.get("risk_per_trade", 1.0), 1.0),
    )
    defaults["position_size"] = adaptive_position_size
    return defaults


def _resolve_backtest_asset_type(
    request_asset_type: Optional[str],
    prefs: TradingPreferencesResponse,
) -> AssetType:
    """Resolve workspace asset type for backtest universe generation."""
    if request_asset_type in {"stock", "etf"}:
        return AssetType(request_asset_type)
    if prefs.asset_type in (AssetType.STOCK, AssetType.ETF):
        return prefs.asset_type
    # AssetType.BOTH is unsupported for preset backtesting; choose stock default.
    return AssetType.STOCK


def _resolve_workspace_universe_for_backtest(
    storage: StorageService,
    screener: MarketScreener,
    prefs: TradingPreferencesResponse,
    request: BacktestRequest,
    broker: Optional[BrokerInterface],
    initial_capital: float,
) -> tuple[List[str], Dict[str, Any]]:
    """
    Build a backtest symbol universe from screener workspace controls.

    Mirrors Screener universe mode + guardrails so backtest and runner inputs stay aligned.
    """
    final_asset_type = _resolve_backtest_asset_type(request.asset_type, prefs)
    requested_mode = request.screener_mode
    if final_asset_type == AssetType.ETF:
        final_mode = ScreenerMode.PRESET
    elif requested_mode in {"most_active", "preset"}:
        final_mode = ScreenerMode(requested_mode)
    else:
        final_mode = prefs.screener_mode if prefs.screener_mode in (ScreenerMode.MOST_ACTIVE, ScreenerMode.PRESET) else ScreenerMode.MOST_ACTIVE

    final_limit = int(request.screener_limit) if request.screener_limit is not None else int(prefs.screener_limit)
    final_limit = max(10, min(200, final_limit))
    min_dollar_volume = _safe_float(request.min_dollar_volume, 10_000_000.0)
    max_spread_bps = _safe_float(request.max_spread_bps, 50.0)
    max_sector_weight_pct = _safe_float(request.max_sector_weight_pct, 45.0)
    auto_regime_adjust = True if request.auto_regime_adjust is None else bool(request.auto_regime_adjust)

    resolved_preset_universe_mode = "seed_guardrail_blend"
    resolved_preset_name: Optional[str] = None

    if final_mode == ScreenerMode.PRESET:
        if final_asset_type == AssetType.STOCK:
            resolved_preset_name = str(request.stock_preset or prefs.stock_preset.value).strip().lower()
            valid_stock = {"weekly_optimized", "three_to_five_weekly", "monthly_optimized", "small_budget_weekly", "micro_budget"}
            if resolved_preset_name not in valid_stock:
                resolved_preset_name = prefs.stock_preset.value
        else:
            resolved_preset_name = str(request.etf_preset or prefs.etf_preset.value).strip().lower()
            valid_etf = {"conservative", "balanced", "aggressive"}
            if resolved_preset_name not in valid_etf:
                resolved_preset_name = prefs.etf_preset.value

        mode_candidate = (
            str(request.preset_universe_mode).strip().lower()
            if request.preset_universe_mode is not None
            else ("seed_only" if bool(request.seed_only) else "seed_guardrail_blend")
        )
        if mode_candidate not in {"seed_only", "seed_guardrail_blend", "guardrail_only"}:
            raise HTTPException(
                status_code=400,
                detail="preset_universe_mode must be one of: seed_only, seed_guardrail_blend, guardrail_only",
            )
        resolved_preset_universe_mode = mode_candidate

        preset_guardrails = screener.get_preset_guardrails(final_asset_type.value, resolved_preset_name)
        min_dollar_volume = max(min_dollar_volume, float(preset_guardrails["min_dollar_volume"]))
        max_spread_bps = min(max_spread_bps, float(preset_guardrails["max_spread_bps"]))
        max_sector_weight_pct = min(max_sector_weight_pct, float(preset_guardrails["max_sector_weight_pct"]))
        assets_raw = screener.get_preset_assets(
            final_asset_type.value,
            resolved_preset_name,
            final_limit,
            seed_only=resolved_preset_universe_mode == "seed_only",
            preset_universe_mode=resolved_preset_universe_mode,
        )
    else:
        from services.market_screener import AssetType as ScreenerAssetType

        assets_raw = screener.get_screener_results(
            ScreenerAssetType(final_asset_type.value),
            final_limit,
        )

    regime = screener.detect_market_regime()
    strategy_defaults = _adaptive_strategy_parameter_defaults(storage, max(1, final_limit))
    target_position_size = runner_manager._dynamic_position_size(
        requested_position_size=_safe_float(strategy_defaults.get("position_size", 1000.0), 1000.0),
        symbol_count=max(1, final_limit),
        existing_position_count=0,
        remaining_weekly_budget=_safe_float(prefs.weekly_budget, 200.0),
        buying_power=max(0.0, float(initial_capital)),
        equity=max(0.0, float(initial_capital)),
        risk_per_trade_pct=_safe_float(strategy_defaults.get("risk_per_trade", 1.0), 1.0),
        stop_loss_pct=_safe_float(strategy_defaults.get("stop_loss_pct", 2.0), 2.0),
    )
    dca_tranches = max(1, int(_safe_float(strategy_defaults.get("dca_tranches", 1), 1)))
    synthetic_account = {
        "equity": max(0.0, float(initial_capital)),
        "buying_power": max(0.0, float(initial_capital)),
    }
    require_fractionable = _should_require_fractionable_symbols(final_asset_type, prefs, synthetic_account)
    enforce_execution_capabilities = bool(final_asset_type == AssetType.STOCK and require_fractionable)
    symbol_capabilities = (
        _collect_symbol_capabilities(broker, assets_raw)
        if enforce_execution_capabilities
        else {}
    )
    optimized = screener.optimize_assets(
        assets_raw,
        limit=final_limit,
        min_dollar_volume=min_dollar_volume,
        max_spread_bps=max_spread_bps,
        max_sector_weight_pct=max_sector_weight_pct,
        regime=regime,
        auto_regime_adjust=auto_regime_adjust,
        current_holdings=[],
        buying_power=max(0.0, float(initial_capital)),
        equity=max(0.0, float(initial_capital)),
        weekly_budget=_safe_float(prefs.weekly_budget, 200.0),
        symbol_capabilities=symbol_capabilities,
        require_broker_tradable=enforce_execution_capabilities,
        require_fractionable=require_fractionable,
        target_position_size=target_position_size,
        dca_tranches=dca_tranches,
    )
    symbols = _normalize_symbols([str(asset.get("symbol", "")).upper() for asset in optimized if asset.get("symbol")])
    selected_capabilities = {
        symbol: {
            "tradable": bool((symbol_capabilities.get(symbol) or {}).get("tradable", True)),
            "fractionable": bool((symbol_capabilities.get(symbol) or {}).get("fractionable", True)),
        }
        for symbol in symbols
    }
    context = {
        "symbols_source": "workspace_universe",
        "asset_type": final_asset_type.value,
        "screener_mode": final_mode.value,
        "preset": resolved_preset_name,
        "preset_universe_mode": resolved_preset_universe_mode if final_mode == ScreenerMode.PRESET else None,
        "screener_limit": final_limit,
        "guardrails": {
            "min_dollar_volume": min_dollar_volume,
            "max_spread_bps": max_spread_bps,
            "max_sector_weight_pct": max_sector_weight_pct,
            "auto_regime_adjust": auto_regime_adjust,
        },
        "market_regime": regime,
        "data_source": screener.get_last_source(),
        "require_fractionable": require_fractionable,
        "require_broker_tradable": enforce_execution_capabilities,
        "target_position_size": target_position_size,
        "dca_tranches": dca_tranches,
        "symbol_capabilities": selected_capabilities,
    }
    return symbols, context


def _resolve_strategy_backtest_parameters(
    db_strategy: Any,
    request_parameters: Optional[Dict[str, float]],
) -> Dict[str, float]:
    """Resolve backtest parameters from strategy config with request overrides."""
    default_params = get_default_parameters()
    param_defs = {param.name: param for param in default_params}
    resolved_parameters: Dict[str, float] = {}
    if db_strategy.config and isinstance(db_strategy.config.get("parameters"), dict):
        for name, value in db_strategy.config.get("parameters", {}).items():
            if name not in param_defs:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(numeric):
                continue
            pdef = param_defs[name]
            resolved_parameters[name] = max(pdef.min_value, min(pdef.max_value, numeric))
    if request_parameters:
        for name, value in request_parameters.items():
            if name not in param_defs:
                raise HTTPException(status_code=400, detail=f"Unknown backtest parameter: {name}")
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"Backtest parameter {name} must be numeric")
            if not math.isfinite(numeric):
                raise HTTPException(status_code=400, detail=f"Backtest parameter {name} must be finite")
            pdef = param_defs[name]
            if not (pdef.min_value <= numeric <= pdef.max_value):
                raise HTTPException(
                    status_code=400,
                    detail=f"Backtest parameter {name} must be within [{pdef.min_value}, {pdef.max_value}]",
                )
            resolved_parameters[name] = numeric
    return resolved_parameters


def _prepare_backtest_execution_context(
    *,
    storage: StorageService,
    db_strategy: Any,
    request: BacktestRequest,
) -> Dict[str, Any]:
    """Prepare validated backtest execution context shared by backtest/optimizer flows."""
    prefs = _load_trading_preferences(storage)
    emulate_live_trading = bool(request.emulate_live_trading)

    selected_symbols = list(request.symbols or [])
    if not selected_symbols and db_strategy.config:
        selected_symbols = list(db_strategy.config.get("symbols", ["AAPL", "MSFT"]))
    selected_symbols = _normalize_symbols(selected_symbols)
    if not selected_symbols:
        raise HTTPException(status_code=400, detail="At least one valid symbol is required for backtest")

    _bt_config = _get_config_snapshot()
    _bt_mode = "paper" if _bt_config.paper_trading else "live"
    broker_name = str(_bt_config.broker or "").strip().lower()
    if emulate_live_trading and broker_name != "alpaca":
        raise HTTPException(
            status_code=400,
            detail=(
                "Live-equivalent backtesting requires Alpaca broker mode. "
                "Set broker=alpaca in Settings, then retry."
            ),
        )
    _bt_require_real_data = bool(
        emulate_live_trading
        or (_bt_config.strict_alpaca_data and broker_name == "alpaca")
    )
    _bt_creds = _resolve_alpaca_credentials_for_mode(_bt_mode)
    if _bt_require_real_data and not _bt_creds:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Strict Alpaca data mode is enabled for {_bt_mode} but credentials are unavailable. "
                "Load/save Alpaca keys in Settings before running backtests."
            ),
        )

    broker_for_constraints: Optional[BrokerInterface] = None
    if broker_name == "alpaca":
        try:
            broker_for_constraints = get_broker()
        except RuntimeError as exc:
            if emulate_live_trading:
                raise HTTPException(status_code=400, detail=str(exc))

    universe_context: Dict[str, Any] = {
        "symbols_source": "strategy_symbols",
        "symbols_requested": len(selected_symbols),
    }
    live_parity_context: Dict[str, Any] = {
        "broker": broker_name or "unknown",
        "broker_mode": _bt_mode,
        "strict_real_data_required": _bt_require_real_data,
        "credentials_available": bool(_bt_creds),
        "workspace_universe_requested": bool(request.use_workspace_universe),
    }
    if request.use_workspace_universe:
        try:
            screener = MarketScreener(
                alpaca_client=_bt_creds,
                require_real_data=_bt_require_real_data,
            )
            selected_symbols, universe_context = _resolve_workspace_universe_for_backtest(
                storage=storage,
                screener=screener,
                prefs=prefs,
                request=request,
                broker=broker_for_constraints,
                initial_capital=float(request.initial_capital),
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        if not selected_symbols:
            raise HTTPException(
                status_code=400,
                detail="Workspace universe resolution produced zero symbols. Adjust guardrails/preset/universe mode.",
            )
    if not selected_symbols:
        raise HTTPException(status_code=400, detail="At least one valid symbol is required for backtest")

    require_fractionable = False
    symbol_capabilities: Dict[str, Dict[str, bool]] = {}
    filtered_out: List[Dict[str, str]] = []
    if emulate_live_trading:
        asset_type_for_rules = _resolve_backtest_asset_type(request.asset_type, prefs)
        if request.use_workspace_universe and universe_context.get("asset_type") in {"stock", "etf"}:
            asset_type_for_rules = AssetType(str(universe_context["asset_type"]))
        synthetic_account = {
            "equity": float(request.initial_capital),
            "buying_power": float(request.initial_capital),
        }
        require_fractionable = _should_require_fractionable_symbols(asset_type_for_rules, prefs, synthetic_account)
        if broker_for_constraints is not None:
            symbol_capabilities = _collect_symbol_capabilities(
                broker_for_constraints,
                [{"symbol": symbol} for symbol in selected_symbols],
            )
        enforced_symbols: List[str] = []
        for symbol in selected_symbols:
            capabilities = symbol_capabilities.get(symbol, {"tradable": True, "fractionable": True})
            tradable = bool(capabilities.get("tradable", True))
            fractionable = bool(capabilities.get("fractionable", True))
            if not tradable:
                filtered_out.append({"symbol": symbol, "reason": "not broker tradable"})
                continue
            if require_fractionable and not fractionable:
                filtered_out.append({"symbol": symbol, "reason": "not fractionable"})
                continue
            enforced_symbols.append(symbol)
        selected_symbols = enforced_symbols
        if not selected_symbols:
            raise HTTPException(
                status_code=400,
                detail="All candidate symbols were filtered by live execution rules (tradable/fractionable).",
            )
    universe_context["symbols_selected"] = len(selected_symbols)
    if filtered_out:
        universe_context["symbols_filtered_out"] = filtered_out[:50]

    max_position_size = float(_bt_config.max_position_size)
    risk_limit_daily = float(_bt_config.risk_limit_daily)
    if broker_for_constraints is not None:
        max_position_size, risk_limit_daily = _balance_adjusted_limits(
            broker=broker_for_constraints,
            requested_max_position_size=max_position_size,
            requested_risk_limit_daily=risk_limit_daily,
        )
    live_parity_context["require_fractionable"] = require_fractionable
    live_parity_context["symbol_capabilities_checked"] = bool(symbol_capabilities)
    live_parity_context["symbols_selected"] = len(selected_symbols)
    live_parity_context["symbols_filtered_out_count"] = len(filtered_out)
    live_parity_context["max_position_size"] = max_position_size
    live_parity_context["risk_limit_daily"] = risk_limit_daily
    universe_context["live_parity_context"] = live_parity_context

    analytics = StrategyAnalyticsService(
        storage.db,
        alpaca_creds=_bt_creds,
        require_real_data=_bt_require_real_data,
    )
    return {
        "prefs": prefs,
        "selected_symbols": selected_symbols,
        "universe_context": universe_context,
        "analytics": analytics,
        "emulate_live_trading": emulate_live_trading,
        "require_fractionable": require_fractionable,
        "symbol_capabilities": symbol_capabilities,
        "max_position_size": max_position_size,
        "risk_limit_daily": risk_limit_daily,
        "fee_bps": 0.0,
    }


def _to_backtest_response(result: Any) -> BacktestResponse:
    """Convert engine backtest result to API response model."""
    return BacktestResponse(
        strategy_id=result.strategy_id,
        start_date=result.start_date,
        end_date=result.end_date,
        initial_capital=result.initial_capital,
        final_capital=result.final_capital,
        total_return=result.total_return,
        total_trades=result.total_trades,
        winning_trades=result.winning_trades,
        losing_trades=result.losing_trades,
        win_rate=result.win_rate,
        max_drawdown=result.max_drawdown,
        sharpe_ratio=result.sharpe_ratio,
        volatility=result.volatility,
        trades=result.trades,
        equity_curve=result.equity_curve,
        diagnostics=result.diagnostics,
    )


def _compute_strategy_optimization_response(
    *,
    strategy_id: str,
    request: StrategyOptimizationRequest,
    db: Session,
    progress_callback: Optional[callable] = None,
    should_cancel: Optional[callable] = None,
) -> StrategyOptimizationResponse:
    """Run optimization and return typed response model."""
    try:
        strategy_id_int = int(strategy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid strategy ID")

    storage = StorageService(db)
    db_strategy = storage.strategies.get_by_id(strategy_id_int)
    if not db_strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    try:
        start_dt = datetime.fromisoformat(request.start_date)
        end_dt = datetime.fromisoformat(request.end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="start_date and end_date must be ISO date/time strings")
    if start_dt > end_dt:
        raise HTTPException(status_code=400, detail="start_date must be before or equal to end_date")
    if not math.isfinite(request.initial_capital):
        raise HTTPException(status_code=400, detail="initial_capital must be a finite number")
    if request.initial_capital < 100 or request.initial_capital > 100_000_000:
        raise HTTPException(status_code=400, detail="initial_capital must be within [100, 100000000]")
    if not math.isfinite(request.contribution_amount):
        raise HTTPException(status_code=400, detail="contribution_amount must be a finite number")

    backtest_request = BacktestRequest(
        start_date=request.start_date,
        end_date=request.end_date,
        initial_capital=request.initial_capital,
        contribution_amount=request.contribution_amount,
        contribution_frequency=request.contribution_frequency,
        symbols=request.symbols,
        parameters=request.parameters,
        emulate_live_trading=request.emulate_live_trading,
        use_workspace_universe=request.use_workspace_universe,
        asset_type=request.asset_type,
        screener_mode=request.screener_mode,
        stock_preset=request.stock_preset,
        etf_preset=request.etf_preset,
        screener_limit=request.screener_limit,
        seed_only=request.seed_only,
        preset_universe_mode=request.preset_universe_mode,
        min_dollar_volume=request.min_dollar_volume,
        max_spread_bps=request.max_spread_bps,
        max_sector_weight_pct=request.max_sector_weight_pct,
        auto_regime_adjust=request.auto_regime_adjust,
    )
    resolved_parameters = _resolve_strategy_backtest_parameters(
        db_strategy=db_strategy,
        request_parameters=backtest_request.parameters,
    )
    exec_context = _prepare_backtest_execution_context(
        storage=storage,
        db_strategy=db_strategy,
        request=backtest_request,
    )
    base_symbols = list(exec_context["selected_symbols"])
    symbol_capabilities = exec_context["symbol_capabilities"] or {}
    if symbol_capabilities:
        symbol_capabilities = {
            symbol: dict(symbol_capabilities.get(symbol, {"tradable": True, "fractionable": True}))
            for symbol in base_symbols
        }

    optimizer = StrategyOptimizerService(exec_context["analytics"])
    optimization_context = OptimizationContext(
        strategy_id=strategy_id,
        start_date=backtest_request.start_date,
        end_date=backtest_request.end_date,
        initial_capital=float(backtest_request.initial_capital),
        contribution_amount=float(backtest_request.contribution_amount),
        contribution_frequency=str(backtest_request.contribution_frequency),
        emulate_live_trading=bool(exec_context["emulate_live_trading"]),
        require_fractionable=bool(exec_context["require_fractionable"]),
        max_position_size=float(exec_context["max_position_size"]),
        risk_limit_daily=float(exec_context["risk_limit_daily"]),
        fee_bps=float(exec_context["fee_bps"]),
        universe_context=dict(exec_context["universe_context"]),
        symbol_capabilities=symbol_capabilities,
    )
    try:
        optimize_payload = optimizer.optimize(
            context=optimization_context,
            base_symbols=base_symbols,
            base_parameters=resolved_parameters,
            iterations=int(request.iterations),
            min_trades=int(request.min_trades),
            objective=str(request.objective),
            strict_min_trades=bool(request.strict_min_trades),
            walk_forward_enabled=bool(request.walk_forward_enabled),
            walk_forward_folds=int(request.walk_forward_folds),
            random_seed=request.random_seed,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )
    except OptimizationCancelledError:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    best_result = optimize_payload["best_result"]
    best_response = _to_backtest_response(best_result)
    top_candidates = [
        StrategyOptimizationCandidate(**row)
        for row in (optimize_payload.get("top_candidates") or [])
    ]

    response = StrategyOptimizationResponse(
        strategy_id=strategy_id,
        requested_iterations=int(optimize_payload["requested_iterations"]),
        evaluated_iterations=int(optimize_payload["evaluated_iterations"]),
        objective=str(optimize_payload["objective"]),
        score=float(optimize_payload["score"]),
        min_trades_target=int(optimize_payload.get("min_trades_target", int(request.min_trades))),
        strict_min_trades=bool(optimize_payload.get("strict_min_trades", bool(request.strict_min_trades))),
        best_candidate_meets_min_trades=bool(optimize_payload.get("best_candidate_meets_min_trades", True)),
        recommended_parameters={
            key: float(value)
            for key, value in (optimize_payload.get("recommended_parameters") or {}).items()
        },
        recommended_symbols=[
            str(symbol).upper()
            for symbol in (optimize_payload.get("recommended_symbols") or [])
            if str(symbol).strip()
        ],
        top_candidates=top_candidates,
        best_result=best_response,
        walk_forward=(
            StrategyOptimizationWalkForwardReport(**optimize_payload["walk_forward"])
            if isinstance(optimize_payload.get("walk_forward"), dict)
            else None
        ),
        notes=[str(note) for note in (optimize_payload.get("notes") or [])],
    )

    storage.create_audit_log(
        event_type="config_updated",
        description=f"Strategy optimization completed: {db_strategy.name}",
        details={
            "strategy_id": db_strategy.id,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "contribution_amount": request.contribution_amount,
            "contribution_frequency": request.contribution_frequency,
            "requested_iterations": response.requested_iterations,
            "evaluated_iterations": response.evaluated_iterations,
            "objective": response.objective,
            "min_trades_target": response.min_trades_target,
            "strict_min_trades": response.strict_min_trades,
            "recommended_symbol_count": len(response.recommended_symbols),
            "best_sharpe_ratio": response.best_result.sharpe_ratio,
            "best_total_return": response.best_result.total_return,
        },
    )
    return response


@router.get("/strategies/{strategy_id}/config", response_model=StrategyConfigResponse)
async def get_strategy_config(strategy_id: str, db: Session = Depends(get_db)):
    """
    Get detailed configuration for a specific strategy.
    Returns parameters, symbols, and settings.
    """
    storage = StorageService(db)
    
    try:
        strategy_id_int = int(strategy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid strategy ID")
    
    db_strategy = storage.strategies.get_by_id(strategy_id_int)
    if not db_strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    symbols = db_strategy.config.get('symbols', []) if db_strategy.config else []
    normalized_symbols = _normalize_symbols(symbols if isinstance(symbols, list) else [])
    # Get parameters from config or use adaptive defaults
    config_params = db_strategy.config.get('parameters', {}) if db_strategy.config else {}
    adaptive_defaults = _adaptive_strategy_parameter_defaults(storage, symbol_count=len(normalized_symbols))
    default_params = get_default_parameters()
    
    # Merge with stored values and convert to API models
    parameters = []
    for param in default_params:
        if param.name in adaptive_defaults:
            param.value = _safe_float(adaptive_defaults[param.name], param.value)
        if param.name in config_params:
            param.value = _safe_float(config_params[param.name], param.value)
        # Convert to API model
        parameters.append(StrategyParameter(
            name=param.name,
            value=param.value,
            min_value=param.min_value,
            max_value=param.max_value,
            step=param.step,
            description=param.description,
        ))
    
    return StrategyConfigResponse(
        strategy_id=str(db_strategy.id),
        name=db_strategy.name,
        description=db_strategy.description or "",
        symbols=normalized_symbols,
        parameters=parameters,
        enabled=db_strategy.is_enabled,
    )


@router.put("/strategies/{strategy_id}/config", response_model=StrategyConfigResponse)
async def update_strategy_config(
    strategy_id: str,
    request: StrategyConfigUpdateRequest,
    db: Session = Depends(get_db)
):
    """
    Update strategy configuration including symbols and parameters.
    """
    storage = StorageService(db)
    
    try:
        strategy_id_int = int(strategy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid strategy ID")
    
    db_strategy = storage.strategies.get_by_id(strategy_id_int)
    if not db_strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    default_params = get_default_parameters()
    param_defs = {param.name: param for param in default_params}
    
    # Update config
    if not db_strategy.config:
        db_strategy.config = {}
    
    config_changed = False
    if request.symbols is not None:
        normalized_symbols = _normalize_symbols(request.symbols)
        db_strategy.config['symbols'] = normalized_symbols
        config_changed = True
    
    if request.parameters is not None:
        if 'parameters' not in db_strategy.config:
            db_strategy.config['parameters'] = {}
        for param_name, param_value in request.parameters.items():
            if param_name not in param_defs:
                raise HTTPException(status_code=400, detail=f"Unknown strategy parameter: {param_name}")
            if not math.isfinite(param_value):
                raise HTTPException(status_code=400, detail=f"Parameter {param_name} must be finite")
            param_def = param_defs[param_name]
            if not (param_def.min_value <= param_value <= param_def.max_value):
                raise HTTPException(
                    status_code=400,
                    detail=f"Parameter {param_name} must be within [{param_def.min_value}, {param_def.max_value}]",
                )
            db_strategy.config['parameters'][param_name] = param_value
        config_changed = True
    
    if request.enabled is not None:
        db_strategy.is_enabled = request.enabled
        if request.enabled is False and db_strategy.is_active:
            db_strategy.is_active = False
            storage.create_audit_log(
                event_type="strategy_stopped",
                description=f"Strategy auto-stopped because it was disabled: {db_strategy.name}",
                details={"strategy_id": db_strategy.id},
            )
    
    # Mark config as modified if changed (needed for SQLAlchemy JSON fields)
    if config_changed:
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(db_strategy, 'config')
    
    # Save changes
    db_strategy = storage.strategies.update(db_strategy)
    
    storage.create_audit_log(
        event_type="config_updated",
        description=f"Strategy config updated: {db_strategy.name}",
        details={"strategy_id": db_strategy.id, "updates": request.model_dump(exclude_none=True)},
    )
    
    # Return updated config
    return await get_strategy_config(strategy_id, db)


# ============================================================================
# Strategy Metrics Endpoints
# ============================================================================

@router.get("/strategies/{strategy_id}/metrics", response_model=StrategyMetricsResponse)
async def get_strategy_metrics(strategy_id: str, db: Session = Depends(get_db)):
    """
    Get real-time performance metrics for a strategy.
    Returns win rate, volatility, drawdown, and other key metrics.
    """
    try:
        strategy_id_int = int(strategy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid strategy ID")
    
    storage = StorageService(db)
    db_strategy = storage.strategies.get_by_id(strategy_id_int)
    if not db_strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    # Calculate metrics using analytics service
    analytics = StrategyAnalyticsService(db)
    metrics = analytics.get_strategy_metrics(strategy_id_int)
    
    return StrategyMetricsResponse(
        strategy_id=metrics.strategy_id,
        win_rate=metrics.win_rate,
        volatility=metrics.volatility,
        drawdown=metrics.drawdown,
        total_trades=metrics.total_trades,
        winning_trades=metrics.winning_trades,
        losing_trades=metrics.losing_trades,
        total_pnl=metrics.total_pnl,
        sharpe_ratio=metrics.sharpe_ratio,
        updated_at=_ensure_utc_datetime(metrics.updated_at),
    )


# ============================================================================
# Strategy Backtesting Endpoints
# ============================================================================

@router.post("/strategies/{strategy_id}/backtest", response_model=BacktestResponse)
async def run_strategy_backtest(
    strategy_id: str,
    request: BacktestRequest,
    db: Session = Depends(get_db)
):
    """
    Run a backtest for the strategy with specified parameters.
    Returns simulated performance metrics and trade history.
    """
    try:
        strategy_id_int = int(strategy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid strategy ID")
    
    storage = StorageService(db)
    db_strategy = storage.strategies.get_by_id(strategy_id_int)
    if not db_strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    try:
        start_dt = datetime.fromisoformat(request.start_date)
        end_dt = datetime.fromisoformat(request.end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="start_date and end_date must be ISO date/time strings")
    if start_dt > end_dt:
        raise HTTPException(status_code=400, detail="start_date must be before or equal to end_date")
    if not math.isfinite(request.initial_capital):
        raise HTTPException(status_code=400, detail="initial_capital must be a finite number")
    if request.initial_capital < 100 or request.initial_capital > 100_000_000:
        raise HTTPException(status_code=400, detail="initial_capital must be within [100, 100000000]")
    
    resolved_parameters = _resolve_strategy_backtest_parameters(
        db_strategy=db_strategy,
        request_parameters=request.parameters,
    )
    exec_context = _prepare_backtest_execution_context(
        storage=storage,
        db_strategy=db_strategy,
        request=request,
    )
    from config.strategy_config import BacktestRequest as BacktestReq
    
    backtest_req = BacktestReq(
        strategy_id=strategy_id,
        start_date=request.start_date,
        end_date=request.end_date,
        initial_capital=request.initial_capital,
        contribution_amount=request.contribution_amount,
        contribution_frequency=request.contribution_frequency,
        symbols=exec_context["selected_symbols"],
        parameters=resolved_parameters or None,
        emulate_live_trading=exec_context["emulate_live_trading"],
        symbol_capabilities=exec_context["symbol_capabilities"] or None,
        require_fractionable=exec_context["require_fractionable"],
        max_position_size=exec_context["max_position_size"],
        risk_limit_daily=exec_context["risk_limit_daily"],
        fee_bps=exec_context["fee_bps"],
        universe_context=exec_context["universe_context"],
    )
    
    try:
        result = exec_context["analytics"].run_backtest(backtest_req)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    
    storage.create_audit_log(
        event_type="strategy_started",
        description=f"Backtest completed for strategy: {db_strategy.name}",
        details={
            "strategy_id": db_strategy.id,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "contribution_amount": request.contribution_amount,
            "contribution_frequency": request.contribution_frequency,
            "total_trades": result.total_trades,
            "win_rate": result.win_rate,
            "emulate_live_trading": exec_context["emulate_live_trading"],
            "symbols_source": exec_context["universe_context"].get("symbols_source"),
            "symbols_selected": exec_context["universe_context"].get("symbols_selected"),
        },
    )
    return _to_backtest_response(result)


@router.post("/strategies/{strategy_id}/optimize", response_model=StrategyOptimizationResponse)
async def optimize_strategy_configuration(
    strategy_id: str,
    request: StrategyOptimizationRequest,
    db: Session = Depends(get_db),
):
    """
    Run parameter + symbol optimization for a strategy using historical backtests.

    Uses the same backtest engine and live-equivalence controls as /backtest,
    then recommends an objective-optimized parameter/symbol set.
    """
    return _compute_strategy_optimization_response(
        strategy_id=strategy_id,
        request=request,
        db=db,
    )


def _run_optimizer_job(job_id: str) -> None:
    """Background worker for async optimizer jobs."""
    started_at = datetime.now(timezone.utc).isoformat()
    _optimizer_update_job(
        job_id,
        {
            "status": "running",
            "started_at": started_at,
            "message": "Running parameter search",
        },
    )

    def _should_cancel() -> bool:
        row = _optimizer_get_job(job_id)
        return bool(row and row.get("cancel_requested"))

    def _progress_update(completed: int, total: int, stage: str) -> None:
        row = _optimizer_get_job(job_id)
        if not row:
            return
        if row.get("started_at"):
            elapsed = max(
                0.0,
                (datetime.now(timezone.utc) - datetime.fromisoformat(str(row["started_at"]))).total_seconds(),
            )
        else:
            elapsed = 0.0
        total_safe = max(1, int(total))
        completed_safe = max(0, min(int(completed), total_safe))
        progress_pct = (completed_safe / total_safe) * 100.0
        avg = (elapsed / completed_safe) if completed_safe > 0 else None
        eta = (avg * (total_safe - completed_safe)) if avg is not None else None
        stage_label = {
            "initializing": "Initializing optimizer",
            "parameter_search": "Evaluating parameter candidates",
            "symbol_trim": "Testing symbol universe trims",
            "walk_forward": "Running walk-forward validation",
            "finalizing": "Finalizing best candidate",
        }.get(stage, "Running optimizer")
        _optimizer_update_job(
            job_id,
            {
                "status": "running",
                "progress_pct": round(progress_pct, 2),
                "completed_iterations": completed_safe,
                "total_iterations": total_safe,
                "elapsed_seconds": round(elapsed, 3),
                "eta_seconds": round(eta, 3) if eta is not None else None,
                "avg_seconds_per_iteration": round(avg, 3) if avg is not None else None,
                "message": stage_label,
            },
        )

    row = _optimizer_get_job(job_id)
    if not row:
        return
    strategy_id = str(row.get("strategy_id"))
    request_payload = row.get("request") or {}
    try:
        request = StrategyOptimizationRequest(**request_payload)
    except Exception as exc:
        _optimizer_update_job(
            job_id,
            {
                "status": "failed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "message": "Invalid request payload",
                "error": str(exc),
            },
        )
        return

    db = SessionLocal()
    try:
        response = _compute_strategy_optimization_response(
            strategy_id=strategy_id,
            request=request,
            db=db,
            progress_callback=_progress_update,
            should_cancel=_should_cancel,
        )
        _optimizer_update_job(
            job_id,
            {
                "status": "completed",
                "progress_pct": 100.0,
                "completed_iterations": max(
                    int(_optimizer_get_job(job_id).get("completed_iterations") if _optimizer_get_job(job_id) else 0),
                    int(response.evaluated_iterations),
                ),
                "total_iterations": max(
                    int(_optimizer_get_job(job_id).get("total_iterations") if _optimizer_get_job(job_id) else 0),
                    int(response.evaluated_iterations),
                ),
                "eta_seconds": 0.0,
                "message": "Completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "result": response.model_dump(),
            },
        )
    except OptimizationCancelledError:
        _optimizer_update_job(
            job_id,
            {
                "status": "canceled",
                "message": "Canceled by user",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            },
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail)
        status = "canceled" if _should_cancel() else "failed"
        _optimizer_update_job(
            job_id,
            {
                "status": status,
                "message": "Canceled by user" if status == "canceled" else "Failed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": detail,
            },
        )
    except Exception as exc:
        status = "canceled" if _should_cancel() else "failed"
        _optimizer_update_job(
            job_id,
            {
                "status": status,
                "message": "Canceled by user" if status == "canceled" else "Failed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            },
        )
    finally:
        db.close()


@router.post("/strategies/{strategy_id}/optimize/start", response_model=StrategyOptimizationJobStartResponse)
async def start_strategy_optimization_job(
    strategy_id: str,
    request: StrategyOptimizationRequest,
    db: Session = Depends(get_db),
):
    """Start async optimizer job and return job id for status polling."""
    try:
        strategy_id_int = int(strategy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid strategy ID")
    storage = StorageService(db)
    db_strategy = storage.strategies.get_by_id(strategy_id_int)
    if not db_strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    payload = request.model_dump(exclude_none=True)
    job = _optimizer_create_job(strategy_id=strategy_id, request_payload=payload)
    thread = threading.Thread(
        target=_run_optimizer_job,
        args=(str(job["job_id"]),),
        daemon=True,
        name=f"optimizer-{job['job_id']}",
    )
    thread.start()
    return StrategyOptimizationJobStartResponse(
        job_id=str(job["job_id"]),
        strategy_id=str(strategy_id),
        status="queued",
        created_at=str(job["created_at"]),
    )


@router.get("/strategies/{strategy_id}/optimize/{job_id}", response_model=StrategyOptimizationJobStatusResponse)
async def get_strategy_optimization_job_status(strategy_id: str, job_id: str):
    """Fetch current async optimizer job status."""
    row = _optimizer_get_job(job_id)
    if not row or str(row.get("strategy_id")) != str(strategy_id):
        raise HTTPException(status_code=404, detail="Optimization job not found")
    return _optimizer_progress_snapshot(row)


@router.post("/strategies/{strategy_id}/optimize/{job_id}/cancel", response_model=StrategyOptimizationJobCancelResponse)
async def cancel_strategy_optimization_job(strategy_id: str, job_id: str):
    """Request cancellation for an async optimizer job."""
    row = _optimizer_get_job(job_id)
    if not row or str(row.get("strategy_id")) != str(strategy_id):
        raise HTTPException(status_code=404, detail="Optimization job not found")
    status = str(row.get("status") or "failed")
    if status in {"completed", "failed", "canceled"}:
        return StrategyOptimizationJobCancelResponse(
            success=False,
            job_id=job_id,
            strategy_id=strategy_id,
            status=status,  # type: ignore[arg-type]
            message=f"Job already {status}",
        )
    updated = _optimizer_update_job(
        job_id,
        {
            "cancel_requested": True,
            "message": "Cancel requested",
        },
    ) or row
    return StrategyOptimizationJobCancelResponse(
        success=True,
        job_id=job_id,
        strategy_id=strategy_id,
        status=str(updated.get("status") or "running"),  # type: ignore[arg-type]
        message="Cancellation requested",
    )


# ============================================================================
# Parameter Tuning Endpoints
# ============================================================================

@router.post("/strategies/{strategy_id}/tune", response_model=ParameterTuneResponse)
async def tune_strategy_parameter(
    strategy_id: str,
    request: ParameterTuneRequest,
    db: Session = Depends(get_db)
):
    """
    Tune a specific strategy parameter.
    Updates the parameter value and validates against constraints.
    """
    try:
        strategy_id_int = int(strategy_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid strategy ID")
    
    storage = StorageService(db)
    db_strategy = storage.strategies.get_by_id(strategy_id_int)
    if not db_strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    # Get default parameters to validate constraints
    default_params = get_default_parameters()
    param_def = next((p for p in default_params if p.name == request.parameter_name), None)
    
    if not param_def:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown parameter: {request.parameter_name}"
        )
    
    # Validate value is within bounds
    if not (param_def.min_value <= request.value <= param_def.max_value):
        raise HTTPException(
            status_code=400,
            detail=f"Value {request.value} outside allowed range [{param_def.min_value}, {param_def.max_value}]"
        )
    
    # Update parameter
    if not db_strategy.config:
        db_strategy.config = {}
    if 'parameters' not in db_strategy.config:
        db_strategy.config['parameters'] = {}
    
    old_value = db_strategy.config['parameters'].get(request.parameter_name, param_def.value)
    db_strategy.config['parameters'][request.parameter_name] = request.value
    
    # Mark config as modified (needed for SQLAlchemy JSON fields)
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(db_strategy, 'config')
    
    # Save changes
    db_strategy = storage.strategies.update(db_strategy)
    
    storage.create_audit_log(
        event_type="config_updated",
        description=f"Parameter tuned: {request.parameter_name} = {request.value}",
        details={
            "strategy_id": db_strategy.id,
            "parameter": request.parameter_name,
            "old_value": old_value,
            "new_value": request.value,
        },
    )
    
    return ParameterTuneResponse(
        strategy_id=str(db_strategy.id),
        parameter_name=request.parameter_name,
        old_value=old_value,
        new_value=request.value,
        success=True,
        message=f"Parameter {request.parameter_name} updated successfully",
    )


# ============================================================================
# Market Screener Endpoints
# ============================================================================

from .models import (
    AssetType, ScreenerAsset, ScreenerResponse,
    SymbolChartResponse, SymbolChartPoint,
    ScreenerMode, PresetUniverseMode, StockPreset, EtfPreset,
    RiskProfile, RiskProfileInfo, RiskProfilesResponse,
    TradingPreferencesRequest, TradingPreferencesResponse,
    BudgetStatus, BudgetUpdateRequest,
)
from services.market_screener import MarketScreener
# In-memory trading preferences (would be persisted in production)
_trading_preferences = TradingPreferencesResponse(
    asset_type=AssetType.BOTH,
    risk_profile=RiskProfile.BALANCED,
    weekly_budget=200.0,
    screener_limit=50,
    screener_mode=ScreenerMode.MOST_ACTIVE,
    stock_preset=StockPreset.WEEKLY_OPTIMIZED,
    etf_preset=EtfPreset.BALANCED,
)

_TRADING_PREFERENCES_KEY = "trading_preferences"


def _load_trading_preferences(storage: StorageService) -> TradingPreferencesResponse:
    """Load trading preferences from DB config, fallback to in-memory defaults."""
    config_entry = storage.config.get_by_key(_TRADING_PREFERENCES_KEY)
    if not config_entry:
        return _trading_preferences

    try:
        raw = json.loads(config_entry.value)
        return TradingPreferencesResponse(**raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _trading_preferences


def _save_trading_preferences(storage: StorageService, preferences: TradingPreferencesResponse) -> None:
    """Persist trading preferences to DB config."""
    storage.config.upsert(
        key=_TRADING_PREFERENCES_KEY,
        value=json.dumps(preferences.model_dump()),
        value_type="json",
        description="User trading preferences",
    )


def _create_market_screener() -> MarketScreener:
    """Create market screener with runtime keychain credentials when available."""
    config = _get_config_snapshot()
    mode = "paper" if config.paper_trading else "live"
    require_real_data = bool(config.strict_alpaca_data and str(config.broker).lower() == "alpaca")
    creds = _resolve_alpaca_credentials_for_mode(mode)
    if require_real_data and not creds:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Strict Alpaca data mode is enabled for {mode} but Alpaca credentials are not loaded. "
                "Open Settings and load/save Alpaca keys for this mode."
            ),
        )
    api_key = str((creds or {}).get("api_key") or "").strip()
    api_key_sig = api_key[-8:] if api_key else ""
    cache_key = f"{str(config.broker).lower()}:{mode}:{int(require_real_data)}:{api_key_sig}"
    with _market_screener_instances_lock:
        cached = _market_screener_instances.get(cache_key)
        if cached is not None:
            return cached
    if creds:
        screener = MarketScreener(alpaca_client=creds, require_real_data=require_real_data)
    else:
        screener = MarketScreener(require_real_data=False)
    with _market_screener_instances_lock:
        _market_screener_instances[cache_key] = screener
        # Bound in-memory screener instances to a tiny set.
        if len(_market_screener_instances) > 4:
            stale_keys = list(_market_screener_instances.keys())[:-4]
            for stale_key in stale_keys:
                _market_screener_instances.pop(stale_key, None)
    return screener


def _paginate_assets(assets_raw: List[dict], page: int, page_size: int) -> tuple[List[ScreenerAsset], int, int]:
    """Paginate raw screener assets and return typed assets + counts."""
    page = max(1, page)
    page_size = max(10, min(100, page_size))
    total_count = len(assets_raw)
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    start = (page - 1) * page_size
    end = start + page_size
    paged_raw = assets_raw[start:end]
    assets = [ScreenerAsset(**asset) for asset in paged_raw]
    return assets, total_count, total_pages


@router.get("/screener/stocks", response_model=ScreenerResponse)
async def get_active_stocks(
    limit: int = Query(default=50, ge=10, le=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=10, le=100),
):
    """
    Get most actively traded stocks.
    
    Args:
        limit: Number of stocks to return (10-200)
        
    Returns:
        List of actively traded stocks
    """
    screener = _create_market_screener()
    try:
        stocks = screener.get_active_stocks(limit)
        regime = screener.detect_market_regime()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    
    assets, total_count, total_pages = _paginate_assets(stocks, page, page_size)
    
    return ScreenerResponse(
        assets=assets,
        total_count=total_count,
        asset_type="stock",
        limit=limit,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        data_source=screener.get_last_source(),
        market_regime=regime,
        applied_guardrails={},
    )


@router.get("/screener/etfs", response_model=ScreenerResponse)
async def get_active_etfs(
    limit: int = Query(default=50, ge=10, le=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=10, le=100),
):
    """
    Get most actively traded ETFs.
    
    Args:
        limit: Number of ETFs to return (10-200)
        
    Returns:
        List of actively traded ETFs
    """
    screener = _create_market_screener()
    try:
        etfs = screener.get_active_etfs(limit)
        regime = screener.detect_market_regime()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    
    assets, total_count, total_pages = _paginate_assets(etfs, page, page_size)
    
    return ScreenerResponse(
        assets=assets,
        total_count=total_count,
        asset_type="etf",
        limit=limit,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        data_source=screener.get_last_source(),
        market_regime=regime,
        applied_guardrails={},
    )


@router.get("/screener/all", response_model=ScreenerResponse)
async def get_screener_results(
    asset_type: Optional[AssetType] = None,
    limit: Optional[int] = Query(default=None, ge=10, le=200),
    screener_mode: Optional[ScreenerMode] = None,
    seed_only: bool = Query(default=False),
    preset_universe_mode: Optional[PresetUniverseMode] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=10, le=100),
    min_dollar_volume: float = Query(default=10_000_000, ge=0, le=1_000_000_000_000),
    max_spread_bps: float = Query(default=50, ge=1, le=2000),
    max_sector_weight_pct: float = Query(default=45, ge=5, le=100),
    auto_regime_adjust: bool = True,
    db: Session = Depends(get_db)
):
    """
    Get screener results based on user preferences or provided filters.
    
    Args:
        asset_type: Asset type filter (overrides preferences)
        limit: Result limit (overrides preferences)
        
    Returns:
        List of assets based on filters
    """
    storage = StorageService(db)
    prefs = _load_trading_preferences(storage)
    broker: Optional[BrokerInterface] = None
    try:
        broker = get_broker()
    except RuntimeError:
        broker = None
    account_snapshot = _load_account_snapshot(broker)
    holdings_snapshot = _load_holdings_snapshot(storage, broker)

    # Use preferences if not overridden
    final_asset_type = asset_type or prefs.asset_type
    final_limit = limit or prefs.screener_limit
    final_mode = screener_mode or prefs.screener_mode
    final_limit = max(10, min(200, final_limit))
    if not math.isfinite(min_dollar_volume) or not math.isfinite(max_spread_bps) or not math.isfinite(max_sector_weight_pct):
        raise HTTPException(status_code=400, detail="Guardrail values must be finite numbers")
    
    screener = _create_market_screener()
    
    resolved_preset_universe_mode = PresetUniverseMode.SEED_GUARDRAIL_BLEND
    try:
        if final_mode == ScreenerMode.PRESET and final_asset_type in (AssetType.STOCK, AssetType.ETF):
            if preset_universe_mode is not None:
                resolved_preset_universe_mode = preset_universe_mode
            elif seed_only:
                resolved_preset_universe_mode = PresetUniverseMode.SEED_ONLY
            preset = (
                prefs.stock_preset.value
                if final_asset_type == AssetType.STOCK
                else prefs.etf_preset.value
            )
            preset_guardrails = screener.get_preset_guardrails(final_asset_type.value, preset)
            min_dollar_volume = max(min_dollar_volume, float(preset_guardrails["min_dollar_volume"]))
            max_spread_bps = min(max_spread_bps, float(preset_guardrails["max_spread_bps"]))
            max_sector_weight_pct = min(max_sector_weight_pct, float(preset_guardrails["max_sector_weight_pct"]))
            results = screener.get_preset_assets(
                final_asset_type.value,
                preset,
                final_limit,
                seed_only=resolved_preset_universe_mode == PresetUniverseMode.SEED_ONLY,
                preset_universe_mode=resolved_preset_universe_mode.value,
            )
        else:
            # Import AssetType from market_screener
            from services.market_screener import AssetType as ScreenerAssetType
            screener_asset_type = ScreenerAssetType(final_asset_type.value)
            results = screener.get_screener_results(screener_asset_type, final_limit)
        regime = screener.detect_market_regime()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    strategy_defaults = _adaptive_strategy_parameter_defaults(storage, max(1, final_limit))
    target_position_size = _safe_float(strategy_defaults.get("position_size", 0.0), 0.0)
    dca_tranches = max(1, int(_safe_float(strategy_defaults.get("dca_tranches", 1), 1)))
    require_fractionable = _should_require_fractionable_symbols(final_asset_type, prefs, account_snapshot)
    enforce_execution_capabilities = bool(final_asset_type == AssetType.STOCK and require_fractionable)
    symbol_capabilities = (
        _collect_symbol_capabilities(broker, results)
        if enforce_execution_capabilities
        else {}
    )
    optimized = screener.optimize_assets(
        results,
        limit=final_limit,
        min_dollar_volume=min_dollar_volume,
        max_spread_bps=max_spread_bps,
        max_sector_weight_pct=max_sector_weight_pct,
        regime=regime,
        auto_regime_adjust=auto_regime_adjust,
        current_holdings=holdings_snapshot,
        buying_power=account_snapshot.get("buying_power", 0.0),
        equity=account_snapshot.get("equity", 0.0),
        weekly_budget=prefs.weekly_budget,
        symbol_capabilities=symbol_capabilities,
        require_broker_tradable=enforce_execution_capabilities,
        require_fractionable=require_fractionable,
        target_position_size=target_position_size,
        dca_tranches=dca_tranches,
    )
    seed_only_relaxed_fallback_applied = False
    if (
        final_mode == ScreenerMode.PRESET
        and resolved_preset_universe_mode == PresetUniverseMode.SEED_ONLY
        and len(optimized) == 0
        and len(results) > 0
    ):
        relaxed = screener.optimize_assets(
            results,
            limit=final_limit,
            min_dollar_volume=0.0,
            max_spread_bps=2000.0,
            max_sector_weight_pct=100.0,
            regime=regime,
            auto_regime_adjust=False,
            current_holdings=holdings_snapshot,
            buying_power=account_snapshot.get("buying_power", 0.0),
            equity=account_snapshot.get("equity", 0.0),
            weekly_budget=prefs.weekly_budget,
            symbol_capabilities=symbol_capabilities,
            require_broker_tradable=False,
            require_fractionable=False,
            target_position_size=target_position_size,
            dca_tranches=dca_tranches,
        )
        if relaxed:
            optimized = relaxed
            seed_only_relaxed_fallback_applied = True
    
    assets, total_count, total_pages = _paginate_assets(optimized, page, page_size)
    
    return ScreenerResponse(
        assets=assets,
        total_count=total_count,
        asset_type=final_asset_type.value,
        limit=final_limit,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        data_source=screener.get_last_source(),
        market_regime=regime,
        applied_guardrails={
            "min_dollar_volume": min_dollar_volume,
            "max_spread_bps": max_spread_bps,
            "max_sector_weight_pct": max_sector_weight_pct,
            "auto_regime_adjust": auto_regime_adjust,
            "portfolio_adjusted": True,
            "holdings_count": len(holdings_snapshot),
            "equity": account_snapshot.get("equity", 0.0),
            "buying_power": account_snapshot.get("buying_power", 0.0),
            "require_broker_tradable": enforce_execution_capabilities,
            "require_fractionable": require_fractionable,
            "target_position_size": target_position_size,
            "dca_tranches": dca_tranches,
            "seed_only": resolved_preset_universe_mode == PresetUniverseMode.SEED_ONLY,
            "preset_universe_mode": resolved_preset_universe_mode.value,
            "seed_only_relaxed_fallback_applied": seed_only_relaxed_fallback_applied,
        },
    )


@router.get("/screener/preset", response_model=ScreenerResponse)
async def get_screener_preset(
    asset_type: AssetType,
    preset: ScreenerPreset,
    limit: int = Query(default=50, ge=10, le=200),
    seed_only: bool = Query(default=False),
    preset_universe_mode: Optional[PresetUniverseMode] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=10, le=100),
    min_dollar_volume: float = Query(default=10_000_000, ge=0, le=1_000_000_000_000),
    max_spread_bps: float = Query(default=50, ge=1, le=2000),
    max_sector_weight_pct: float = Query(default=45, ge=5, le=100),
    auto_regime_adjust: bool = True,
    db: Session = Depends(get_db),
):
    """
    Get curated screener assets by strategy preset.

    Stocks presets:
    - weekly_optimized
    - three_to_five_weekly
    - monthly_optimized
    - small_budget_weekly
    - micro_budget

    ETF presets:
    - conservative
    - balanced
    - aggressive
    """
    if asset_type == AssetType.BOTH:
        raise HTTPException(status_code=400, detail="Preset screener requires asset_type stock or etf")

    if not math.isfinite(min_dollar_volume) or not math.isfinite(max_spread_bps) or not math.isfinite(max_sector_weight_pct):
        raise HTTPException(status_code=400, detail="Guardrail values must be finite numbers")
    storage = StorageService(db)
    broker: Optional[BrokerInterface] = None
    try:
        broker = get_broker()
    except RuntimeError:
        broker = None
    account_snapshot = _load_account_snapshot(broker)
    holdings_snapshot = _load_holdings_snapshot(storage, broker)
    prefs = _load_trading_preferences(storage)
    screener = _create_market_screener()
    preset_guardrails = screener.get_preset_guardrails(asset_type.value, preset.value)
    min_dollar_volume = max(min_dollar_volume, float(preset_guardrails["min_dollar_volume"]))
    max_spread_bps = min(max_spread_bps, float(preset_guardrails["max_spread_bps"]))
    max_sector_weight_pct = min(max_sector_weight_pct, float(preset_guardrails["max_sector_weight_pct"]))
    resolved_preset_universe_mode = (
        preset_universe_mode
        if preset_universe_mode is not None
        else (PresetUniverseMode.SEED_ONLY if seed_only else PresetUniverseMode.SEED_GUARDRAIL_BLEND)
    )
    try:
        assets_raw = screener.get_preset_assets(
            asset_type.value,
            preset.value,
            limit,
            seed_only=resolved_preset_universe_mode == PresetUniverseMode.SEED_ONLY,
            preset_universe_mode=resolved_preset_universe_mode.value,
        )
        regime = screener.detect_market_regime()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    strategy_defaults = _adaptive_strategy_parameter_defaults(storage, max(1, limit))
    target_position_size = _safe_float(strategy_defaults.get("position_size", 0.0), 0.0)
    dca_tranches = max(1, int(_safe_float(strategy_defaults.get("dca_tranches", 1), 1)))
    require_fractionable = _should_require_fractionable_symbols(asset_type, prefs, account_snapshot)
    enforce_execution_capabilities = bool(asset_type == AssetType.STOCK and require_fractionable)
    symbol_capabilities = (
        _collect_symbol_capabilities(broker, assets_raw)
        if enforce_execution_capabilities
        else {}
    )
    optimized = screener.optimize_assets(
        assets_raw,
        limit=limit,
        min_dollar_volume=min_dollar_volume,
        max_spread_bps=max_spread_bps,
        max_sector_weight_pct=max_sector_weight_pct,
        regime=regime,
        auto_regime_adjust=auto_regime_adjust,
        current_holdings=holdings_snapshot,
        buying_power=account_snapshot.get("buying_power", 0.0),
        equity=account_snapshot.get("equity", 0.0),
        weekly_budget=prefs.weekly_budget,
        symbol_capabilities=symbol_capabilities,
        require_broker_tradable=enforce_execution_capabilities,
        require_fractionable=require_fractionable,
        target_position_size=target_position_size,
        dca_tranches=dca_tranches,
    )
    seed_only_relaxed_fallback_applied = False
    if (
        resolved_preset_universe_mode == PresetUniverseMode.SEED_ONLY
        and len(optimized) == 0
        and len(assets_raw) > 0
    ):
        relaxed = screener.optimize_assets(
            assets_raw,
            limit=limit,
            min_dollar_volume=0.0,
            max_spread_bps=2000.0,
            max_sector_weight_pct=100.0,
            regime=regime,
            auto_regime_adjust=False,
            current_holdings=holdings_snapshot,
            buying_power=account_snapshot.get("buying_power", 0.0),
            equity=account_snapshot.get("equity", 0.0),
            weekly_budget=prefs.weekly_budget,
            symbol_capabilities=symbol_capabilities,
            require_broker_tradable=False,
            require_fractionable=False,
            target_position_size=target_position_size,
            dca_tranches=dca_tranches,
        )
        if relaxed:
            optimized = relaxed
            seed_only_relaxed_fallback_applied = True
    assets, total_count, total_pages = _paginate_assets(optimized, page, page_size)

    return ScreenerResponse(
        assets=assets,
        total_count=total_count,
        asset_type=asset_type.value,
        limit=limit,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        data_source=screener.get_last_source(),
        market_regime=regime,
        applied_guardrails={
            "min_dollar_volume": min_dollar_volume,
            "max_spread_bps": max_spread_bps,
            "max_sector_weight_pct": max_sector_weight_pct,
            "auto_regime_adjust": auto_regime_adjust,
            "portfolio_adjusted": True,
            "holdings_count": len(holdings_snapshot),
            "equity": account_snapshot.get("equity", 0.0),
            "buying_power": account_snapshot.get("buying_power", 0.0),
            "require_broker_tradable": enforce_execution_capabilities,
            "require_fractionable": require_fractionable,
            "target_position_size": target_position_size,
            "dca_tranches": dca_tranches,
            "seed_only": resolved_preset_universe_mode == PresetUniverseMode.SEED_ONLY,
            "preset_universe_mode": resolved_preset_universe_mode.value,
            "seed_only_relaxed_fallback_applied": seed_only_relaxed_fallback_applied,
        },
    )


# ============================================================================
# Risk Profile Endpoints
# ============================================================================

@router.get("/risk-profiles", response_model=RiskProfilesResponse)
async def get_risk_profiles():
    """
    Get all available risk profiles with their configurations.
    
    Returns:
        Dictionary of risk profiles
    """
    profiles_data = get_all_profiles()
    
    profiles = {}
    for key, config in profiles_data.items():
        profiles[key] = RiskProfileInfo(
            name=config["name"],
            description=config["description"],
            max_position_size=config["max_position_size"],
            max_positions=config["max_positions"],
            position_size_percent=config["position_size_percent"],
            stop_loss_percent=config["stop_loss_percent"],
            take_profit_percent=config["take_profit_percent"],
            max_weekly_loss=config["max_weekly_loss"],
        )
    
    return RiskProfilesResponse(profiles=profiles)


# ============================================================================
# Trading Preferences Endpoints
# ============================================================================

@router.get("/preferences", response_model=TradingPreferencesResponse)
async def get_trading_preferences(db: Session = Depends(get_db)):
    """
    Get current trading preferences.
    
    Returns:
        Current trading preferences including asset type, risk profile, and budget
    """
    storage = StorageService(db)
    return _load_trading_preferences(storage)


@router.post("/preferences", response_model=TradingPreferencesResponse)
async def update_trading_preferences(request: TradingPreferencesRequest, db: Session = Depends(get_db)):
    """
    Update trading preferences.
    
    Args:
        request: Preferences to update
        
    Returns:
        Updated preferences
    """
    global _trading_preferences
    storage = StorageService(db)
    current = _load_trading_preferences(storage)

    if request.weekly_budget is not None:
        if not math.isfinite(request.weekly_budget):
            raise HTTPException(status_code=400, detail="weekly_budget must be a finite number")
        if request.weekly_budget < 50 or request.weekly_budget > 1_000_000:
            raise HTTPException(status_code=400, detail="weekly_budget must be within [50, 1000000]")
    if request.screener_limit is not None and (request.screener_limit < 10 or request.screener_limit > 200):
        raise HTTPException(status_code=400, detail="screener_limit must be within [10, 200]")

    if request.asset_type is not None:
        current.asset_type = request.asset_type
    
    if request.risk_profile is not None:
        current.risk_profile = request.risk_profile
    
    if request.weekly_budget is not None:
        current.weekly_budget = request.weekly_budget
        # Update budget tracker
        tracker = get_budget_tracker()
        tracker.set_weekly_budget(request.weekly_budget)
    
    if request.screener_limit is not None:
        current.screener_limit = request.screener_limit
    if request.screener_mode is not None:
        current.screener_mode = request.screener_mode
    if request.stock_preset is not None:
        current.stock_preset = request.stock_preset
    if request.etf_preset is not None:
        current.etf_preset = request.etf_preset

    # Conflict prevention and normalization.
    if current.asset_type == AssetType.ETF:
        current.screener_mode = ScreenerMode.PRESET
        current.risk_profile = RiskProfile(current.etf_preset.value)
    if current.asset_type == AssetType.BOTH and current.screener_mode == ScreenerMode.PRESET:
        raise HTTPException(status_code=400, detail="Preset mode requires asset_type stock or etf")
    if current.asset_type != AssetType.STOCK and current.screener_mode == ScreenerMode.MOST_ACTIVE:
        raise HTTPException(status_code=400, detail="Most active mode is available only for stock asset_type")
    if current.asset_type == AssetType.STOCK and current.screener_mode == ScreenerMode.PRESET and current.stock_preset is None:
        raise HTTPException(status_code=400, detail="Stock preset is required for stock preset mode")

    _trading_preferences = current
    _save_trading_preferences(storage, current)
    return current


@router.get("/preferences/recommendation")
async def get_preference_recommendation(
    equity: Optional[float] = Query(default=None, ge=100, le=100_000_000),
    weekly_budget: Optional[float] = Query(default=None, ge=50, le=5_000_000),
    target_trades_per_week: int = Query(default=4, ge=1, le=10),
    asset_type: Optional[AssetType] = Query(default=None),
    preset: Optional[ScreenerPreset] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Get tailored recommendation using current balance, holdings, and selected universe/preset."""
    storage = StorageService(db)
    prefs = _load_trading_preferences(storage)
    screener = _create_market_screener()

    normalized_asset_type = asset_type or prefs.asset_type
    if normalized_asset_type == AssetType.BOTH:
        normalized_asset_type = AssetType.STOCK
    stock_presets = {"weekly_optimized", "three_to_five_weekly", "monthly_optimized", "small_budget_weekly", "micro_budget"}
    etf_presets = {"conservative", "balanced", "aggressive"}
    requested_preset = preset.value if preset is not None else None
    config_snapshot = _get_config_snapshot()
    mode = "paper" if config_snapshot.paper_trading else "live"
    runtime_creds = _get_runtime_credentials(mode)
    runtime_credentials_loaded = bool(
        str(runtime_creds.get("api_key") or "").strip()
        and str(runtime_creds.get("secret_key") or "").strip()
    )
    recommendation_cache_key = json.dumps(
        {
            "asset_type": normalized_asset_type.value,
            "requested_preset": requested_preset or "",
            "equity_override": _safe_float(equity, -1.0) if equity is not None else None,
            "weekly_budget_override": _safe_float(weekly_budget, -1.0) if weekly_budget is not None else None,
            "target_trades_per_week": int(target_trades_per_week),
            "prefs": {
                "asset_type": prefs.asset_type.value,
                "stock_preset": prefs.stock_preset.value,
                "etf_preset": prefs.etf_preset.value,
                "weekly_budget": _safe_float(prefs.weekly_budget, 0.0),
                "screener_limit": int(prefs.screener_limit),
            },
            "config": {
                "broker": str(config_snapshot.broker).lower(),
                "paper_trading": bool(config_snapshot.paper_trading),
                "strict_alpaca_data": bool(config_snapshot.strict_alpaca_data),
            },
            "runtime_credentials_loaded": runtime_credentials_loaded,
            "last_broker_sync_at": _last_broker_sync_at or "",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    cached = _preference_recommendation_cache_get(recommendation_cache_key)
    if cached is not None:
        return cached

    broker: Optional[BrokerInterface] = None
    try:
        broker = get_broker()
    except RuntimeError:
        broker = None
    account_snapshot = _load_account_snapshot(broker)
    holdings_snapshot = _load_holdings_snapshot(storage, broker)

    effective_equity = (
        _safe_float(equity, 0.0)
        if equity is not None
        else _safe_float(account_snapshot.get("equity", 0.0), 0.0)
    )
    if effective_equity <= 0:
        effective_equity = max(
            0.0,
            sum(_safe_float(row.get("market_value", 0.0), 0.0) for row in holdings_snapshot),
        )
    effective_buying_power = _safe_float(account_snapshot.get("buying_power", 0.0), 0.0)
    effective_weekly_budget = (
        _safe_float(weekly_budget, 0.0)
        if weekly_budget is not None
        else _safe_float(prefs.weekly_budget, 200.0)
    )
    if effective_weekly_budget <= 0:
        effective_weekly_budget = 200.0

    if normalized_asset_type == AssetType.ETF:
        effective_preset = requested_preset if requested_preset in etf_presets else prefs.etf_preset.value
        if effective_preset not in etf_presets:
            effective_preset = "balanced"
        risk_profile = effective_preset
    else:
        if requested_preset in stock_presets:
            effective_preset = requested_preset
        elif effective_weekly_budget < 60 or effective_equity < 200:
            effective_preset = "micro_budget"
        elif target_trades_per_week <= 3:
            effective_preset = "monthly_optimized"
        elif target_trades_per_week <= 5:
            effective_preset = "three_to_five_weekly"
        elif effective_weekly_budget < 250 or effective_equity < 5_000:
            effective_preset = "small_budget_weekly"
        else:
            effective_preset = prefs.stock_preset.value
        if effective_preset not in stock_presets:
            effective_preset = "weekly_optimized"
        risk_profile_by_preset = {
            "micro_budget": "micro_budget",
            "small_budget_weekly": "conservative",
            "monthly_optimized": "balanced",
            "three_to_five_weekly": "balanced",
            "weekly_optimized": "aggressive",
        }
        risk_profile = risk_profile_by_preset.get(effective_preset, "balanced")

    preset_guardrails = screener.get_preset_guardrails(normalized_asset_type.value, effective_preset)

    holding_sector_values: Dict[str, float] = {}
    total_holding_value = 0.0
    for h in holdings_snapshot:
        symbol = str(h.get("symbol", "")).upper()
        asset_kind = str(h.get("asset_type", "")).lower()
        if asset_kind not in {"stock", "etf"}:
            asset_kind = "etf" if symbol.startswith("XL") or symbol in {
                "SPY", "VOO", "IVV", "QQQ", "IWM", "DIA", "VTI", "VEA", "VWO", "AGG", "TLT", "IEF", "BND",
                "XLF", "XLK", "XLE", "XLI", "XLP", "XLV", "XLY", "EEM"
            } else "stock"
        sector = screener._infer_sector(symbol, asset_kind)  # type: ignore[attr-defined]
        value = _safe_float(h.get("market_value", 0.0), 0.0)
        holding_sector_values[sector] = holding_sector_values.get(sector, 0.0) + value
        total_holding_value += value
    max_sector_exposure_pct = (
        (max(holding_sector_values.values()) / total_holding_value) * 100.0
        if total_holding_value > 0 and holding_sector_values
        else 0.0
    )

    min_dollar_volume = float(preset_guardrails["min_dollar_volume"])
    max_spread_bps = float(preset_guardrails["max_spread_bps"])
    max_sector_weight_pct = float(preset_guardrails["max_sector_weight_pct"])
    if effective_buying_power < 2_500:
        min_dollar_volume = max(min_dollar_volume, 15_000_000)
        max_spread_bps = min(max_spread_bps, 40)
    elif effective_buying_power < 10_000:
        min_dollar_volume = max(min_dollar_volume, 12_000_000)
        max_spread_bps = min(max_spread_bps, 45)
    if max_sector_exposure_pct >= 45:
        max_sector_weight_pct = min(max_sector_weight_pct, 35)
    elif max_sector_exposure_pct >= 35:
        max_sector_weight_pct = min(max_sector_weight_pct, 40)

    base_position_size = min(
        max(effective_weekly_budget * 0.60, 100.0),
        max(effective_equity * 0.10, 150.0),
    )
    if effective_buying_power > 0:
        base_position_size = min(base_position_size, max(100.0, effective_buying_power * 0.25))
    if holdings_snapshot:
        concentration_discount = max(0.55, 1.0 - (len(holdings_snapshot) * 0.04))
        base_position_size *= concentration_discount
    recommended_max_position_size = max(50.0, base_position_size)

    recommended_risk_limit_daily = min(
        max(effective_weekly_budget * 0.30, 75.0),
        max(effective_equity * 0.03, 100.0),
        max(recommended_max_position_size * 0.9, 75.0),
    )
    if effective_buying_power > 0:
        recommended_risk_limit_daily = min(recommended_risk_limit_daily, max(50.0, effective_buying_power * 0.12))
    recommended_risk_limit_daily = max(50.0, recommended_risk_limit_daily)

    estimated_ticket = max(100.0, recommended_max_position_size * 0.75)
    if effective_buying_power > 0:
        affordable_slots = max(1, int(effective_buying_power / estimated_ticket))
        recommended_screener_limit = int(max(10, min(200, max(affordable_slots * 4, 25))))
    else:
        recommended_screener_limit = int(max(10, min(200, prefs.screener_limit)))

    guardrails = {
        "min_dollar_volume": float(min_dollar_volume),
        "max_spread_bps": float(max_spread_bps),
        "max_sector_weight_pct": float(max_sector_weight_pct),
        "max_position_size": float(round(recommended_max_position_size, 2)),
        "risk_limit_daily": float(round(recommended_risk_limit_daily, 2)),
        "screener_limit": int(recommended_screener_limit),
    }
    response_payload = {
        "asset_type": normalized_asset_type.value,
        "stock_preset": effective_preset if normalized_asset_type == AssetType.STOCK else prefs.stock_preset.value,
        "etf_preset": effective_preset if normalized_asset_type == AssetType.ETF else prefs.etf_preset.value,
        "preset": effective_preset,
        "risk_profile": risk_profile,
        "guardrails": guardrails,
        "portfolio_context": {
            "equity": effective_equity,
            "buying_power": effective_buying_power,
            "cash": _safe_float(account_snapshot.get("cash", 0.0), 0.0),
            "holdings_count": len(holdings_snapshot),
            "max_sector_exposure_pct": round(max_sector_exposure_pct, 2),
        },
        "notes": (
            "Recommendation blends preset defaults with live account buying power, "
            "equity, and current holdings concentration."
        ),
    }
    _preference_recommendation_cache_set(recommendation_cache_key, response_payload)
    return response_payload


@router.get("/screener/chart/{symbol}", response_model=SymbolChartResponse)
async def get_symbol_chart(
    symbol: str,
    days: int = Query(default=320, ge=30, le=1000),
    take_profit_pct: float = Query(default=5.0, ge=0.1, le=50.0),
    trailing_stop_pct: float = Query(default=2.5, ge=0.1, le=30.0),
    atr_stop_mult: float = Query(default=1.8, ge=0.1, le=10.0),
    zscore_entry_threshold: float = Query(default=-1.5, ge=-10.0, le=-0.01),
    dip_buy_threshold_pct: float = Query(default=2.0, ge=0.1, le=30.0),
):
    """Get historical price chart with SMA50/SMA250 overlays for a symbol."""
    symbol = symbol.strip().upper()
    if not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", symbol):
        raise HTTPException(status_code=400, detail="Invalid symbol format")
    numeric_values = [take_profit_pct, trailing_stop_pct, atr_stop_mult, zscore_entry_threshold, dip_buy_threshold_pct]
    if any(not math.isfinite(value) for value in numeric_values):
        raise HTTPException(status_code=400, detail="Chart indicator values must be finite numbers")
    config = _get_config_snapshot()
    cache_key = (
        f"{symbol}:{int(days)}:"
        f"{str(config.broker).lower()}:{int(bool(config.paper_trading))}:{int(bool(config.strict_alpaca_data))}"
    )
    points = _chart_cache_get(cache_key)
    screener = _create_market_screener()
    try:
        if points is None:
            points = screener.get_symbol_chart(symbol=symbol, days=days)
            _chart_cache_set(cache_key, points)
        indicators = screener.get_chart_indicators(
            points=points,
            take_profit_pct=take_profit_pct,
            trailing_stop_pct=trailing_stop_pct,
            atr_stop_mult=atr_stop_mult,
            zscore_entry_threshold=zscore_entry_threshold,
            dip_buy_threshold_pct=dip_buy_threshold_pct,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return SymbolChartResponse(
        symbol=symbol.upper(),
        points=[SymbolChartPoint(**p) for p in points],
        indicators=indicators,
    )


# ============================================================================
# Budget Tracking Endpoints
# ============================================================================

@router.get("/budget/status", response_model=BudgetStatus)
async def get_budget_status(db: Session = Depends(get_db)):
    """
    Get current weekly budget status.
    
    Returns:
        Budget status including usage, remaining, and P&L
    """
    storage = StorageService(db)
    prefs = _load_trading_preferences(storage)
    tracker = get_budget_tracker(prefs.weekly_budget)
    status = tracker.get_budget_status()
    
    return BudgetStatus(**status)


@router.post("/budget/update", response_model=BudgetStatus)
async def update_weekly_budget(request: BudgetUpdateRequest, db: Session = Depends(get_db)):
    """
    Update the weekly budget amount.
    
    Args:
        request: New budget amount
        
    Returns:
        Updated budget status
    """
    global _trading_preferences
    
    tracker = get_budget_tracker()
    tracker.set_weekly_budget(request.weekly_budget)
    
    # Also update preferences
    _trading_preferences.weekly_budget = request.weekly_budget
    storage = StorageService(db)
    _save_trading_preferences(storage, _trading_preferences)
    
    status = tracker.get_budget_status()
    return BudgetStatus(**status)
