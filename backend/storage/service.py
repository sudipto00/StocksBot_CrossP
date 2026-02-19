"""
Storage service - High-level interface for storage operations.
Provides business logic on top of repositories.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from storage.repositories import (
    PositionRepository, OrderRepository, TradeRepository,
    StrategyRepository, ConfigRepository, AuditLogRepository, PortfolioSnapshotRepository,
    OptimizationRunRepository,
)
from storage.models import (
    Position, Order, Trade, Strategy, Config, AuditLog, PortfolioSnapshot, OptimizationRun,
    PositionSideEnum, OrderSideEnum, OrderTypeEnum, OrderStatusEnum, TradeTypeEnum,
    AuditEventTypeEnum
)


class StorageService:
    """
    Main storage service coordinating all repository operations.
    This is the primary interface for backend services to interact with storage.
    """
    
    def __init__(self, db: Session):
        """Initialize storage service with database session."""
        self.db = db
        self.positions = PositionRepository(db)
        self.orders = OrderRepository(db)
        self.trades = TradeRepository(db)
        self.strategies = StrategyRepository(db)
        self.config = ConfigRepository(db)
        self.audit_logs = AuditLogRepository(db)
        self.portfolio_snapshots = PortfolioSnapshotRepository(db)
        self.optimization_runs = OptimizationRunRepository(db)
    
    # Position operations
    
    def get_open_positions(self) -> List[Position]:
        """Get all open positions."""
        return self.positions.get_all_open()
    
    def get_position_by_symbol(self, symbol: str) -> Optional[Position]:
        """Get open position for a symbol."""
        return self.positions.get_by_symbol(symbol, is_open=True)
    
    def create_position(self, symbol: str, side: str, quantity: float,
                       avg_entry_price: float) -> Position:
        """Create a new position."""
        cost_basis = quantity * avg_entry_price
        return self.positions.create(
            symbol=symbol,
            side=PositionSideEnum(side),
            quantity=quantity,
            avg_entry_price=avg_entry_price,
            cost_basis=cost_basis
        )
    
    def update_position_quantity(self, position: Position, quantity_delta: float,
                                 price: float) -> Position:
        """
        Update position quantity and recalculate cost basis.
        
        Args:
            position: Position to update
            quantity_delta: Change in quantity (positive for buy, negative for sell)
            price: Transaction price
        
        Returns:
            Updated position
        """
        new_quantity = position.quantity + quantity_delta
        
        if new_quantity == 0:
            # Position closed
            if position.side == PositionSideEnum.LONG:
                realized_pnl = quantity_delta * (price - position.avg_entry_price)
            else:  # SHORT
                realized_pnl = quantity_delta * (position.avg_entry_price - price)
            
            return self.positions.close_position(position, realized_pnl)
        else:
            if abs(new_quantity) > abs(position.quantity):
                total_cost = position.cost_basis + (abs(quantity_delta) * price)
                position.avg_entry_price = total_cost / abs(new_quantity)
            
            position.quantity = new_quantity
            position.cost_basis = abs(new_quantity) * position.avg_entry_price
            return self.positions.update(position)
    
    # Order operations
    
    def create_order(self, symbol: str, side: str, order_type: str,
                     quantity: float, price: Optional[float] = None,
                     strategy_id: Optional[int] = None) -> Order:
        """Create a new order."""
        return self.orders.create(
            symbol=symbol,
            side=OrderSideEnum(side),
            type=OrderTypeEnum(order_type),
            quantity=quantity,
            price=price,
            strategy_id=strategy_id
        )
    
    def get_recent_orders(self, limit: int = 100) -> List[Order]:
        """Get recent orders."""
        return self.orders.get_recent(limit)

    def get_open_orders(self, limit: int = 500) -> List[Order]:
        """Get broker-submitted orders that are not terminal yet."""
        return self.orders.get_open_orders(limit=limit)
    
    def update_order_status(self, order_id: int, status: str,
                           filled_quantity: Optional[float] = None,
                           avg_fill_price: Optional[float] = None) -> Optional[Order]:
        """Update order status."""
        order = self.orders.get_by_id(order_id)
        if order:
            return self.orders.update_status(
                order, OrderStatusEnum(status), filled_quantity, avg_fill_price
            )
        return None
    
    # Trade operations
    
    def record_trade(self, order_id: int, symbol: str, side: str,
                    quantity: float, price: float,
                    commission: float = 0.0, fees: float = 0.0) -> Trade:
        """Record a trade execution."""
        return self.trades.create(
            order_id=order_id,
            symbol=symbol,
            side=OrderSideEnum(side),
            type=TradeTypeEnum.OPEN,
            quantity=quantity,
            price=price,
            commission=commission,
            fees=fees
        )
    
    def get_recent_trades(self, limit: int = 100) -> List[Trade]:
        """Get recent trades."""
        return self.trades.get_recent(limit)

    def get_all_trades(self, limit: int = 5000) -> List[Trade]:
        """Get full trade history ordered by execution time."""
        return self.trades.get_all(limit=limit)
    
    # Strategy operations
    
    def create_strategy(self, name: str, strategy_type: str,
                       config: Dict[str, Any],
                       description: Optional[str] = None) -> Strategy:
        """Create a new strategy."""
        return self.strategies.create(name, strategy_type, config, description)
    
    def get_active_strategies(self) -> List[Strategy]:
        """Get all active strategies."""
        return self.strategies.get_active()
    
    def get_strategy_by_name(self, name: str) -> Optional[Strategy]:
        """Get strategy by name."""
        return self.strategies.get_by_name(name)
    
    # Config operations
    
    def get_config_value(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get config value by key."""
        config = self.config.get_by_key(key)
        return config.value if config else default
    
    def set_config_value(self, key: str, value: str, value_type: str = "string",
                        description: Optional[str] = None) -> Config:
        """Set config value (create or update)."""
        return self.config.upsert(key, value, value_type, description)
    
    def get_all_config(self) -> Dict[str, str]:
        """Get all config as a dictionary."""
        configs = self.config.get_all()
        return {c.key: c.value for c in configs}
    
    # Audit log operations
    
    def create_audit_log(
        self,
        event_type: str,
        description: str,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        strategy_id: Optional[int] = None,
        order_id: Optional[int] = None
    ) -> AuditLog:
        """Create a new audit log entry."""
        return self.audit_logs.create(
            event_type=AuditEventTypeEnum(event_type),
            description=description,
            details=details,
            user_id=user_id,
            strategy_id=strategy_id,
            order_id=order_id
        )
    
    def get_audit_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        event_type: Optional[str] = None,
        strategy_id: Optional[int] = None,
        order_id: Optional[int] = None
    ) -> List[AuditLog]:
        """Get audit logs with filtering and pagination."""
        event_type_enum = AuditEventTypeEnum(event_type) if event_type else None
        return self.audit_logs.get_all(
            limit=limit,
            offset=offset,
            event_type=event_type_enum,
            strategy_id=strategy_id,
            order_id=order_id
        )
    
    def count_audit_logs(
        self,
        event_type: Optional[str] = None,
        strategy_id: Optional[int] = None,
        order_id: Optional[int] = None
    ) -> int:
        """Count audit logs with optional filtering."""
        event_type_enum = AuditEventTypeEnum(event_type) if event_type else None
        return self.audit_logs.count(
            event_type=event_type_enum,
            strategy_id=strategy_id,
            order_id=order_id
        )
    
    def get_trades_by_strategy(self, strategy_id: int) -> List[Trade]:
        """Get all trades for a specific strategy."""
        # For now, return recent trades since we don't have strategy_id on trades
        # In a full implementation, Trade model would have a strategy_id field
        return self.trades.get_recent(limit=1000)

    # Portfolio snapshot operations

    def record_portfolio_snapshot(
        self,
        equity: float,
        cash: float,
        buying_power: float,
        market_value: float,
        unrealized_pnl: float,
        realized_pnl_total: float,
        open_positions: int,
        timestamp: Optional[datetime] = None,
    ) -> PortfolioSnapshot:
        """Persist an account/portfolio snapshot row."""
        return self.portfolio_snapshots.create(
            equity=float(equity),
            cash=float(cash),
            buying_power=float(buying_power),
            market_value=float(market_value),
            unrealized_pnl=float(unrealized_pnl),
            realized_pnl_total=float(realized_pnl_total),
            open_positions=int(open_positions),
            timestamp=timestamp,
        )

    def get_recent_portfolio_snapshots(self, limit: int = 5000) -> List[PortfolioSnapshot]:
        """Return most recent snapshots in ascending order."""
        return self.portfolio_snapshots.get_recent(limit=limit)

    def get_latest_portfolio_snapshot(self) -> Optional[PortfolioSnapshot]:
        """Return latest snapshot row, if present."""
        return self.portfolio_snapshots.get_latest()

    def get_portfolio_snapshots_since(
        self,
        cutoff: Optional[datetime] = None,
        limit: int = 5000,
    ) -> List[PortfolioSnapshot]:
        """Get snapshots with optional UTC cutoff."""
        snapshots = self.get_recent_portfolio_snapshots(limit=limit)
        if cutoff is None:
            return snapshots
        cutoff_utc = cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=timezone.utc)
        filtered: List[PortfolioSnapshot] = []
        for snapshot in snapshots:
            ts = snapshot.timestamp
            if ts is None:
                continue
            ts_utc = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            if ts_utc >= cutoff_utc:
                filtered.append(snapshot)
        return filtered

    # Optimization history operations

    def upsert_optimization_run(
        self,
        *,
        run_id: str,
        strategy_id: int,
        strategy_name: str,
        source: str,
        status: str,
        job_id: Optional[str],
        request_payload: Dict[str, Any],
        result_payload: Optional[Dict[str, Any]],
        error: Optional[str],
        objective: Optional[str],
        score: Optional[float],
        total_return: Optional[float],
        sharpe_ratio: Optional[float],
        max_drawdown: Optional[float],
        total_trades: Optional[int],
        win_rate: Optional[float],
        recommended_symbol_count: int,
        requested_iterations: Optional[int],
        evaluated_iterations: Optional[int],
        created_at: Optional[datetime] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
    ) -> OptimizationRun:
        """Create or update an optimization run row."""
        return self.optimization_runs.upsert(
            run_id=run_id,
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            source=source,
            status=status,
            job_id=job_id,
            request_payload=request_payload,
            result_payload=result_payload,
            error=error,
            objective=objective,
            score=score,
            total_return=total_return,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            total_trades=total_trades,
            win_rate=win_rate,
            recommended_symbol_count=recommended_symbol_count,
            requested_iterations=requested_iterations,
            evaluated_iterations=evaluated_iterations,
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
        )

    def list_recent_optimization_runs(
        self,
        *,
        strategy_ids: Optional[List[int]] = None,
        statuses: Optional[List[str]] = None,
        sources: Optional[List[str]] = None,
        limit_per_strategy: int = 10,
        limit_total: int = 200,
    ) -> List[OptimizationRun]:
        """List recent optimization runs for one or more strategies."""
        return self.optimization_runs.list_recent(
            strategy_ids=strategy_ids,
            statuses=statuses,
            sources=sources,
            limit_per_strategy=limit_per_strategy,
            limit_total=limit_total,
        )

    def get_optimization_run_by_run_id(self, run_id: str) -> Optional[OptimizationRun]:
        """Fetch optimization run by stable run_id."""
        return self.optimization_runs.get_by_run_id(run_id)

    def prune_strategy_optimization_history(self, strategy_id: int, keep: int) -> int:
        """Prune older optimization runs for a strategy."""
        return self.optimization_runs.prune_strategy_history(strategy_id=strategy_id, keep=keep)

    def delete_optimization_runs(
        self,
        *,
        statuses: Optional[List[str]] = None,
        source: Optional[str] = None,
        strategy_id: Optional[int] = None,
        older_than: Optional[datetime] = None,
    ) -> int:
        """Delete optimization runs matching filters."""
        return self.optimization_runs.delete_runs(
            statuses=statuses,
            source=source,
            strategy_id=strategy_id,
            older_than=older_than,
        )
