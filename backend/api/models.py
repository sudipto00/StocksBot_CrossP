"""
API Data Models and Contracts.
Defines Pydantic models for request/response validation.
"""
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from enum import Enum
import re
from pydantic import BaseModel, Field, field_validator


# ============================================================================
# Enums
# ============================================================================

class OrderSide(str, Enum):
    """Order side enumeration."""
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Order type enumeration."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    """Order status enumeration."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PositionSide(str, Enum):
    """Position side enumeration."""
    LONG = "long"
    SHORT = "short"


# ============================================================================
# Response Models
# ============================================================================

class StatusResponse(BaseModel):
    """Backend status response."""
    status: str = Field(..., description="Service status")
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")


class ConfigResponse(BaseModel):
    """Configuration response."""
    environment: str = Field(default="development", description="Environment name")
    trading_enabled: bool = Field(default=False, description="Whether trading is enabled")
    paper_trading: bool = Field(default=True, description="Whether in paper trading mode")
    max_position_size: float = Field(default=10000.0, description="Maximum position size")
    risk_limit_daily: float = Field(default=500.0, description="Daily risk limit")
    tick_interval_seconds: float = Field(default=60.0, description="Strategy runner polling interval in seconds")
    streaming_enabled: bool = Field(default=False, description="Enable websocket trade-update streaming when broker supports it")
    strict_alpaca_data: bool = Field(
        default=True,
        description="When true and broker is alpaca, fail instead of using fallback market data",
    )
    log_directory: str = Field(default="./logs", description="Directory for backend log files")
    audit_export_directory: str = Field(default="./audit_exports", description="Directory for audit export artifacts")
    log_retention_days: int = Field(default=30, description="Retention period for log files")
    audit_retention_days: int = Field(default=90, description="Retention period for audit logs/files")
    broker: str = Field(default="paper", description="Broker name")


class Position(BaseModel):
    """Position model."""
    symbol: str = Field(..., description="Stock symbol")
    side: PositionSide = Field(..., description="Position side (long/short)")
    quantity: float = Field(..., description="Number of shares")
    avg_entry_price: float = Field(..., description="Average entry price")
    current_price: float = Field(..., description="Current market price")
    unrealized_pnl: float = Field(..., description="Unrealized profit/loss")
    unrealized_pnl_percent: float = Field(..., description="Unrealized P&L percentage")
    cost_basis: float = Field(..., description="Total cost basis")
    market_value: float = Field(..., description="Current market value")
    current_price_available: bool = Field(default=True, description="Whether current_price is sourced from live market data")
    valuation_source: str = Field(default="broker_mark", description="Valuation source: broker_mark or cost_basis_fallback")


class PositionsResponse(BaseModel):
    """Positions list response."""
    positions: List[Position] = Field(default_factory=list, description="List of positions")
    total_value: float = Field(default=0.0, description="Total portfolio value")
    total_pnl: float = Field(default=0.0, description="Total unrealized P&L")
    total_pnl_percent: float = Field(default=0.0, description="Total P&L percentage")
    data_source: str = Field(default="broker", description="Primary source for position payload")
    degraded: bool = Field(default=False, description="True when broker market marks were unavailable")
    degraded_reason: Optional[str] = Field(default=None, description="Reason for degraded fallback mode")


