"""
Portfolio Service.
Manages portfolio state, positions, and P&L tracking.
Now integrated with database storage layer.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from sqlalchemy.orm import Session

from storage.service import StorageService
from storage.models import Position


class PortfolioService:
    """
    Portfolio management service.
    
    Responsible for:
    - Tracking current positions (now database-backed)
    - Calculating P&L (realized and unrealized)
    - Portfolio value calculations
    - Position history
    - Performance analytics
    
    TODO: Integrate with broker API for real positions
    TODO: Add real-time market data for valuations
    """
    
    def __init__(self, db: Optional[Session] = None, storage: Optional[StorageService] = None):
        """
        Initialize portfolio service.
        
        Args:
            db: Database session (if storage not provided)
            storage: StorageService instance (preferred)
        """
        if storage:
            self.storage = storage
        elif db:
            self.storage = StorageService(db)
        else:
            # Fallback to in-memory mode for backward compatibility
            self.storage = None
            self._in_memory_positions: Dict[str, Dict[str, Any]] = {}
        
        # Cash balance tracking (TODO: Move to database)
        self.cash_balance: float = 100000.0  # Starting cash
        self.total_deposits: float = 100000.0
        
    def get_positions(self) -> List[Dict[str, Any]]:
        """
        Get current positions.
        
        Returns:
            List of position dictionaries
            
        TODO: Fetch from broker API
        TODO: Calculate current market values
        TODO: Include unrealized P&L
        """
        if self.storage:
            positions = self.storage.get_open_positions()
            return [self._position_to_dict(p) for p in positions]
        else:
            # Fallback to in-memory
            return list(self._in_memory_positions.values())
    
    def _position_to_dict(self, position: Position) -> Dict[str, Any]:
        """Convert Position model to dictionary."""
        return {
            "symbol": position.symbol,
            "side": position.side.value,
            "quantity": position.quantity,
            "avg_entry_price": position.avg_entry_price,
            "cost_basis": position.cost_basis,
            "realized_pnl": position.realized_pnl,
        }
    
    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific position.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Position dict or None
        """
        if self.storage:
            position = self.storage.get_position_by_symbol(symbol)
            return self._position_to_dict(position) if position else None
        else:
            return self._in_memory_positions.get(symbol)
    
    def update_position(
        self,
        symbol: str,
        quantity: float,
        price: float,
        side: str = "long",
    ) -> Dict[str, Any]:
        """
        Update a position (add or reduce).
        
        Args:
            symbol: Stock symbol
            quantity: Quantity change (positive for buy, negative for sell)
            price: Transaction price
            side: Position side (long/short)
            
        Returns:
            Updated position
            
        TODO: Calculate realized P&L on closes
        TODO: Update cash balance
        """
        if self.storage:
            # Database-backed implementation
            position = self.storage.get_position_by_symbol(symbol)
            
            if position is None:
                # Create new position
                position = self.storage.create_position(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    avg_entry_price=price
                )
            else:
                # Update existing position
                position = self.storage.update_position_quantity(
                    position, quantity, price
                )
            
            return self._position_to_dict(position) if position.is_open else {}
        else:
            # Fallback to in-memory implementation
            if symbol not in self._in_memory_positions:
                # New position
                self._in_memory_positions[symbol] = {
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "avg_entry_price": price,
                    "cost_basis": quantity * price,
                    "realized_pnl": 0.0,
                }
            else:
                # Update existing position
                pos = self._in_memory_positions[symbol]
                new_quantity = pos["quantity"] + quantity
                
                if new_quantity == 0:
                    # Position closed
                    del self._in_memory_positions[symbol]
                    return {}
                else:
                    # Position increased or decreased
                    pos["quantity"] = new_quantity
                    pos["cost_basis"] = new_quantity * pos["avg_entry_price"]
            
            return self._in_memory_positions.get(symbol, {})
    
    def calculate_portfolio_value(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate total portfolio value.
        
        Args:
            current_prices: Dict of symbol -> current price
            
        Returns:
            Total portfolio value
            
        TODO: Use real-time market data
        TODO: Include options and other asset types
        """
        positions = self.get_positions()
        positions_value = sum(
            pos["quantity"] * current_prices.get(pos["symbol"], pos["avg_entry_price"])
            for pos in positions
        )
        return self.cash_balance + positions_value
    
    def calculate_unrealized_pnl(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate total unrealized P&L.
        
        Args:
            current_prices: Dict of symbol -> current price
            
        Returns:
            Total unrealized P&L
            
        TODO: Use real-time market data
        """
        total_pnl = 0.0
        for pos in self.get_positions():
            current_price = current_prices.get(pos["symbol"], pos["avg_entry_price"])
            market_value = pos["quantity"] * current_price
            unrealized_pnl = market_value - pos["cost_basis"]
            total_pnl += unrealized_pnl
        return total_pnl
    
    def get_portfolio_summary(self, current_prices: Dict[str, float]) -> Dict[str, Any]:
        """
        Get portfolio summary.
        
        Args:
            current_prices: Dict of symbol -> current price
            
        Returns:
            Portfolio summary dict
            
        TODO: Add more metrics
        """
        total_value = self.calculate_portfolio_value(current_prices)
        unrealized_pnl = self.calculate_unrealized_pnl(current_prices)
        total_return = total_value - self.total_deposits
        total_return_pct = (total_return / self.total_deposits * 100) if self.total_deposits > 0 else 0.0
        
        return {
            "total_value": total_value,
            "cash_balance": self.cash_balance,
            "positions_value": total_value - self.cash_balance,
            "unrealized_pnl": unrealized_pnl,
            "total_deposits": self.total_deposits,
            "total_return": total_return,
            "total_return_percent": total_return_pct,
        }
