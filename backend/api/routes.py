"""
API Routes.
Defines all REST API endpoints for StocksBot.
"""
from datetime import datetime, timedelta, timezone
import json
import math
import re
import threading
import time
import asyncio
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, Query, Header, WebSocket, WebSocketDisconnect
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from storage.database import get_db
from storage.service import StorageService
from storage.models import AuditLog as DBAuditLog, Trade as DBTrade
from services.broker import BrokerInterface, PaperBroker
from services.order_execution import (
    OrderExecutionService,
    OrderValidationError,
    BrokerError,
    set_global_kill_switch,
    get_global_kill_switch,
)
from config.settings import get_settings, has_alpaca_credentials
from services.logging_service import configure_file_logging, cleanup_old_files

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
    # Strategy configuration models
    StrategyConfigResponse,
    StrategyConfigUpdateRequest,
    StrategyMetricsResponse,
    BacktestRequest,
    BacktestResponse,
    ParameterTuneRequest,
    ParameterTuneResponse,
    StrategyParameter,
    ScreenerPreset,
)
from .runner_manager import runner_manager
from services.strategy_analytics import StrategyAnalyticsService
from config.strategy_config import get_default_parameters

router = APIRouter()

# ============================================================================
# Broker Initialization
# ============================================================================

_broker_instance: Optional[BrokerInterface] = None
_runtime_broker_credentials = {
    "paper": {"api_key": None, "secret_key": None},
    "live": {"api_key": None, "secret_key": None},
}


def get_broker() -> BrokerInterface:
    """
    Get or create broker instance.
    
    Returns:
        Configured broker instance (Paper or Alpaca)
    """
    global _broker_instance
    
    if _broker_instance is None:
        settings = get_settings()
        mode = "paper" if _config.paper_trading else "live"
        runtime_creds = _runtime_broker_credentials.get(mode, {})
        runtime_has_credentials = bool(
            runtime_creds.get("api_key") and runtime_creds.get("secret_key")
        )

        # Prefer runtime credentials provided by desktop keychain flow.
        # Fallback to env credentials, and finally the in-process paper broker.
        if runtime_has_credentials:
            from integrations.alpaca_broker import AlpacaBroker
            _broker_instance = AlpacaBroker(
                api_key=runtime_creds["api_key"],
                secret_key=runtime_creds["secret_key"],
                paper=_config.paper_trading,
            )
            _config.broker = "alpaca"
        elif has_alpaca_credentials():
            from integrations.alpaca_broker import AlpacaBroker
            _broker_instance = AlpacaBroker(
                api_key=settings.alpaca_api_key,
                secret_key=settings.alpaca_secret_key,
                paper=_config.paper_trading
            )
            _config.broker = "alpaca"
        else:
            _broker_instance = PaperBroker()
            _config.broker = "paper"
        
        # Connect broker
        if not _broker_instance.connect():
            raise RuntimeError("Failed to connect to broker")
    
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
    broker = get_broker()
    storage = StorageService(db)
    set_global_kill_switch(_load_kill_switch(storage))
    
    # Get config for risk limits
    global _config
    _config = _load_runtime_config(storage)
    config = _config
    
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
    log_directory="./logs",
    audit_export_directory="./audit_exports",
    log_retention_days=30,
    audit_retention_days=90,
    broker="paper",
)
configure_file_logging(_config.log_directory)
_last_housekeeping_run: Optional[datetime] = None
_CONFIG_KEY = "runtime_config"
_KILL_SWITCH_KEY = "safety_kill_switch"
_BROKER_SYNC_KEY = "last_broker_sync_at"
_idempotency_cache: Dict[str, Dict[str, Any]] = {}
_idempotency_lock = threading.Lock()
_last_broker_sync_at: Optional[str] = None

