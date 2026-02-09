"""
Storage service - High-level interface for storage operations.
Provides business logic on top of repositories.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session

from storage.repositories import (
    PositionRepository, OrderRepository, TradeRepository,
    StrategyRepository, ConfigRepository
)
from storage.models import (
    Position, Order, Trade, Strategy, Config,
    PositionSideEnum, OrderSideEnum, OrderTypeEnum, OrderStatusEnum, TradeTypeEnum
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
            # Calculate realized P&L
            if position.side == PositionSideEnum.LONG:
                realized_pnl = quantity_delta * (price - position.avg_entry_price)
            else:  # SHORT
                realized_pnl = quantity_delta * (position.avg_entry_price - price)
            
            return self.positions.close_position(position, realized_pnl)
        else:
            # Update position
            if abs(new_quantity) > abs(position.quantity):
                # Adding to position - recalculate average entry
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
            type=TradeTypeEnum.OPEN,  # Default to OPEN, can be refined
            quantity=quantity,
            price=price,
            commission=commission,
            fees=fees
        )
    
    def get_recent_trades(self, limit: int = 100) -> List[Trade]:
        """Get recent trades."""
        return self.trades.get_recent(limit)
    
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
