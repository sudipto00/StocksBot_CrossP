"""
API Routes.
Defines all REST API endpoints for StocksBot.
"""
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from sqlalchemy.orm import Session

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
from storage.database import get_db
from storage.service import StorageService

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
    
    # Convert DB models to API models
    api_strategies = [
        Strategy(
            id=str(s.id),
            name=s.name,
            description=s.description or "",
            status=StrategyStatus.RUNNING if s.is_active else StrategyStatus.STOPPED,
            symbols=[],  # Symbols can be stored in config JSON
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in db_strategies
    ]
    
    return StrategiesResponse(
        strategies=api_strategies,
        total_count=len(api_strategies),
    )


@router.post("/strategies", response_model=Strategy)
async def create_strategy(request: StrategyCreateRequest, db: Session = Depends(get_db)):
    """
    Create a new strategy and persist to database.
    """
    storage = StorageService(db)
    
    # Check if strategy with same name exists
    existing = storage.strategies.get_by_name(request.name)
    if existing:
        raise HTTPException(status_code=400, detail="Strategy with this name already exists")
    
    # Create strategy in database
    db_strategy = storage.strategies.create(
        name=request.name,
        description=request.description or "",
        strategy_type="custom",  # Default type
        config={"symbols": request.symbols}  # Store symbols in config
    )
    
    # Create audit log
    storage.create_audit_log(
        event_type="strategy_started",
        description=f"Strategy '{request.name}' created",
        strategy_id=db_strategy.id
    )
    
    # Convert to API model
    strategy = Strategy(
        id=str(db_strategy.id),
        name=db_strategy.name,
        description=db_strategy.description or "",
        status=StrategyStatus.STOPPED,
        symbols=request.symbols,
        created_at=db_strategy.created_at,
        updated_at=db_strategy.updated_at,
    )
    
    return strategy


@router.get("/strategies/{strategy_id}", response_model=Strategy)
async def get_strategy(strategy_id: str, db: Session = Depends(get_db)):
    """
    Get a specific strategy by ID from database.
    """
    storage = StorageService(db)
    
    try:
        db_strategy = storage.strategies.get_by_id(int(strategy_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid strategy ID")
    
    if not db_strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    # Convert to API model
    symbols = db_strategy.config.get("symbols", []) if db_strategy.config else []
    strategy = Strategy(
        id=str(db_strategy.id),
        name=db_strategy.name,
        description=db_strategy.description or "",
        status=StrategyStatus.RUNNING if db_strategy.is_active else StrategyStatus.STOPPED,
        symbols=symbols,
        created_at=db_strategy.created_at,
        updated_at=db_strategy.updated_at,
    )
    
    return strategy


@router.put("/strategies/{strategy_id}", response_model=Strategy)
async def update_strategy(
    strategy_id: str,
    request: StrategyUpdateRequest,
    db: Session = Depends(get_db)
):
    """
    Update a strategy in the database.
    """
    storage = StorageService(db)
    
    try:
        db_strategy = storage.strategies.get_by_id(int(strategy_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid strategy ID")
    
    if not db_strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    # Update fields
    if request.name is not None:
        db_strategy.name = request.name
    if request.description is not None:
        db_strategy.description = request.description
    if request.symbols is not None:
        if not db_strategy.config:
            db_strategy.config = {}
        db_strategy.config["symbols"] = request.symbols
    if request.status is not None:
        db_strategy.is_active = (request.status == StrategyStatus.RUNNING)
    
    # Save changes
    db_strategy = storage.strategies.update(db_strategy)
    
    # Create audit log
    storage.create_audit_log(
        event_type="config_updated",
        description=f"Strategy '{db_strategy.name}' updated",
        strategy_id=db_strategy.id
    )
    
    # Convert to API model
    symbols = db_strategy.config.get("symbols", []) if db_strategy.config else []
    strategy = Strategy(
        id=str(db_strategy.id),
        name=db_strategy.name,
        description=db_strategy.description or "",
        status=StrategyStatus.RUNNING if db_strategy.is_active else StrategyStatus.STOPPED,
        symbols=symbols,
        created_at=db_strategy.created_at,
        updated_at=db_strategy.updated_at,
    )
    
    return strategy


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
    
    # Check if strategy exists
    db_strategy = storage.strategies.get_by_id(strategy_id_int)
    if not db_strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    # Create audit log before deletion
    storage.create_audit_log(
        event_type="strategy_stopped",
        description=f"Strategy '{db_strategy.name}' deleted",
        strategy_id=strategy_id_int
    )
    
    # Delete strategy
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
    
    # Get audit logs from database
    db_logs = storage.get_audit_logs(
        limit=limit,
        offset=0,
        event_type=event_type.value if event_type else None
    )
    
    # Get total count
    total_count = storage.count_audit_logs(
        event_type=event_type.value if event_type else None
    )
    
    # Convert DB models to API models
    api_logs = [
        AuditLog(
            id=str(log.id),
            timestamp=log.timestamp,
            event_type=AuditEventType(log.event_type.value),
            description=log.description,
            details=log.details or {}
        )
        for log in db_logs
    ]
    
    return AuditLogsResponse(
        logs=api_logs,
        total_count=total_count,
    )


# ============================================================================
# Strategy Runner Endpoints
# ============================================================================

# Global strategy runner instance (singleton)
_runner_instance = None
_runner_lock = None


def get_runner_instance():
    """Get or create the global strategy runner instance."""
    global _runner_instance, _runner_lock
    
    if _runner_lock is None:
        import threading
        _runner_lock = threading.Lock()
    
    with _runner_lock:
        if _runner_instance is None:
            from engine.strategy_runner import StrategyRunner
            from typing import Dict, List, Optional
            import os
            
            # Try to create Alpaca broker with env vars, fall back to mock
            try:
                from integrations.alpaca_broker import AlpacaBroker
                api_key = os.getenv('ALPACA_API_KEY', '')
                secret_key = os.getenv('ALPACA_SECRET_KEY', '')
                
                if api_key and secret_key:
                    broker = AlpacaBroker(api_key=api_key, secret_key=secret_key, paper=True)
                else:
                    raise ValueError("No API keys provided, using mock broker")
            except Exception as e:
                print(f"Failed to create Alpaca broker, using mock: {e}")
                # Fallback to mock broker
                from services.broker import BrokerInterface, OrderSide, OrderType
                
                class MockBroker(BrokerInterface):
                    """Mock broker for testing."""
                    def __init__(self):
                        self._connected = False
                    
                    def connect(self) -> bool:
                        self._connected = True
                        return True
                    
                    def disconnect(self) -> bool:
                        self._connected = False
                        return True
                    
                    def is_connected(self) -> bool:
                        return self._connected
                    
                    def get_account_info(self) -> Dict:
                        return {"cash": 100000.0, "portfolio_value": 100000.0, "buying_power": 100000.0}
                    
                    def get_positions(self) -> List[Dict]:
                        return []
                    
                    def submit_order(self, symbol: str, side: OrderSide, order_type: OrderType,
                                   quantity: float, price: Optional[float] = None) -> Dict:
                        return {"id": "mock-order-1", "symbol": symbol, "status": "filled"}
                    
                    def cancel_order(self, order_id: str) -> bool:
                        return True
                    
                    def get_order(self, order_id: str) -> Dict:
                        return {"id": order_id, "status": "filled"}
                    
                    def get_orders(self, status: Optional[str] = None) -> List[Dict]:
                        return []
                    
                    def get_market_data(self, symbol: str) -> Dict:
                        return {"symbol": symbol, "price": 100.0}
                
                broker = MockBroker()
            
            # Create runner with default settings
            _runner_instance = StrategyRunner(
                broker=broker,
                storage_service=None,  # Will be set when starting
                tick_interval=60.0  # 1 minute
            )
        
        return _runner_instance


@router.post("/runner/start")
async def start_runner(db: Session = Depends(get_db)):
    """
    Start the strategy runner.
    Idempotent - returns success if already running.
    """
    runner = get_runner_instance()
    storage = StorageService(db)
    
    # Set storage service
    runner.storage = storage
    
    # Check if already running
    if runner.status.value == "running":
        return {
            "success": True,
            "message": "Strategy runner is already running",
            "status": runner.get_status()
        }
    
    # Load active strategies from database
    active_strategies = storage.strategies.get_active()
    if not active_strategies:
        return {
            "success": False,
            "message": "No active strategies found. Please enable at least one strategy.",
            "status": runner.get_status()
        }
    
    # Start the runner
    success = runner.start()
    
    if success:
        # Create audit log
        storage.create_audit_log(
            event_type="strategy_started",
            description=f"Strategy runner started with {len(active_strategies)} active strategies"
        )
        
        return {
            "success": True,
            "message": "Strategy runner started successfully",
            "status": runner.get_status()
        }
    else:
        return {
            "success": False,
            "message": "Failed to start strategy runner",
            "status": runner.get_status()
        }


@router.post("/runner/stop")
async def stop_runner(db: Session = Depends(get_db)):
    """
    Stop the strategy runner.
    Idempotent - returns success if already stopped.
    """
    runner = get_runner_instance()
    storage = StorageService(db)
    
    # Check if already stopped
    if runner.status.value == "stopped":
        return {
            "success": True,
            "message": "Strategy runner is already stopped",
            "status": runner.get_status()
        }
    
    # Stop the runner
    success = runner.stop()
    
    if success:
        # Create audit log
        storage.create_audit_log(
            event_type="strategy_stopped",
            description="Strategy runner stopped"
        )
        
        return {
            "success": True,
            "message": "Strategy runner stopped successfully",
            "status": runner.get_status()
        }
    else:
        return {
            "success": False,
            "message": "Failed to stop strategy runner",
            "status": runner.get_status()
        }


@router.get("/runner/status")
async def get_runner_status():
    """
    Get the current status of the strategy runner.
    """
    runner = get_runner_instance()
    status = runner.get_status()
    
    return {
        "success": True,
        "status": status
    }