class Order(BaseModel):
    """Order model."""
    id: str = Field(..., description="Order ID")
    symbol: str = Field(..., description="Stock symbol")
    side: OrderSide = Field(..., description="Order side (buy/sell)")
    type: OrderType = Field(..., description="Order type")
    quantity: float = Field(..., description="Order quantity")
    price: Optional[float] = Field(None, description="Limit/stop price")
    status: OrderStatus = Field(..., description="Order status")
    filled_quantity: float = Field(default=0.0, description="Filled quantity")
    avg_fill_price: Optional[float] = Field(None, description="Average fill price")
    created_at: datetime = Field(..., description="Order creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class OrdersResponse(BaseModel):
    """Orders list response."""
    orders: List[Order] = Field(default_factory=list, description="List of orders")
    total_count: int = Field(default=0, description="Total order count")


# ============================================================================
# Request Models
# ============================================================================

class OrderRequest(BaseModel):
    """Order creation request."""
    symbol: str = Field(..., description="Stock symbol", min_length=1, max_length=10)
    side: OrderSide = Field(..., description="Order side (buy/sell)")
    type: OrderType = Field(..., description="Order type")
    quantity: float = Field(..., description="Order quantity", gt=0)
    price: Optional[float] = Field(None, description="Limit/stop price", gt=0)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        symbol = value.strip().upper()
        if not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", symbol):
            raise ValueError("Invalid symbol format")
        return symbol


class ConfigUpdateRequest(BaseModel):
    """Configuration update request."""
    trading_enabled: Optional[bool] = Field(None, description="Enable/disable trading")
    paper_trading: Optional[bool] = Field(None, description="Enable/disable paper trading")
    max_position_size: Optional[float] = Field(None, description="Maximum position size", gt=0)
    risk_limit_daily: Optional[float] = Field(None, description="Daily risk limit", gt=0)
    tick_interval_seconds: Optional[float] = Field(None, description="Runner polling interval in seconds", gt=0)
    streaming_enabled: Optional[bool] = Field(None, description="Enable websocket trade-update streaming")
    strict_alpaca_data: Optional[bool] = Field(
        None,
        description="Require real Alpaca-backed data when broker is alpaca",
    )
    log_directory: Optional[str] = Field(None, description="Directory for backend log files")
    audit_export_directory: Optional[str] = Field(None, description="Directory for audit exports")
    log_retention_days: Optional[int] = Field(None, description="Retention days for logs", ge=1, le=3650)
    audit_retention_days: Optional[int] = Field(None, description="Retention days for audit logs/files", ge=1, le=3650)
    broker: Optional[str] = Field(None, description="Broker name (paper/alpaca)")


class BrokerCredentialsRequest(BaseModel):
    """Runtime broker credentials request (not persisted)."""
    mode: str = Field(..., description="Credential mode: paper or live")
    api_key: str = Field(..., description="Alpaca API key", min_length=1)
    secret_key: str = Field(..., description="Alpaca secret key", min_length=1)

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        mode = value.strip().lower()
        if mode not in {"paper", "live"}:
            raise ValueError("mode must be either 'paper' or 'live'")
        return mode


class BrokerCredentialsStatusResponse(BaseModel):
    """Runtime broker credentials status."""
    paper_available: bool = Field(..., description="Paper credentials are available")
    live_available: bool = Field(..., description="Live credentials are available")
    active_mode: str = Field(..., description="Current runtime mode in use")
    using_runtime_credentials: bool = Field(..., description="Whether runtime credentials are active")


class BrokerAccountResponse(BaseModel):
    """Active broker account snapshot."""
    broker: str = Field(..., description="Active broker provider")
    mode: str = Field(..., description="paper or live")
    connected: bool = Field(..., description="Whether broker account was fetched successfully")
    using_runtime_credentials: bool = Field(..., description="Whether runtime credentials are in use")
    currency: str = Field(default="USD", description="Account currency")
    cash: float = Field(default=0.0, description="Cash balance")
    equity: float = Field(default=0.0, description="Account equity")
    buying_power: float = Field(default=0.0, description="Available buying power")
    message: str = Field(default="", description="Status message")


# ============================================================================
# Notification Models
# ============================================================================

class NotificationSeverity(str, Enum):
    """Notification severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


class NotificationRequest(BaseModel):
    """Notification request from backend."""
    title: str = Field(..., description="Notification title", max_length=100)
    message: str = Field(..., description="Notification message", max_length=500)
    severity: NotificationSeverity = Field(default=NotificationSeverity.INFO, description="Severity level")


class NotificationResponse(BaseModel):
    """Notification response."""
    success: bool = Field(..., description="Whether notification was queued")
    message: str = Field(..., description="Response message")


class SummaryNotificationChannel(str, Enum):
    """Summary notification delivery channel."""
    EMAIL = "email"
    SMS = "sms"


class SummaryNotificationFrequency(str, Enum):
    """Summary notification frequency."""
    DAILY = "daily"
    WEEKLY = "weekly"


class SummaryNotificationPreferencesRequest(BaseModel):
    """Summary notification preferences update request."""
    enabled: Optional[bool] = Field(None, description="Enable daily/weekly transaction summaries")
    frequency: Optional[SummaryNotificationFrequency] = Field(None, description="Summary cadence")
    channel: Optional[SummaryNotificationChannel] = Field(None, description="Delivery channel")
    recipient: Optional[str] = Field(None, description="Email address or phone number")


class SummaryNotificationPreferencesResponse(BaseModel):
    """Summary notification preferences response."""
    enabled: bool = Field(default=False, description="Whether summary notifications are enabled")
    frequency: SummaryNotificationFrequency = Field(default=SummaryNotificationFrequency.DAILY, description="Summary cadence")
    channel: SummaryNotificationChannel = Field(default=SummaryNotificationChannel.EMAIL, description="Delivery channel")
    recipient: str = Field(default="", description="Email address or phone number")


# ============================================================================
# Strategy Models
# ============================================================================

class StrategyStatus(str, Enum):
    """Strategy status enumeration."""
    ACTIVE = "active"
    STOPPED = "stopped"
    ERROR = "error"


class Strategy(BaseModel):
    """Strategy model."""
    id: str = Field(..., description="Strategy ID")
    name: str = Field(..., description="Strategy name")
    description: Optional[str] = Field(None, description="Strategy description")
    status: StrategyStatus = Field(..., description="Strategy status")
    symbols: List[str] = Field(default_factory=list, description="Symbols to trade")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class StrategyCreateRequest(BaseModel):
    """Strategy creation request."""
    name: str = Field(..., description="Strategy name", min_length=1, max_length=100)
    description: Optional[str] = Field(None, description="Strategy description", max_length=500)
    symbols: List[str] = Field(default_factory=list, description="Symbols to trade")

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, symbols: List[str]) -> List[str]:
        if len(symbols) > 200:
            raise ValueError("symbols cannot exceed 200 entries")
        for symbol in symbols:
            clean = (symbol or "").strip().upper()
            if clean and not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", clean):
                raise ValueError(f"Invalid symbol format: {symbol}")
        return symbols


class StrategyUpdateRequest(BaseModel):
    """Strategy update request."""
    name: Optional[str] = Field(None, description="Strategy name", min_length=1, max_length=100)
    description: Optional[str] = Field(None, description="Strategy description", max_length=500)
    symbols: Optional[List[str]] = Field(None, description="Symbols to trade")
    status: Optional[StrategyStatus] = Field(None, description="Strategy status")

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, symbols: Optional[List[str]]) -> Optional[List[str]]:
        if symbols is None:
            return symbols
        if len(symbols) > 200:
            raise ValueError("symbols cannot exceed 200 entries")
        for symbol in symbols:
            clean = (symbol or "").strip().upper()
            if clean and not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", clean):
                raise ValueError(f"Invalid symbol format: {symbol}")
        return symbols


class StrategiesResponse(BaseModel):
    """Strategies list response."""
    strategies: List[Strategy] = Field(default_factory=list, description="List of strategies")
    total_count: int = Field(default=0, description="Total strategy count")


# ============================================================================
# Audit Log Models
# ============================================================================

class AuditEventType(str, Enum):
    """Audit event type enumeration."""
    ORDER_CREATED = "order_created"
    ORDER_FILLED = "order_filled"
    ORDER_CANCELLED = "order_cancelled"
    STRATEGY_STARTED = "strategy_started"
    STRATEGY_STOPPED = "strategy_stopped"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    CONFIG_UPDATED = "config_updated"
    RUNNER_STARTED = "runner_started"
    RUNNER_STOPPED = "runner_stopped"
    ERROR = "error"


class AuditLog(BaseModel):
    """Audit log entry model."""
    id: str = Field(..., description="Log entry ID")
    timestamp: datetime = Field(..., description="Event timestamp")
    event_type: AuditEventType = Field(..., description="Event type")
    description: str = Field(..., description="Event description")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional event details")


class AuditLogsResponse(BaseModel):
    """Audit logs list response."""
    logs: List[AuditLog] = Field(default_factory=list, description="List of audit log entries")
    total_count: int = Field(default=0, description="Total log count")


class TradeHistoryItem(BaseModel):
    """Trade history entry for audit mode."""
    id: str = Field(..., description="Trade ID")
    order_id: str = Field(..., description="Associated order ID")
    symbol: str = Field(..., description="Traded symbol")
    side: OrderSide = Field(..., description="Trade side")
    quantity: float = Field(..., description="Executed quantity")
    price: float = Field(..., description="Execution price")
    commission: float = Field(default=0.0, description="Commission paid")
    fees: float = Field(default=0.0, description="Fees paid")
    executed_at: datetime = Field(..., description="Execution timestamp")
    realized_pnl: Optional[float] = Field(None, description="Realized P&L if available")


class TradeHistoryResponse(BaseModel):
    """Trade history list response."""
    trades: List[TradeHistoryItem] = Field(default_factory=list, description="Trade history entries")
    total_count: int = Field(default=0, description="Total trade count")


# ============================================================================
# Runner Models
# ============================================================================

class RunnerStatusResponse(BaseModel):
    """Runner status response."""
    status: str = Field(..., description="Runner status (stopped, running, sleeping, paused, error)")
    strategies: List[Dict[str, Any]] = Field(default_factory=list, description="Loaded strategies")
    tick_interval: float = Field(..., description="Tick interval in seconds")
    broker_connected: bool = Field(..., description="Whether broker is connected")
    poll_success_count: int = Field(default=0, description="Successful poll cycles")
    poll_error_count: int = Field(default=0, description="Poll cycles with errors")
    last_poll_error: str = Field(default="", description="Most recent poll error summary")
    last_poll_at: Optional[str] = Field(default=None, description="Last poll timestamp ISO string")
    last_successful_poll_at: Optional[str] = Field(default=None, description="Last successful poll timestamp ISO string")
    last_reconciliation_at: Optional[str] = Field(default=None, description="Last reconciliation timestamp ISO string")
    last_reconciliation_discrepancies: int = Field(default=0, description="Last reconciliation discrepancy count")
    sleeping: bool = Field(default=False, description="Whether runner is in off-hours sleep mode")
    sleep_since: Optional[str] = Field(default=None, description="Sleep mode start timestamp ISO string")
    next_market_open_at: Optional[str] = Field(default=None, description="Forecast market-open timestamp ISO string")
    last_resume_at: Optional[str] = Field(default=None, description="Last resume timestamp ISO string")
    last_catchup_at: Optional[str] = Field(default=None, description="Last catch-up cycle timestamp ISO string")
    resume_count: int = Field(default=0, description="Number of sleep->resume transitions")
    market_session_open: Optional[bool] = Field(default=None, description="Latest broker market-session flag")


class RunnerActionResponse(BaseModel):
    """Runner action response (start/stop)."""
    success: bool = Field(..., description="Whether action was successful")
    message: str = Field(..., description="Action result message")
    status: str = Field(..., description="Current runner status")


# ============================================================================
# Strategy Configuration Models
# ============================================================================

class StrategyParameter(BaseModel):
    """Strategy parameter model."""
    name: str = Field(..., description="Parameter name")
    value: float = Field(..., description="Parameter value")
    min_value: float = Field(default=0.0, description="Minimum allowed value")
    max_value: float = Field(default=100.0, description="Maximum allowed value")
    step: float = Field(default=0.1, description="Adjustment step size")
    description: Optional[str] = Field(None, description="Parameter description")


class StrategyConfigResponse(BaseModel):
    """Strategy configuration response."""
    strategy_id: str = Field(..., description="Strategy ID")
    name: str = Field(..., description="Strategy name")
    description: Optional[str] = Field(None, description="Strategy description")
    symbols: List[str] = Field(default_factory=list, description="Trading symbols")
    parameters: List[StrategyParameter] = Field(default_factory=list, description="Strategy parameters")
    enabled: bool = Field(default=True, description="Whether strategy is enabled")


class StrategyConfigUpdateRequest(BaseModel):
    """Request to update strategy configuration."""
    symbols: Optional[List[str]] = Field(None, description="Trading symbols")
    parameters: Optional[Dict[str, float]] = Field(None, description="Parameter updates")
    enabled: Optional[bool] = Field(None, description="Enable/disable strategy")


class StrategyMetricsResponse(BaseModel):
    """Strategy performance metrics response."""
    strategy_id: str = Field(..., description="Strategy ID")
    win_rate: float = Field(..., description="Win rate percentage")
    volatility: float = Field(..., description="Returns volatility")
    drawdown: float = Field(..., description="Maximum drawdown percentage")
    total_trades: int = Field(..., description="Total number of trades")
    winning_trades: int = Field(..., description="Number of winning trades")
    losing_trades: int = Field(..., description="Number of losing trades")
    total_pnl: float = Field(..., description="Total profit/loss")
    sharpe_ratio: Optional[float] = Field(None, description="Sharpe ratio")
    updated_at: datetime = Field(..., description="Last update timestamp")


class BacktestRequest(BaseModel):
    """Backtest request model."""
    start_date: str = Field(..., description="Start date (ISO format)")
    end_date: str = Field(..., description="End date (ISO format)")
    initial_capital: float = Field(default=100000.0, description="Initial capital")
    symbols: Optional[List[str]] = Field(None, description="Symbols to backtest")
    parameters: Optional[Dict[str, float]] = Field(None, description="Strategy parameters")
    # Live-equivalence controls (optional for backward compatibility).
    emulate_live_trading: bool = Field(
        default=False,
        description="When true, enforce live-like backtest constraints and strict real data.",
    )
    use_workspace_universe: bool = Field(
        default=False,
        description="When true, resolve symbols from current screener workspace preferences/guardrails.",
    )
    asset_type: Optional[Literal["stock", "etf"]] = Field(
        default=None,
        description="Optional workspace asset type override for backtest universe resolution.",
    )
    screener_mode: Optional[Literal["most_active", "preset"]] = Field(
        default=None,
        description="Optional workspace screener mode override for backtest universe resolution.",
    )
    stock_preset: Optional[Literal["weekly_optimized", "three_to_five_weekly", "monthly_optimized", "small_budget_weekly", "micro_budget"]] = Field(
        default=None,
        description="Optional stock preset override for workspace universe backtests.",
    )
    etf_preset: Optional[Literal["conservative", "balanced", "aggressive"]] = Field(
        default=None,
        description="Optional ETF preset override for workspace universe backtests.",
    )
    screener_limit: Optional[int] = Field(default=None, ge=10, le=200, description="Universe size cap for workspace-backed runs.")
    seed_only: Optional[bool] = Field(default=None, description="Compatibility flag for preset universe mode.")
    preset_universe_mode: Optional[Literal["seed_only", "seed_guardrail_blend", "guardrail_only"]] = Field(
        default=None,
        description="Preset universe mode when screener_mode=preset.",
    )
    min_dollar_volume: Optional[float] = Field(default=None, ge=0, description="Guardrail override: minimum dollar volume.")
    max_spread_bps: Optional[float] = Field(default=None, ge=1, description="Guardrail override: max spread in bps.")
    max_sector_weight_pct: Optional[float] = Field(default=None, ge=5, le=100, description="Guardrail override: sector concentration cap.")
    auto_regime_adjust: Optional[bool] = Field(default=None, description="Guardrail override: enable regime-based adjustment.")


class BacktestResponse(BaseModel):
    """Backtest result response."""
    strategy_id: str = Field(..., description="Strategy ID")
    start_date: str = Field(..., description="Backtest start date")
    end_date: str = Field(..., description="Backtest end date")
    initial_capital: float = Field(..., description="Initial capital")
    final_capital: float = Field(..., description="Final capital")
    total_return: float = Field(..., description="Total return percentage")
    total_trades: int = Field(..., description="Total trades executed")
    winning_trades: int = Field(..., description="Number of winning trades")
    losing_trades: int = Field(..., description="Number of losing trades")
    win_rate: float = Field(..., description="Win rate percentage")
    max_drawdown: float = Field(..., description="Maximum drawdown percentage")
    sharpe_ratio: float = Field(..., description="Sharpe ratio")
    volatility: float = Field(..., description="Returns volatility")
    trades: List[Dict[str, Any]] = Field(default_factory=list, description="Trade history")
    equity_curve: List[Dict[str, Any]] = Field(default_factory=list, description="Equity curve data")
    diagnostics: Dict[str, Any] = Field(default_factory=dict, description="Signal and blocker diagnostics")


class ParameterTuneRequest(BaseModel):
    """Parameter tuning request model."""
    parameter_name: str = Field(..., description="Parameter to tune")
    value: float = Field(..., description="New parameter value")


class ParameterTuneResponse(BaseModel):
    """Parameter tuning response model."""
    strategy_id: str = Field(..., description="Strategy ID")
    parameter_name: str = Field(..., description="Parameter name")
    old_value: float = Field(..., description="Previous value")
    new_value: float = Field(..., description="New value")
    success: bool = Field(..., description="Whether update was successful")
    message: str = Field(..., description="Result message")


# ============================================================================
# Market Screener Models
# ============================================================================

class AssetType(str, Enum):
    """Asset type enumeration."""
    STOCK = "stock"
    ETF = "etf"
    BOTH = "both"


class ScreenerPreset(str, Enum):
    """Curated screener preset names."""
    WEEKLY_OPTIMIZED = "weekly_optimized"
    THREE_TO_FIVE_WEEKLY = "three_to_five_weekly"
    MONTHLY_OPTIMIZED = "monthly_optimized"
    SMALL_BUDGET_WEEKLY = "small_budget_weekly"
    MICRO_BUDGET = "micro_budget"
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class ScreenerMode(str, Enum):
    """Screener mode enumeration."""
    MOST_ACTIVE = "most_active"
    PRESET = "preset"


class PresetUniverseMode(str, Enum):
    """Universe construction modes for preset screener workflows."""
    SEED_ONLY = "seed_only"
    SEED_GUARDRAIL_BLEND = "seed_guardrail_blend"
    GUARDRAIL_ONLY = "guardrail_only"


class StockPreset(str, Enum):
    """Stock strategy presets."""
    WEEKLY_OPTIMIZED = "weekly_optimized"
    THREE_TO_FIVE_WEEKLY = "three_to_five_weekly"
    MONTHLY_OPTIMIZED = "monthly_optimized"
    SMALL_BUDGET_WEEKLY = "small_budget_weekly"
    MICRO_BUDGET = "micro_budget"


class EtfPreset(str, Enum):
    """ETF strategy presets."""
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class ScreenerAsset(BaseModel):
    """Screener asset model."""
    symbol: str = Field(..., description="Asset symbol")
    name: str = Field(..., description="Asset name")
    asset_type: str = Field(..., description="Asset type (stock/etf)")
    volume: int = Field(..., description="Average daily volume")
    price: float = Field(..., description="Current price")
    change_percent: float = Field(..., description="Price change percentage")
    last_updated: str = Field(..., description="Last update timestamp")
    sector: Optional[str] = Field(default=None, description="Mapped sector classification")
    score: Optional[float] = Field(default=None, description="Composite symbol score")
    dollar_volume: Optional[float] = Field(default=None, description="Estimated dollar volume")
    spread_bps: Optional[float] = Field(default=None, description="Estimated spread in basis points")
    tradable: Optional[bool] = Field(default=True, description="Whether symbol passed execution guardrails")
    broker_tradable: Optional[bool] = Field(default=None, description="Whether broker reports symbol tradable")
    fractionable: Optional[bool] = Field(default=None, description="Whether broker supports fractional orders")
    execution_ticket: Optional[float] = Field(default=None, description="Estimated executable ticket size in dollars")
    selection_reason: Optional[str] = Field(default=None, description="Explainability note for selection")


class ScreenerResponse(BaseModel):
    """Market screener response."""
    assets: List[ScreenerAsset] = Field(default_factory=list, description="List of screened assets")
    total_count: int = Field(..., description="Total count")
    asset_type: str = Field(..., description="Asset type filter applied")
    limit: int = Field(..., description="Limit applied")
    page: int = Field(default=1, description="Current result page")
    page_size: int = Field(default=25, description="Page size")
    total_pages: int = Field(default=1, description="Total available pages")
    data_source: str = Field(default="fallback", description="Source used: alpaca, fallback, or mixed")
    market_regime: str = Field(default="unknown", description="Detected market regime")
    applied_guardrails: Dict[str, Any] = Field(default_factory=dict, description="Applied screener filters/guardrails")


class SymbolChartPoint(BaseModel):
    """Symbol chart point with SMA overlays."""
    timestamp: str
    close: float
    sma50: Optional[float] = None
    sma250: Optional[float] = None


class SymbolChartResponse(BaseModel):
    """Symbol chart response."""
    symbol: str
    points: List[SymbolChartPoint]
    indicators: Dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# Risk Profile Models
# ============================================================================

class RiskProfile(str, Enum):
    """Risk profile enumeration."""
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"
    MICRO_BUDGET = "micro_budget"


class RiskProfileInfo(BaseModel):
    """Risk profile information."""
    name: str = Field(..., description="Profile name")
    description: str = Field(..., description="Profile description")
    max_position_size: float = Field(..., description="Maximum position size")
    max_positions: int = Field(..., description="Maximum number of positions")
    position_size_percent: float = Field(..., description="Position size as percent of budget")
    stop_loss_percent: float = Field(..., description="Stop loss percentage")
    take_profit_percent: float = Field(..., description="Take profit percentage")
    max_weekly_loss: float = Field(..., description="Max weekly loss as percent of budget")


class RiskProfilesResponse(BaseModel):
    """Risk profiles list response."""
    profiles: Dict[str, RiskProfileInfo] = Field(..., description="Available risk profiles")


class TradingPreferencesRequest(BaseModel):
    """Trading preferences update request."""
    asset_type: Optional[AssetType] = Field(None, description="Preferred asset type")
    risk_profile: Optional[RiskProfile] = Field(None, description="Risk profile")
    weekly_budget: Optional[float] = Field(None, description="Weekly budget", gt=0)
    screener_limit: Optional[int] = Field(None, description="Screener result limit", ge=10, le=200)
    screener_mode: Optional[ScreenerMode] = Field(None, description="Screener mode")
    stock_preset: Optional[StockPreset] = Field(None, description="Stock preset")
    etf_preset: Optional[EtfPreset] = Field(None, description="ETF preset")


class TradingPreferencesResponse(BaseModel):
    """Trading preferences response."""
    asset_type: AssetType = Field(..., description="Preferred asset type")
    risk_profile: RiskProfile = Field(..., description="Current risk profile")
    weekly_budget: float = Field(..., description="Weekly trading budget")
    screener_limit: int = Field(..., description="Screener result limit")
    screener_mode: ScreenerMode = Field(..., description="Screener mode")
    stock_preset: StockPreset = Field(..., description="Stock strategy preset")
    etf_preset: EtfPreset = Field(..., description="ETF strategy preset")


# ============================================================================
# Budget Tracking Models
# ============================================================================

class BudgetStatus(BaseModel):
    """Weekly budget status."""
    weekly_budget: float = Field(..., description="Total weekly budget")
    base_weekly_budget: float = Field(default=0.0, description="Original weekly budget before auto-scaling")
    used_budget: float = Field(..., description="Budget used this week")
    remaining_budget: float = Field(..., description="Budget remaining this week")
    used_percent: float = Field(..., description="Percentage of budget used")
    trades_this_week: int = Field(..., description="Number of trades this week")
    weekly_pnl: float = Field(..., description="Weekly profit/loss")
    week_start: str = Field(..., description="Current week start date")
    days_remaining: int = Field(..., description="Days remaining in week")
    reinvested_amount: float = Field(default=0.0, description="Profits reinvested this week")
    reinvest_profits: bool = Field(default=True, description="Whether profit reinvestment is enabled")
    reinvest_pct: float = Field(default=50.0, description="Percentage of profits to reinvest")
    auto_scale_budget: bool = Field(default=False, description="Whether auto-scaling is enabled")
    auto_scale_pct: float = Field(default=10.0, description="Auto-scale percentage per profitable streak")
    cumulative_pnl: float = Field(default=0.0, description="Cumulative P&L across all weeks")
    consecutive_profitable_weeks: int = Field(default=0, description="Current streak of profitable weeks")


class BudgetUpdateRequest(BaseModel):
    """Budget update request."""
    weekly_budget: float = Field(..., description="New weekly budget", gt=0)
