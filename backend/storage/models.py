"""
Database models for StocksBot.
Defines the schema for positions, orders, trades, strategies, and config.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, Enum as SQLEnum, Text, JSON
)
from sqlalchemy.sql import func
import enum

from storage.database import Base


# Enums for type safety
class PositionSideEnum(str, enum.Enum):
    """Position side enumeration."""
    LONG = "long"
    SHORT = "short"


class OrderSideEnum(str, enum.Enum):
    """Order side enumeration."""
    BUY = "buy"
    SELL = "sell"


class OrderTypeEnum(str, enum.Enum):
    """Order type enumeration."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatusEnum(str, enum.Enum):
    """Order status enumeration."""
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class TradeTypeEnum(str, enum.Enum):
    """Trade type enumeration."""
    OPEN = "open"
    CLOSE = "close"
    ADJUSTMENT = "adjustment"


class AuditEventTypeEnum(str, enum.Enum):
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


# Database Models

class Position(Base):
    """
    Position model - tracks current and historical positions.
    """
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(SQLEnum(PositionSideEnum), nullable=False)
    quantity = Column(Float, nullable=False)
    avg_entry_price = Column(Float, nullable=False)
    cost_basis = Column(Float, nullable=False)
    realized_pnl = Column(Float, default=0.0)
    
    # Status tracking
    is_open = Column(Boolean, default=True, index=True)
    opened_at = Column(DateTime, default=func.now(), nullable=False)
    closed_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)


class Order(Base):
    """
    Order model - tracks all orders (pending, filled, cancelled).
    """
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(100), nullable=True, index=True)  # Broker order ID
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(SQLEnum(OrderSideEnum), nullable=False)
    type = Column(SQLEnum(OrderTypeEnum), nullable=False)
    status = Column(SQLEnum(OrderStatusEnum), nullable=False, index=True)
    
    # Order details
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=True)  # Limit/stop price
    filled_quantity = Column(Float, default=0.0)
    avg_fill_price = Column(Float, nullable=True)
    
    # Strategy association (optional)
    strategy_id = Column(Integer, nullable=True, index=True)
    
    # Timestamps
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    filled_at = Column(DateTime, nullable=True)


class Trade(Base):
    """
    Trade model - individual trade executions.
    A single order can result in multiple trades.
    """
    __tablename__ = "trades"
    
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, nullable=False, index=True)
    external_id = Column(String(100), nullable=True)  # Broker trade ID
    
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(SQLEnum(OrderSideEnum), nullable=False)
    type = Column(SQLEnum(TradeTypeEnum), nullable=False)
    
    # Trade details
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    commission = Column(Float, default=0.0)
    fees = Column(Float, default=0.0)
    
    # P&L tracking
    realized_pnl = Column(Float, nullable=True)
    
    # Timestamps
    executed_at = Column(DateTime, default=func.now(), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)


class Strategy(Base):
    """
    Strategy model - trading strategy configurations.
    """
    __tablename__ = "strategies"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    strategy_type = Column(String(50), nullable=False)  # e.g., "momentum", "mean_reversion"
    
    # Configuration (JSON for flexibility)
    config = Column(JSON, nullable=False, default={})
    
    # Status
    is_active = Column(Boolean, default=False)
    is_enabled = Column(Boolean, default=True)
    
    # Performance metrics (placeholders)
    total_trades = Column(Integer, default=0)
    win_rate = Column(Float, nullable=True)
    total_pnl = Column(Float, default=0.0)
    
    # Timestamps
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    last_run_at = Column(DateTime, nullable=True)


class Config(Base):
    """
    Config model - application configuration settings.
    Key-value store for system settings.
    """
    __tablename__ = "config"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), nullable=False, unique=True, index=True)
    value = Column(Text, nullable=False)
    value_type = Column(String(20), nullable=False)  # "string", "int", "float", "bool", "json"
    description = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)


class AuditLog(Base):
    """
    AuditLog model - tracks all system events and actions.
    Used for compliance, debugging, and audit trails.
    """
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(SQLEnum(AuditEventTypeEnum), nullable=False, index=True)
    description = Column(Text, nullable=False)
    details = Column(JSON, nullable=True)
    
    # Optional references
    user_id = Column(String(100), nullable=True, index=True)
    strategy_id = Column(Integer, nullable=True, index=True)
    order_id = Column(Integer, nullable=True, index=True)
    
    # Timestamps
    timestamp = Column(DateTime, default=func.now(), nullable=False, index=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)


class PortfolioSnapshot(Base):
    """
    Persisted portfolio/account snapshot for chart continuity and analytics.
    """
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False, index=True)
    equity = Column(Float, nullable=False, default=0.0)
    cash = Column(Float, nullable=False, default=0.0)
    buying_power = Column(Float, nullable=False, default=0.0)
    market_value = Column(Float, nullable=False, default=0.0)
    unrealized_pnl = Column(Float, nullable=False, default=0.0)
    realized_pnl_total = Column(Float, nullable=False, default=0.0)
    open_positions = Column(Integer, nullable=False, default=0)
