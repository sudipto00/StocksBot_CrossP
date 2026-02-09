"""
API Routes.
Defines all REST API endpoints for StocksBot.
"""
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from sqlalchemy.orm import Session

from storage.database import get_db
from storage.service import StorageService

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
    # Runner models
    RunnerStatusResponse,
    RunnerActionResponse,
)
from .runner_manager import runner_manager

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

    db_strategy = storage.strategies.create(
        name=request.name,
        description=request.description or "",
        strategy_type="custom",
        config={"symbols": request.symbols},
    )

    storage.create_audit_log(
        event_type="strategy_started",
        description=f"Strategy created: {request.name}",
        details={"strategy_id": db_strategy.id, "symbols": request.symbols},
    )

    return Strategy(
        id=str(db_strategy.id),
        name=db_strategy.name,
        description=db_strategy.description or "",
        status=StrategyStatus.STOPPED,
        symbols=request.symbols,
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
        db_strategy.config["symbols"] = request.symbols
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

    storage.create_audit_log(
        event_type="strategy_stopped",
        description=f"Strategy deleted: {db_strategy.name}",
        details={"strategy_id": db_strategy.id},
    )

    storage.strategies.delete(strategy_id_int)

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

    event_type_str = event_type.value if event_type else None
    db_logs = storage.get_audit_logs(limit=limit, event_type=event_type_str)
    total_count = storage.count_audit_logs(event_type=event_type_str)

    logs = []
    for db_log in db_logs:
        logs.append(AuditLog(
            id=str(db_log.id),
            timestamp=db_log.timestamp,
            event_type=AuditEventType(db_log.event_type),
            description=db_log.description,
            details=db_log.details or {},
        ))

    return AuditLogsResponse(
        logs=logs,
        total_count=total_count,
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


@router.post("/runner/start", response_model=RunnerActionResponse)
async def start_runner():
    """
    Start the strategy runner.
    Loads active strategies and begins execution loop.
    Idempotent - safe to call multiple times.
    """
    result = runner_manager.start_runner()
    return RunnerActionResponse(**result)


@router.post("/runner/stop", response_model=RunnerActionResponse)
async def stop_runner():
    """
    Stop the strategy runner.
    Stops all strategies and the execution loop.
    Idempotent - safe to call multiple times.
    """
    result = runner_manager.stop_runner()
    return RunnerActionResponse(**result)


# ============================================================================
# Portfolio Analytics Endpoints
# ============================================================================

@router.get("/analytics/portfolio")
async def get_portfolio_analytics(
    days: int = 30,
    db: Session = Depends(get_db)
):
    """
    Get portfolio analytics time series data.
    Returns equity curve and P&L over time.
    """
    storage = StorageService(db)

    trades = storage.get_recent_trades(limit=1000)

    time_series = []
    cumulative_pnl = 0.0
    equity = 100000.0

    for trade in reversed(trades):
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
        'total_trades': len(trades),
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