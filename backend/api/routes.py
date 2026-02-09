"""
API Routes.
Defines all REST API endpoints for StocksBot.
"""
from datetime import datetime
from fastapi import APIRouter, HTTPException
from typing import List

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
)

router = APIRouter()


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
    broker="paper",
)


@router.get("/config", response_model=ConfigResponse)
async def get_config():
    """
    Get current configuration.
    TODO: Load from persistent storage.
    """
    return _config


@router.post("/config", response_model=ConfigResponse)
async def update_config(request: ConfigUpdateRequest):
    """
    Update configuration.
    TODO: Persist to storage and validate changes.
    """
    global _config
    
    if request.trading_enabled is not None:
        _config.trading_enabled = request.trading_enabled
    if request.paper_trading is not None:
        _config.paper_trading = request.paper_trading
    if request.max_position_size is not None:
        _config.max_position_size = request.max_position_size
    if request.risk_limit_daily is not None:
        _config.risk_limit_daily = request.risk_limit_daily
    
    return _config


# ============================================================================
# Positions Endpoints
# ============================================================================

@router.get("/positions", response_model=PositionsResponse)
async def get_positions():
    """
    Get current positions.
    TODO: Integrate with portfolio service and broker API.
    Returns stub data for now.
    """
    # Stub data for development
    stub_positions = [
        Position(
            symbol="AAPL",
            side=PositionSide.LONG,
            quantity=100,
            avg_entry_price=150.00,
            current_price=155.00,
            unrealized_pnl=500.00,
            unrealized_pnl_percent=3.33,
            cost_basis=15000.00,
            market_value=15500.00,
        ),
        Position(
            symbol="MSFT",
            side=PositionSide.LONG,
            quantity=50,
            avg_entry_price=300.00,
            current_price=310.00,
            unrealized_pnl=500.00,
            unrealized_pnl_percent=3.33,
            cost_basis=15000.00,
            market_value=15500.00,
        ),
    ]
    
    total_value = sum(p.market_value for p in stub_positions)
    total_pnl = sum(p.unrealized_pnl for p in stub_positions)
    total_cost = sum(p.cost_basis for p in stub_positions)
    total_pnl_percent = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0
    
    return PositionsResponse(
        positions=stub_positions,
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


@router.post("/orders")
async def create_order(request: OrderRequest):
    """
    Create a new order.
    TODO: Validate order, integrate with order service and broker API.
    This is a placeholder that doesn't execute real trades.
    """
    # Placeholder response
    return {
        "message": f"Order placeholder created for {request.quantity} shares of {request.symbol}",
        "note": "This is a stub endpoint. Real order execution not implemented.",
    }


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
    # Placeholder - just log for now
    print(f"[NOTIFICATION] {request.severity.upper()}: {request.title} - {request.message}")
    
    return NotificationResponse(
        success=True,
        message="Notification queued (placeholder)",
    )
