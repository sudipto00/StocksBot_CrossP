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
from services.broker import BrokerInterface, PaperBroker
from services.order_execution import OrderExecutionService, OrderValidationError, BrokerError
from config.settings import get_settings, has_alpaca_credentials

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
    # Strategy configuration models
    StrategyConfigResponse,
    StrategyConfigUpdateRequest,
    StrategyMetricsResponse,
    BacktestRequest,
    BacktestResponse,
    ParameterTuneRequest,
    ParameterTuneResponse,
    StrategyParameter,
)
from .runner_manager import runner_manager
from services.strategy_analytics import StrategyAnalyticsService
from config.strategy_config import get_default_parameters

router = APIRouter()

# ============================================================================
# Broker Initialization
# ============================================================================

_broker_instance: Optional[BrokerInterface] = None


def get_broker() -> BrokerInterface:
    """
    Get or create broker instance.
    
    Returns:
        Configured broker instance (Paper or Alpaca)
    """
    global _broker_instance
    
    if _broker_instance is None:
        settings = get_settings()
        
        # Use Alpaca if credentials are available, otherwise use PaperBroker
        if has_alpaca_credentials():
            from integrations.alpaca_broker import AlpacaBroker
            _broker_instance = AlpacaBroker(
                api_key=settings.alpaca_api_key,
                secret_key=settings.alpaca_secret_key,
                paper=settings.alpaca_paper
            )
        else:
            _broker_instance = PaperBroker()
        
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
    
    # Get config for risk limits
    config = _config
    
    return OrderExecutionService(
        broker=broker,
        storage=storage,
        max_position_size=config.max_position_size,
        risk_limit_daily=config.risk_limit_daily
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
        enabled=db_strategy.is_active,
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
    
    # Update config
    if not db_strategy.config:
        db_strategy.config = {}
    
    config_changed = False
    if request.symbols is not None:
        db_strategy.config['symbols'] = request.symbols
        config_changed = True
    
    if request.parameters is not None:
        if 'parameters' not in db_strategy.config:
            db_strategy.config['parameters'] = {}
        db_strategy.config['parameters'].update(request.parameters)
        config_changed = True
    
    if request.enabled is not None:
        db_strategy.is_active = request.enabled
    
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
    
    # Use strategy symbols if not provided in request
    if not request.symbols and db_strategy.config:
        request.symbols = db_strategy.config.get('symbols', ['AAPL', 'MSFT'])
    
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