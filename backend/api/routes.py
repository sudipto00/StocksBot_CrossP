"""
API Routes.
Defines all REST API endpoints for StocksBot.
"""
from datetime import datetime
from fastapi import APIRouter, HTTPException
from typing import List, Optional

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


# ============================================================================
# Strategy Endpoints
# ============================================================================

# In-memory strategy store (TODO: Replace with persistent storage)
_strategies: dict[str, Strategy] = {}
_strategy_counter = 0


@router.get("/strategies", response_model=StrategiesResponse)
async def get_strategies():
    """
    Get all strategies.
    TODO: Load from database.
    Returns stub data for now.
    """
    return StrategiesResponse(
        strategies=list(_strategies.values()),
        total_count=len(_strategies),
    )


@router.post("/strategies", response_model=Strategy)
async def create_strategy(request: StrategyCreateRequest):
    """
    Create a new strategy.
    TODO: Persist to database and validate.
    This is a stub implementation.
    """
    global _strategy_counter
    _strategy_counter += 1
    
    strategy_id = f"strat-{_strategy_counter}"
    now = datetime.now()
    
    strategy = Strategy(
        id=strategy_id,
        name=request.name,
        description=request.description,
        status=StrategyStatus.STOPPED,
        symbols=request.symbols,
        created_at=now,
        updated_at=now,
    )
    
    _strategies[strategy_id] = strategy
    return strategy


@router.get("/strategies/{strategy_id}", response_model=Strategy)
async def get_strategy(strategy_id: str):
    """
    Get a specific strategy by ID.
    TODO: Load from database.
    """
    if strategy_id not in _strategies:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    return _strategies[strategy_id]


@router.put("/strategies/{strategy_id}", response_model=Strategy)
async def update_strategy(strategy_id: str, request: StrategyUpdateRequest):
    """
    Update a strategy.
    TODO: Persist to database and validate.
    This is a stub implementation.
    """
    if strategy_id not in _strategies:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    strategy = _strategies[strategy_id]
    
    if request.name is not None:
        strategy.name = request.name
    if request.description is not None:
        strategy.description = request.description
    if request.symbols is not None:
        strategy.symbols = request.symbols
    if request.status is not None:
        strategy.status = request.status
    
    strategy.updated_at = datetime.now()
    
    return strategy


@router.delete("/strategies/{strategy_id}")
async def delete_strategy(strategy_id: str):
    """
    Delete a strategy.
    TODO: Remove from database.
    This is a stub implementation.
    """
    if strategy_id not in _strategies:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    del _strategies[strategy_id]
    
    return {"message": "Strategy deleted"}


# ============================================================================
# Audit Log Endpoints
# ============================================================================

# In-memory audit log store (TODO: Replace with persistent storage)
_audit_logs: List[AuditLog] = []


@router.get("/audit/logs", response_model=AuditLogsResponse)
async def get_audit_logs(
    limit: int = 100,
    event_type: Optional[AuditEventType] = None
):
    """
    Get audit logs.
    TODO: Load from database with filtering and pagination.
    Returns stub data for now.
    """
    # Generate some stub data if empty
    if not _audit_logs:
        _generate_stub_audit_logs()
    
    # Filter by event type if specified
    logs = _audit_logs
    if event_type:
        logs = [log for log in logs if log.event_type == event_type]
    
    # Apply limit
    logs = logs[:limit]
    
    return AuditLogsResponse(
        logs=logs,
        total_count=len(_audit_logs),
    )


def _generate_stub_audit_logs():
    """Generate stub audit log data for development."""
    global _audit_logs
    
    now = datetime.now()
    
    _audit_logs = [
        AuditLog(
            id="log-001",
            timestamp=now,
            event_type=AuditEventType.ORDER_CREATED,
            description="Market order created for AAPL",
            details={"symbol": "AAPL", "quantity": 100, "side": "buy"}
        ),
        AuditLog(
            id="log-002",
            timestamp=now,
            event_type=AuditEventType.ORDER_FILLED,
            description="Order filled for AAPL at $150.00",
            details={"symbol": "AAPL", "quantity": 100, "price": 150.00}
        ),
        AuditLog(
            id="log-003",
            timestamp=now,
            event_type=AuditEventType.POSITION_OPENED,
            description="Position opened: AAPL 100 shares",
            details={"symbol": "AAPL", "quantity": 100}
        ),
    ]
