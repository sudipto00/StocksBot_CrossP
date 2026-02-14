"""
Repository classes for database CRUD operations.
Provides abstraction layer between services and database models.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from storage.models import (
    Position, Order, Trade, Strategy, Config, AuditLog, PortfolioSnapshot,
    PositionSideEnum, OrderSideEnum, OrderTypeEnum, OrderStatusEnum, TradeTypeEnum,
    AuditEventTypeEnum
)


class PositionRepository:
    """Repository for Position CRUD operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, symbol: str, side: PositionSideEnum, quantity: float,
               avg_entry_price: float, cost_basis: float) -> Position:
        """Create a new position."""
        position = Position(
            symbol=symbol,
            side=side,
            quantity=quantity,
            avg_entry_price=avg_entry_price,
            cost_basis=cost_basis,
            is_open=True
        )
        self.db.add(position)
        self.db.commit()
        self.db.refresh(position)
        return position
    
    def get_by_id(self, position_id: int) -> Optional[Position]:
        """Get position by ID."""
        return self.db.query(Position).filter(Position.id == position_id).first()
    
    def get_by_symbol(self, symbol: str, is_open: bool = True) -> Optional[Position]:
        """Get open position by symbol."""
        return self.db.query(Position).filter(
            and_(Position.symbol == symbol, Position.is_open == is_open)
        ).first()
    
    def get_all_open(self) -> List[Position]:
        """Get all open positions."""
        return self.db.query(Position).filter(Position.is_open == True).all()
    
    def get_all(self, limit: int = 100, offset: int = 0) -> List[Position]:
        """Get all positions with pagination."""
        return self.db.query(Position).offset(offset).limit(limit).all()
    
    def update(self, position: Position) -> Position:
        """Update an existing position."""
        position.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(position)
        return position
    
    def close_position(self, position: Position, realized_pnl: float) -> Position:
        """Close a position."""
        position.is_open = False
        position.closed_at = datetime.now()
        position.realized_pnl = realized_pnl
        return self.update(position)
    
    def delete(self, position_id: int) -> bool:
        """Delete a position (use with caution)."""
        position = self.get_by_id(position_id)
        if position:
            self.db.delete(position)
            self.db.commit()
            return True
        return False