_SUMMARY_NOTIFICATION_PREFERENCES_KEY = "summary_notification_preferences"
_summary_notification_preferences = SummaryNotificationPreferencesResponse(
    enabled=False,
    frequency=SummaryNotificationFrequency.DAILY,
    channel=SummaryNotificationChannel.EMAIL,
    recipient="",
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")


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


def _load_runtime_config(storage: StorageService) -> ConfigResponse:
    """Load runtime config from DB config store or fallback to defaults."""
    entry = storage.config.get_by_key(_CONFIG_KEY)
    if not entry or not entry.value:
        return _config
    try:
        raw = json.loads(entry.value)
        return ConfigResponse(**raw)
    except Exception:
        return _config


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
    _last_broker_sync_at = ts_iso


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
    except Exception:
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
    except Exception:
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
        except Exception:
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
    if get_global_kill_switch():
        return "Trading is blocked: kill switch is active"
    if not broker.is_connected():
        return "Broker is not connected"
    if not broker.is_symbol_tradable(symbol):
        return f"Symbol {symbol} is not tradable"
    if not broker.is_market_open():
        return "Market is closed"
    return None


def _load_summary_notification_preferences(storage: StorageService) -> SummaryNotificationPreferencesResponse:
    """Load summary notification preferences from DB config."""
    config_entry = storage.config.get_by_key(_SUMMARY_NOTIFICATION_PREFERENCES_KEY)
    if not config_entry:
        return _summary_notification_preferences
    try:
        return SummaryNotificationPreferencesResponse(**json.loads(config_entry.value))
    except Exception:
        return _summary_notification_preferences


def _run_housekeeping(storage: StorageService, force: bool = False) -> Dict[str, int]:
    """Periodic cleanup for audit rows and retained files."""
    global _last_housekeeping_run
    now = datetime.now(timezone.utc)
    if not force and _last_housekeeping_run and (now - _last_housekeeping_run).total_seconds() < 3600:
        return {"audit_rows_deleted": 0, "log_files_deleted": 0, "audit_files_deleted": 0}
    _last_housekeeping_run = now
    audit_rows_deleted = storage.audit_logs.delete_old_logs(days=_config.audit_retention_days)
    log_files_deleted = cleanup_old_files(_config.log_directory, _config.log_retention_days)
    audit_files_deleted = cleanup_old_files(_config.audit_export_directory, _config.audit_retention_days)
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


@router.get("/config", response_model=ConfigResponse)
async def get_config(db: Session = Depends(get_db)):
    """
    Get current configuration.
    TODO: Load from persistent storage.
    """
    global _config
    storage = StorageService(db)
    _config = _load_runtime_config(storage)
    return _config


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
    global _config
    cached = _idempotency_cache_get("/config", x_idempotency_key)
    if cached is not None:
        return ConfigResponse(**cached)

    storage = StorageService(db)
    _config = _load_runtime_config(storage)

    if request.trading_enabled is not None:
        _config.trading_enabled = request.trading_enabled
    if request.paper_trading is not None:
        _config.paper_trading = request.paper_trading
    if request.max_position_size is not None:
        if not math.isfinite(request.max_position_size):
            raise HTTPException(status_code=400, detail="max_position_size must be a finite number")
        if request.max_position_size < 1 or request.max_position_size > 10_000_000:
            raise HTTPException(status_code=400, detail="max_position_size must be within [1, 10000000]")
        _config.max_position_size = request.max_position_size
    if request.risk_limit_daily is not None:
        if not math.isfinite(request.risk_limit_daily):
            raise HTTPException(status_code=400, detail="risk_limit_daily must be a finite number")
        if request.risk_limit_daily < 1 or request.risk_limit_daily > 1_000_000:
            raise HTTPException(status_code=400, detail="risk_limit_daily must be within [1, 1000000]")
        _config.risk_limit_daily = request.risk_limit_daily
    if request.tick_interval_seconds is not None:
        if not math.isfinite(request.tick_interval_seconds):
            raise HTTPException(status_code=400, detail="tick_interval_seconds must be a finite number")
        if request.tick_interval_seconds < 5 or request.tick_interval_seconds > 3600:
            raise HTTPException(status_code=400, detail="tick_interval_seconds must be within [5, 3600]")
        _config.tick_interval_seconds = request.tick_interval_seconds
        runner_manager.set_tick_interval(_config.tick_interval_seconds)
    if request.streaming_enabled is not None:
        _config.streaming_enabled = request.streaming_enabled
        runner_manager.set_streaming_enabled(_config.streaming_enabled)
    if request.log_directory is not None:
        candidate = request.log_directory.strip()
        if not candidate:
            raise HTTPException(status_code=400, detail="log_directory cannot be empty")
        _config.log_directory = str(configure_file_logging(candidate))
    if request.audit_export_directory is not None:
        candidate = request.audit_export_directory.strip()
        if not candidate:
            raise HTTPException(status_code=400, detail="audit_export_directory cannot be empty")
        export_dir = Path(candidate).expanduser().resolve()
        export_dir.mkdir(parents=True, exist_ok=True)
        _config.audit_export_directory = str(export_dir)
    if request.log_retention_days is not None:
        _config.log_retention_days = int(request.log_retention_days)
    if request.audit_retention_days is not None:
        _config.audit_retention_days = int(request.audit_retention_days)
    if request.broker is not None:
        _config.broker = request.broker

    # Recreate broker on next use when mode changes.
    global _broker_instance
    _broker_instance = None
    _run_housekeeping(storage, force=True)
    _save_runtime_config(storage, _config)
    _idempotency_cache_set("/config", x_idempotency_key, _config.model_dump())

    return _config


@router.get("/broker/credentials/status", response_model=BrokerCredentialsStatusResponse)
async def get_broker_credentials_status():
    """
    Get status of runtime broker credentials loaded from desktop keychain.
    """
    paper_available = bool(
        _runtime_broker_credentials["paper"]["api_key"]
        and _runtime_broker_credentials["paper"]["secret_key"]
    )
    live_available = bool(
        _runtime_broker_credentials["live"]["api_key"]
        and _runtime_broker_credentials["live"]["secret_key"]
    )
    active_mode = "paper" if _config.paper_trading else "live"
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

    _runtime_broker_credentials[mode]["api_key"] = api_key
    _runtime_broker_credentials[mode]["secret_key"] = secret_key

    # Ensure broker instance is recreated with latest credentials.
    global _broker_instance
    _broker_instance = None

    return await get_broker_credentials_status()


@router.get("/broker/account", response_model=BrokerAccountResponse)
async def get_broker_account():
    """
    Get active broker account balances (cash/equity/buying power).
    Returns an informative disconnected payload if unavailable.
    """
    status = await get_broker_credentials_status()
    mode = "paper" if _config.paper_trading else "live"
    try:
        broker = get_broker()
        info = broker.get_account_info()
        cash = float(info.get("cash", 0.0))
        equity = float(info.get("equity", info.get("portfolio_value", 0.0)))
        buying_power = float(info.get("buying_power", 0.0))
        currency = str(info.get("currency", "USD"))
        return BrokerAccountResponse(
            broker=_config.broker,
            mode=mode,
            connected=True,
            using_runtime_credentials=status.using_runtime_credentials,
            currency=currency,
            cash=cash,
            equity=equity,
            buying_power=buying_power,
            message="Account fetched successfully",
        )
    except Exception as exc:
        return BrokerAccountResponse(
            broker=_config.broker,
            mode=mode,
            connected=False,
            using_runtime_credentials=status.using_runtime_credentials,
            currency="USD",
            cash=0.0,
            equity=0.0,
            buying_power=0.0,
            message=f"Broker account unavailable: {exc}",
        )
    finally:
        _set_last_broker_sync(datetime.now(timezone.utc).isoformat())


# ============================================================================
# Positions Endpoints
# ============================================================================

@router.get("/positions", response_model=PositionsResponse)
async def get_positions(db: Session = Depends(get_db)):
    """
    Get current positions.
    TODO: Integrate with portfolio service and broker API.
    Returns stub data for now.
    """
    broker_positions: List[Dict[str, Any]] = []
    try:
        broker = get_broker()
        broker_positions = broker.get_positions()
    except Exception:
        storage = StorageService(db)
        local_positions = storage.get_open_positions()
        for position in local_positions:
            broker_positions.append({
                "symbol": position.symbol,
                "quantity": float(position.quantity),
                "side": position.side.value if hasattr(position.side, "value") else str(position.side),
                "avg_entry_price": float(position.avg_entry_price),
                "current_price": float(position.avg_entry_price),
                "market_value": float(position.cost_basis),
                "cost_basis": float(position.cost_basis),
                "unrealized_pnl": 0.0,
                "unrealized_pnl_percent": 0.0,
            })
    positions: List[Position] = []
    for raw in broker_positions:
        qty = float(raw.get("quantity", 0.0))
        current_price = float(raw.get("current_price", raw.get("price", 0.0)))
        avg_entry_price = float(raw.get("avg_entry_price", 0.0))
        cost_basis = float(raw.get("cost_basis", abs(qty) * avg_entry_price))
        market_value = float(raw.get("market_value", abs(qty) * current_price))
        unrealized_pnl = float(raw.get("unrealized_pnl", market_value - cost_basis))
        unrealized_pnl_percent = float(
            raw.get(
                "unrealized_pnl_percent",
                ((unrealized_pnl / cost_basis) * 100.0) if cost_basis > 0 else 0.0,
            )
        )
        side_raw = str(raw.get("side", "long")).lower()
        side = PositionSide.SHORT if side_raw == "short" else PositionSide.LONG
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
    )


