"""
API Data Models and Contracts.
Defines Pydantic models for request/response validation.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


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


class PositionsResponse(BaseModel):
    """Positions list response."""
    positions: List[Position] = Field(default_factory=list, description="List of positions")
    total_value: float = Field(default=0.0, description="Total portfolio value")
    total_pnl: float = Field(default=0.0, description="Total unrealized P&L")
    total_pnl_percent: float = Field(default=0.0, description="Total P&L percentage")


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


class ConfigUpdateRequest(BaseModel):
    """Configuration update request."""
    trading_enabled: Optional[bool] = Field(None, description="Enable/disable trading")
    paper_trading: Optional[bool] = Field(None, description="Enable/disable paper trading")
    max_position_size: Optional[float] = Field(None, description="Maximum position size", gt=0)
    risk_limit_daily: Optional[float] = Field(None, description="Daily risk limit", gt=0)


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


class StrategyUpdateRequest(BaseModel):
    """Strategy update request."""
    name: Optional[str] = Field(None, description="Strategy name", min_length=1, max_length=100)
    description: Optional[str] = Field(None, description="Strategy description", max_length=500)
    symbols: Optional[List[str]] = Field(None, description="Symbols to trade")
    status: Optional[StrategyStatus] = Field(None, description="Strategy status")


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


# ============================================================================
# Runner Models
# ============================================================================

class RunnerStatusResponse(BaseModel):
    """Runner status response."""
    status: str = Field(..., description="Runner status (stopped, running, paused, error)")
    strategies: List[Dict[str, Any]] = Field(default_factory=list, description="Loaded strategies")
    tick_interval: float = Field(..., description="Tick interval in seconds")
    broker_connected: bool = Field(..., description="Whether broker is connected")


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


class ScreenerAsset(BaseModel):
    """Screener asset model."""
    symbol: str = Field(..., description="Asset symbol")
    name: str = Field(..., description="Asset name")
    asset_type: str = Field(..., description="Asset type (stock/etf)")
    volume: int = Field(..., description="Average daily volume")
    price: float = Field(..., description="Current price")
    change_percent: float = Field(..., description="Price change percentage")
    last_updated: str = Field(..., description="Last update timestamp")


class ScreenerResponse(BaseModel):
    """Market screener response."""
    assets: List[ScreenerAsset] = Field(default_factory=list, description="List of screened assets")
    total_count: int = Field(..., description="Total count")
    asset_type: str = Field(..., description="Asset type filter applied")
    limit: int = Field(..., description="Limit applied")


# ============================================================================
# Risk Profile Models
# ============================================================================

class RiskProfile(str, Enum):
    """Risk profile enumeration."""
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


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


class TradingPreferencesResponse(BaseModel):
    """Trading preferences response."""
    asset_type: AssetType = Field(..., description="Preferred asset type")
    risk_profile: RiskProfile = Field(..., description="Current risk profile")
    weekly_budget: float = Field(..., description="Weekly trading budget")
    screener_limit: int = Field(..., description="Screener result limit")


# ============================================================================
# Budget Tracking Models
# ============================================================================

class BudgetStatus(BaseModel):
    """Weekly budget status."""
    weekly_budget: float = Field(..., description="Total weekly budget")
    used_budget: float = Field(..., description="Budget used this week")
    remaining_budget: float = Field(..., description="Budget remaining this week")
    used_percent: float = Field(..., description="Percentage of budget used")
    trades_this_week: int = Field(..., description="Number of trades this week")
    weekly_pnl: float = Field(..., description="Weekly profit/loss")
    week_start: str = Field(..., description="Current week start date")
    days_remaining: int = Field(..., description="Days remaining in week")


class BudgetUpdateRequest(BaseModel):
    """Budget update request."""
    weekly_budget: float = Field(..., description="New weekly budget", gt=0)