class OrderRepository:
    """Repository for Order CRUD operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, symbol: str, side: OrderSideEnum, type: OrderTypeEnum,
               quantity: float, price: Optional[float] = None,
               strategy_id: Optional[int] = None,
               external_id: Optional[str] = None) -> Order:
        """Create a new order."""
        order = Order(
            symbol=symbol,
            side=side,
            type=type,
            quantity=quantity,
            price=price,
            status=OrderStatusEnum.PENDING,
            strategy_id=strategy_id,
            external_id=external_id
        )
        self.db.add(order)
        self.db.commit()
        self.db.refresh(order)
        return order
    
    def get_by_id(self, order_id: int) -> Optional[Order]:
        """Get order by ID."""
        return self.db.query(Order).filter(Order.id == order_id).first()
    
    def get_by_external_id(self, external_id: str) -> Optional[Order]:
        """Get order by external/broker ID."""
        return self.db.query(Order).filter(Order.external_id == external_id).first()
    
    def get_by_status(self, status: OrderStatusEnum, limit: int = 100) -> List[Order]:
        """Get orders by status."""
        return self.db.query(Order).filter(Order.status == status).limit(limit).all()
    
    def get_by_symbol(self, symbol: str, limit: int = 100) -> List[Order]:
        """Get orders by symbol."""
        return self.db.query(Order).filter(Order.symbol == symbol).limit(limit).all()
    
    def get_recent(self, limit: int = 100) -> List[Order]:
        """Get recent orders."""
        return self.db.query(Order).order_by(Order.created_at.desc()).limit(limit).all()

    def get_open_orders(self, limit: int = 500) -> List[Order]:
        """Get orders that may still change status (pending/open/partially filled)."""
        return (
            self.db.query(Order)
            .filter(Order.status.in_([OrderStatusEnum.PENDING, OrderStatusEnum.OPEN, OrderStatusEnum.PARTIALLY_FILLED]))
            .order_by(Order.created_at.asc())
            .limit(limit)
            .all()
        )
    
    def update_status(self, order: Order, status: OrderStatusEnum,
                     filled_quantity: Optional[float] = None,
                     avg_fill_price: Optional[float] = None) -> Order:
        """Update order status and fill details."""
        order.status = status
        if filled_quantity is not None:
            order.filled_quantity = filled_quantity
        if avg_fill_price is not None:
            order.avg_fill_price = avg_fill_price
        if status == OrderStatusEnum.FILLED:
            order.filled_at = datetime.now()
        return self.update(order)
    
    def update(self, order: Order) -> Order:
        """Update an existing order."""
        order.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(order)
        return order


class TradeRepository:
    """Repository for Trade CRUD operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, order_id: int, symbol: str, side: OrderSideEnum,
               type: TradeTypeEnum, quantity: float, price: float,
               commission: float = 0.0, fees: float = 0.0,
               external_id: Optional[str] = None,
               executed_at: Optional[datetime] = None) -> Trade:
        """Create a new trade."""
        trade = Trade(
            order_id=order_id,
            symbol=symbol,
            side=side,
            type=type,
            quantity=quantity,
            price=price,
            commission=commission,
            fees=fees,
            external_id=external_id,
            executed_at=executed_at or datetime.now()
        )
        self.db.add(trade)
        self.db.commit()
        self.db.refresh(trade)
        return trade
    
    def get_by_id(self, trade_id: int) -> Optional[Trade]:
        """Get trade by ID."""
        return self.db.query(Trade).filter(Trade.id == trade_id).first()
    
    def get_by_order_id(self, order_id: int) -> List[Trade]:
        """Get all trades for an order."""
        return self.db.query(Trade).filter(Trade.order_id == order_id).all()
    
    def get_by_symbol(self, symbol: str, limit: int = 100) -> List[Trade]:
        """Get trades by symbol."""
        return self.db.query(Trade).filter(Trade.symbol == symbol).limit(limit).all()
    
    def get_recent(self, limit: int = 100) -> List[Trade]:
        """Get recent trades."""
        return self.db.query(Trade).order_by(Trade.executed_at.desc()).limit(limit).all()
    
    def get_all(self, limit: int = 1000) -> List[Trade]:
        """Get all trades ordered by execution time."""
        return self.db.query(Trade).order_by(Trade.executed_at.asc()).limit(limit).all()


class StrategyRepository:
    """Repository for Strategy CRUD operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, name: str, strategy_type: str, config: Dict[str, Any],
               description: Optional[str] = None) -> Strategy:
        """Create a new strategy."""
        strategy = Strategy(
            name=name,
            strategy_type=strategy_type,
            config=config,
            description=description
        )
        self.db.add(strategy)
        self.db.commit()
        self.db.refresh(strategy)
        return strategy
    
    def get_by_id(self, strategy_id: int) -> Optional[Strategy]:
        """Get strategy by ID."""
        return self.db.query(Strategy).filter(Strategy.id == strategy_id).first()
    
    def get_by_name(self, name: str) -> Optional[Strategy]:
        """Get strategy by name."""
        return self.db.query(Strategy).filter(Strategy.name == name).first()
    
    def get_active(self) -> List[Strategy]:
        """Get all active strategies."""
        return (
            self.db.query(Strategy)
            .filter(Strategy.is_active == True)
            .filter(or_(Strategy.is_enabled == True, Strategy.is_enabled.is_(None)))
            .all()
        )
    
    def get_all(self) -> List[Strategy]:
        """Get all strategies."""
        return self.db.query(Strategy).all()
    
    def update(self, strategy: Strategy) -> Strategy:
        """Update a strategy."""
        strategy.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(strategy)
        return strategy
    
    def delete(self, strategy_id: int) -> bool:
        """Delete a strategy."""
        strategy = self.get_by_id(strategy_id)
        if strategy:
            self.db.delete(strategy)
            self.db.commit()
            return True
        return False


class ConfigRepository:
    """Repository for Config CRUD operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, key: str, value: str, value_type: str,
               description: Optional[str] = None) -> Config:
        """Create a new config entry."""
        config = Config(
            key=key,
            value=value,
            value_type=value_type,
            description=description
        )
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        return config
    
    def get_by_key(self, key: str) -> Optional[Config]:
        """Get config by key."""
        return self.db.query(Config).filter(Config.key == key).first()
    
    def get_all(self) -> List[Config]:
        """Get all config entries."""
        return self.db.query(Config).all()
    
    def update(self, config: Config, value: str) -> Config:
        """Update config value."""
        config.value = value
        config.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(config)
        return config
    
    def upsert(self, key: str, value: str, value_type: str,
               description: Optional[str] = None) -> Config:
        """Create or update config entry."""
        config = self.get_by_key(key)
        if config:
            return self.update(config, value)
        else:
            return self.create(key, value, value_type, description)
    
    def delete(self, key: str) -> bool:
        """Delete a config entry."""
        config = self.get_by_key(key)
        if config:
            self.db.delete(config)
            self.db.commit()
            return True
        return False