# ============================================================================
# Orders Endpoints
# ============================================================================

@router.get("/orders", response_model=OrdersResponse)
async def get_orders():
    """
    Get orders.
    TODO: Integrate with order service and broker API.
    Returns stub data for now.
    """
    # Stub data for development
    stub_orders = [
        Order(
            id="order-001",
            symbol="AAPL",
            side=OrderSide.BUY,
            type=OrderType.LIMIT,
            quantity=100,
            price=150.00,
            status=OrderStatus.FILLED,
            filled_quantity=100,
            avg_fill_price=150.00,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ),
        Order(
            id="order-002",
            symbol="MSFT",
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=50,
            status=OrderStatus.FILLED,
            filled_quantity=50,
            avg_fill_price=300.00,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ),
    ]

    return OrdersResponse(
        orders=stub_orders,
        total_count=len(stub_orders),
    )


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
            status=OrderStatus(order.status.value),
            filled_quantity=order.filled_quantity or 0.0,
            avg_fill_price=order.avg_fill_price,
            created_at=order.created_at,
            updated_at=order.updated_at
        )
        
    except OrderValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except BrokerError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


# ============================================================================
# Notifications Endpoints
# ============================================================================

@router.post("/notifications", response_model=NotificationResponse)
async def request_notification(request: NotificationRequest):
    """
    Request a notification to be sent to the user.
    TODO: Integrate with notification service and system tray.
    This is a placeholder.
    """
    title = request.title.strip()
    message = request.message.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    # Placeholder - just log for now
    print(f"[NOTIFICATION] {request.severity.upper()}: {title} - {message}")

    return NotificationResponse(
        success=True,
        message="Notification queued (placeholder)",
    )


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
    Generate and queue a summary notification immediately.
    This prepares the payload for email/SMS delivery.
    """
    storage = StorageService(db)
    prefs = _load_summary_notification_preferences(storage)

    if not prefs.enabled:
        return NotificationResponse(success=False, message="Summary notifications are disabled")
    if not prefs.recipient:
        return NotificationResponse(success=False, message="Recipient is required")

    trades = storage.get_all_trades(limit=5000)
    now = datetime.now(timezone.utc)
    if prefs.frequency == SummaryNotificationFrequency.DAILY:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = start - timedelta(days=start.weekday())

    scoped = [t for t in trades if t.executed_at and t.executed_at >= start]
    trade_count = len(scoped)
    gross_notional = sum(float(t.quantity or 0) * float(t.price or 0) for t in scoped)
    realized_pnl = sum(float(t.realized_pnl or 0) for t in scoped if t.realized_pnl is not None)
    summary = (
        f"{prefs.frequency.value.title()} summary: {trade_count} trade(s), "
        f"gross ${gross_notional:.2f}, realized P&L ${realized_pnl:.2f}"
    )

    # Placeholder transport hook for email/SMS integration.
    print(f"[SUMMARY:{prefs.channel.value}] to {prefs.recipient} -> {summary}")
    storage.create_audit_log(
        event_type="config_updated",
        description=f"Queued {prefs.frequency.value} {prefs.channel.value} summary notification",
        details={
            "recipient": prefs.recipient,
            "trade_count": trade_count,
            "gross_notional": gross_notional,
            "realized_pnl": realized_pnl,
        },
    )

    return NotificationResponse(
        success=True,
        message=f"Queued {prefs.channel.value} summary to {prefs.recipient}: {summary}",
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
            created_at=db_strat.created_at,
            updated_at=db_strat.updated_at,
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
        created_at=db_strategy.created_at,
        updated_at=db_strategy.updated_at,
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
        created_at=db_strategy.created_at,
        updated_at=db_strategy.updated_at,
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
        created_at=db_strategy.created_at,
        updated_at=db_strategy.updated_at,
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
            timestamp=db_log.timestamp,
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
                executed_at=trade.executed_at,
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


@router.get("/maintenance/storage")
async def get_storage_settings():
    """Get configured log/audit storage paths and a quick file inventory."""
    log_dir = Path(_config.log_directory).expanduser().resolve()
    audit_dir = Path(_config.audit_export_directory).expanduser().resolve()
    log_files = []
    audit_files = []
    if log_dir.exists():
        log_files = sorted(
            [{"name": p.name, "size_bytes": p.stat().st_size, "modified_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat()} for p in log_dir.iterdir() if p.is_file()],
            key=lambda row: row["modified_at"],
            reverse=True,
        )[:50]
    if audit_dir.exists():
        audit_files = sorted(
            [{"name": p.name, "size_bytes": p.stat().st_size, "modified_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat()} for p in audit_dir.iterdir() if p.is_file()],
            key=lambda row: row["modified_at"],
            reverse=True,
        )[:50]
    return {
        "log_directory": str(log_dir),
        "audit_export_directory": str(audit_dir),
        "log_retention_days": _config.log_retention_days,
        "audit_retention_days": _config.audit_retention_days,
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

    if clear_log_files:
        log_files_deleted = _delete_all_files(_config.log_directory)
    if clear_audit_export_files:
        audit_files_deleted = _delete_all_files(_config.audit_export_directory)

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


@router.websocket("/ws/system-health")
async def ws_system_health(websocket: WebSocket):
    """Realtime health snapshot stream for UI surfaces."""
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
                "last_broker_sync_at": _last_broker_sync_at,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await websocket.send_json(payload)
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        return


@router.post("/runner/start", response_model=RunnerActionResponse)
async def start_runner(
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

    global _config
    storage = StorageService(db)
    _config = _load_runtime_config(storage)
    broker = get_broker()
    max_position_size, risk_limit_daily = _balance_adjusted_limits(
        broker=broker,
        requested_max_position_size=_config.max_position_size,
        requested_risk_limit_daily=_config.risk_limit_daily,
    )
    result = runner_manager.start_runner(
        db=db,
        broker=broker,
        max_position_size=max_position_size,
        risk_limit_daily=risk_limit_daily,
        tick_interval=_config.tick_interval_seconds,
        streaming_enabled=_config.streaming_enabled,
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
    except Exception as e:
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
    days: int = Query(default=30, ge=1, le=3650),
    db: Session = Depends(get_db)
):
    """
    Get portfolio analytics time series data.
    Returns equity curve and P&L over time.
    """
    storage = StorageService(db)

    trades = storage.get_recent_trades(limit=5000)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    scoped_trades = []
    for trade in trades:
        if not trade.executed_at:
            continue
        executed_at = (
            trade.executed_at.replace(tzinfo=timezone.utc)
            if trade.executed_at.tzinfo is None
            else trade.executed_at.astimezone(timezone.utc)
        )
        if executed_at >= cutoff:
            scoped_trades.append(trade)

    time_series = []
    cumulative_pnl = 0.0
    equity = 100000.0

    for trade in reversed(scoped_trades):
        cumulative_pnl += trade.realized_pnl or 0.0
        equity += trade.realized_pnl or 0.0

        time_series.append({
            'timestamp': trade.executed_at.isoformat(),
            'equity': equity,
            'pnl': trade.realized_pnl or 0.0,
            'cumulative_pnl': cumulative_pnl,
            'symbol': trade.symbol,
        })

    return {
        'time_series': time_series,
        'total_trades': len(scoped_trades),
        'current_equity': equity,
        'total_pnl': cumulative_pnl,
    }


@router.get("/analytics/summary")
async def get_portfolio_summary(db: Session = Depends(get_db)):
    """
    Get portfolio summary statistics.
    Returns aggregate metrics and performance stats.
    """
    storage = StorageService(db)

    positions = storage.get_open_positions()
    trades = storage.get_recent_trades(limit=1000)

    total_trades = len(trades)
    total_pnl = sum(t.realized_pnl or 0.0 for t in trades)
    winning_trades = len([t for t in trades if (t.realized_pnl or 0.0) > 0])
    losing_trades = len([t for t in trades if (t.realized_pnl or 0.0) < 0])
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

    total_position_value = sum(p.cost_basis for p in positions)
    total_positions = len(positions)

    return {
        'total_trades': total_trades,
        'total_pnl': total_pnl,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': win_rate,
        'total_positions': total_positions,
        'total_position_value': total_position_value,
        'equity': 100000.0 + total_pnl,
    }


# ============================================================================
# Strategy Configuration Endpoints
# ============================================================================

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
    
    # Get parameters from config or use defaults
    config_params = db_strategy.config.get('parameters', {}) if db_strategy.config else {}
    default_params = get_default_parameters()
    
    # Merge with stored values and convert to API models
    parameters = []
    for param in default_params:
        if param.name in config_params:
            param.value = config_params[param.name]
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
        symbols=db_strategy.config.get('symbols', []) if db_strategy.config else [],
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
        updated_at=metrics.updated_at,
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
    
    # Use strategy symbols if not provided in request
    if not request.symbols and db_strategy.config:
        request.symbols = db_strategy.config.get('symbols', ['AAPL', 'MSFT'])
    if request.symbols:
        request.symbols = _normalize_symbols(request.symbols)
        if not request.symbols:
            raise HTTPException(status_code=400, detail="At least one valid symbol is required for backtest")
    
    # Run backtest
    analytics = StrategyAnalyticsService(db)
    from config.strategy_config import BacktestRequest as BacktestReq
    
    backtest_req = BacktestReq(
        strategy_id=strategy_id,
        start_date=request.start_date,
        end_date=request.end_date,
        initial_capital=request.initial_capital,
        symbols=request.symbols,
        parameters=request.parameters,
    )
    
    result = analytics.run_backtest(backtest_req)
    
    storage.create_audit_log(
        event_type="strategy_started",
        description=f"Backtest completed for strategy: {db_strategy.name}",
        details={
            "strategy_id": db_strategy.id,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "total_trades": result.total_trades,
            "win_rate": result.win_rate,
        },
    )
    
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
    ScreenerMode, StockPreset, EtfPreset,
    RiskProfile, RiskProfileInfo, RiskProfilesResponse,
    TradingPreferencesRequest, TradingPreferencesResponse,
    BudgetStatus, BudgetUpdateRequest,
)
from services.market_screener import MarketScreener
from services.budget_tracker import get_budget_tracker
from config.risk_profiles import get_risk_profile, get_all_profiles

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
    except Exception:
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
    mode = "paper" if _config.paper_trading else "live"
    runtime_creds = _runtime_broker_credentials.get(mode, {})
    api_key = (runtime_creds.get("api_key") or "").strip()
    secret_key = (runtime_creds.get("secret_key") or "").strip()
    if api_key and secret_key:
        return MarketScreener(alpaca_client={"api_key": api_key, "secret_key": secret_key})
    return MarketScreener()


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
    stocks = screener.get_active_stocks(limit)
    regime = screener.detect_market_regime()
    
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
    etfs = screener.get_active_etfs(limit)
    regime = screener.detect_market_regime()
    
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
    except Exception:
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
    
    if final_mode == ScreenerMode.PRESET and final_asset_type in (AssetType.STOCK, AssetType.ETF):
        preset = (
            prefs.stock_preset.value
            if final_asset_type == AssetType.STOCK
            else prefs.etf_preset.value
        )
        preset_guardrails = screener.get_preset_guardrails(final_asset_type.value, preset)
        min_dollar_volume = max(min_dollar_volume, float(preset_guardrails["min_dollar_volume"]))
        max_spread_bps = min(max_spread_bps, float(preset_guardrails["max_spread_bps"]))
        max_sector_weight_pct = min(max_sector_weight_pct, float(preset_guardrails["max_sector_weight_pct"]))
        results = screener.get_preset_assets(final_asset_type.value, preset, final_limit)
    else:
        # Import AssetType from market_screener
        from services.market_screener import AssetType as ScreenerAssetType
        screener_asset_type = ScreenerAssetType(final_asset_type.value)
        results = screener.get_screener_results(screener_asset_type, final_limit)
    regime = screener.detect_market_regime()
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
    )
    
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
        },
    )


@router.get("/screener/preset", response_model=ScreenerResponse)
async def get_screener_preset(
    asset_type: AssetType,
    preset: ScreenerPreset,
    limit: int = Query(default=50, ge=10, le=200),
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
    except Exception:
        broker = None
    account_snapshot = _load_account_snapshot(broker)
    holdings_snapshot = _load_holdings_snapshot(storage, broker)
    prefs = _load_trading_preferences(storage)
    screener = _create_market_screener()
    preset_guardrails = screener.get_preset_guardrails(asset_type.value, preset.value)
    min_dollar_volume = max(min_dollar_volume, float(preset_guardrails["min_dollar_volume"]))
    max_spread_bps = min(max_spread_bps, float(preset_guardrails["max_spread_bps"]))
    max_sector_weight_pct = min(max_sector_weight_pct, float(preset_guardrails["max_sector_weight_pct"]))
    try:
        assets_raw = screener.get_preset_assets(asset_type.value, preset.value, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    regime = screener.detect_market_regime()
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
    )
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
    weekly_budget: Optional[float] = Query(default=None, ge=25, le=5_000_000),
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

    broker: Optional[BrokerInterface] = None
    try:
        broker = get_broker()
    except Exception:
        broker = None
    account_snapshot = _load_account_snapshot(broker)
    holdings_snapshot = _load_holdings_snapshot(storage, broker)

    effective_equity = (
        _safe_float(equity, 0.0)
        if equity is not None
        else _safe_float(account_snapshot.get("equity", 0.0), 0.0)
    )
    if effective_equity <= 0:
        effective_equity = 10_000.0
    effective_buying_power = _safe_float(account_snapshot.get("buying_power", 0.0), 0.0)
    effective_weekly_budget = (
        _safe_float(weekly_budget, 0.0)
        if weekly_budget is not None
        else _safe_float(prefs.weekly_budget, 200.0)
    )
    if effective_weekly_budget <= 0:
        effective_weekly_budget = 200.0

    stock_presets = {"weekly_optimized", "three_to_five_weekly", "monthly_optimized", "small_budget_weekly"}
    etf_presets = {"conservative", "balanced", "aggressive"}
    requested_preset = preset.value if preset is not None else None

    if normalized_asset_type == AssetType.ETF:
        effective_preset = requested_preset if requested_preset in etf_presets else prefs.etf_preset.value
        if effective_preset not in etf_presets:
            effective_preset = "balanced"
        risk_profile = effective_preset
    else:
        if requested_preset in stock_presets:
            effective_preset = requested_preset
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
    return {
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
    screener = _create_market_screener()
    points = screener.get_symbol_chart(symbol=symbol, days=days)
    indicators = screener.get_chart_indicators(
        points=points,
        take_profit_pct=take_profit_pct,
        trailing_stop_pct=trailing_stop_pct,
        atr_stop_mult=atr_stop_mult,
        zscore_entry_threshold=zscore_entry_threshold,
        dip_buy_threshold_pct=dip_buy_threshold_pct,
    )
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
