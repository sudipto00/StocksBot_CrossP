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