class AuditLogRepository:
    """Repository for AuditLog CRUD operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(
        self,
        event_type: AuditEventTypeEnum,
        description: str,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        strategy_id: Optional[int] = None,
        order_id: Optional[int] = None
    ) -> AuditLog:
        """Create a new audit log entry."""
        audit_log = AuditLog(
            event_type=event_type,
            description=description,
            details=details,
            user_id=user_id,
            strategy_id=strategy_id,
            order_id=order_id
        )
        self.db.add(audit_log)
        self.db.commit()
        self.db.refresh(audit_log)
        return audit_log
    
    def get_by_id(self, log_id: int) -> Optional[AuditLog]:
        """Get audit log by ID."""
        return self.db.query(AuditLog).filter(AuditLog.id == log_id).first()
    
    def get_all(
        self,
        limit: int = 100,
        offset: int = 0,
        event_type: Optional[AuditEventTypeEnum] = None,
        strategy_id: Optional[int] = None,
        order_id: Optional[int] = None
    ) -> List[AuditLog]:
        """Get audit logs with filtering and pagination."""
        query = self.db.query(AuditLog)
        
        if event_type:
            query = query.filter(AuditLog.event_type == event_type)
        if strategy_id:
            query = query.filter(AuditLog.strategy_id == strategy_id)
        if order_id:
            query = query.filter(AuditLog.order_id == order_id)
        
        query = query.order_by(AuditLog.timestamp.desc())
        return query.offset(offset).limit(limit).all()
    
    def count(
        self,
        event_type: Optional[AuditEventTypeEnum] = None,
        strategy_id: Optional[int] = None,
        order_id: Optional[int] = None
    ) -> int:
        """Count audit logs with optional filtering."""
        query = self.db.query(AuditLog)
        
        if event_type:
            query = query.filter(AuditLog.event_type == event_type)
        if strategy_id:
            query = query.filter(AuditLog.strategy_id == strategy_id)
        if order_id:
            query = query.filter(AuditLog.order_id == order_id)
        
        return query.count()
    
    def delete_old_logs(self, days: int = 90) -> int:
        """Delete audit logs older than specified days."""
        from datetime import timedelta
        cutoff_date = datetime.now() - timedelta(days=days)
        
        deleted = self.db.query(AuditLog).filter(
            AuditLog.timestamp < cutoff_date
        ).delete()
        self.db.commit()
        return deleted


def _to_db_datetime(value: datetime) -> datetime:
    """Normalize datetime for DB comparisons/storage."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class PortfolioSnapshotRepository:
    """Repository for portfolio snapshot persistence."""

    def __init__(self, db: Session):
        self.db = db

    def create(
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
        snapshot = PortfolioSnapshot(
            timestamp=_to_db_datetime(timestamp) if timestamp is not None else datetime.now(timezone.utc).replace(tzinfo=None),
            equity=equity,
            cash=cash,
            buying_power=buying_power,
            market_value=market_value,
            unrealized_pnl=unrealized_pnl,
            realized_pnl_total=realized_pnl_total,
            open_positions=open_positions,
        )
        self.db.add(snapshot)
        self.db.commit()
        self.db.refresh(snapshot)
        return snapshot

    def get_recent(self, limit: int = 5000) -> List[PortfolioSnapshot]:
        """Get most recent snapshots in ascending time order."""
        rows = (
            self.db.query(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.timestamp.desc())
            .limit(limit)
            .all()
        )
        rows.reverse()
        return rows

    def get_latest(self) -> Optional[PortfolioSnapshot]:
        """Get latest snapshot row."""
        return (
            self.db.query(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.timestamp.desc())
            .first()
        )
