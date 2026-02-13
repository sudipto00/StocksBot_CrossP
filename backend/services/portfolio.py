"""
Portfolio Service.
Manages portfolio state, positions, and P&L tracking.
Now integrated with database storage layer.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session

from storage.service import StorageService
from storage.models import Position
from services.broker import BrokerInterface


class PortfolioService:
    """
    Portfolio management service.
    
    Responsible for:
    - Tracking current positions (now database-backed)
    - Calculating P&L (realized and unrealized)
    - Portfolio value calculations
    - Position history
    - Performance analytics
    
    """
    
    def __init__(
        self,
        db: Optional[Session] = None,
        storage: Optional[StorageService] = None,
        broker: Optional[BrokerInterface] = None,
    ):
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
        self.broker = broker
        
        # Fallback cash tracking when broker snapshot is unavailable.
        self.cash_balance: float = 100000.0  # Starting cash
        self.total_deposits: float = 100000.0
        
    def get_positions(self) -> List[Dict[str, Any]]:
        """
        Get current positions.
        
        Returns:
            List of position dictionaries
            
        """
        if self.storage:
            positions = self.storage.get_open_positions()
            return [self._position_to_dict(p) for p in positions]
        else:
            # Fallback to in-memory
            return [self._enrich_position(dict(row)) for row in self._in_memory_positions.values()]
    
    def _position_to_dict(self, position: Position) -> Dict[str, Any]:
        """Convert Position model to dictionary."""
        base = {
            "symbol": position.symbol,
            "side": position.side.value,
            "quantity": position.quantity,
            "avg_entry_price": position.avg_entry_price,
            "cost_basis": position.cost_basis,
            "realized_pnl": position.realized_pnl,
        }
        return self._enrich_position(base)
    
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
            raw = self._in_memory_positions.get(symbol)
            if not raw:
                return None
            return self._enrich_position(dict(raw))
    
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
            
        """
        broker_account = self._get_broker_account_info()
        broker_equity = self._safe_float(broker_account.get("equity", broker_account.get("portfolio_value", 0.0)), 0.0)
        if broker_equity > 0:
            return broker_equity

        positions = self.get_positions()
        positions_value = sum(
            pos["quantity"] * self._resolve_price(pos["symbol"], current_prices.get(pos["symbol"]))
            for pos in positions
        )
        cash_balance = self._resolve_cash_balance(default=self.cash_balance)
        return cash_balance + positions_value
    
    def calculate_unrealized_pnl(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate total unrealized P&L.
        
        Args:
            current_prices: Dict of symbol -> current price
            
        Returns:
            Total unrealized P&L
            
        """
        broker_positions = self._get_broker_positions()
        if broker_positions:
            total = 0.0
            for row in broker_positions:
                total += self._safe_float(row.get("unrealized_pnl", 0.0), 0.0)
            return total

        total_pnl = 0.0
        for pos in self.get_positions():
            current_price = self._resolve_price(pos["symbol"], current_prices.get(pos["symbol"]))
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
            
        """
        total_value = self.calculate_portfolio_value(current_prices)
        unrealized_pnl = self.calculate_unrealized_pnl(current_prices)
        cash_balance = self._resolve_cash_balance(default=self.cash_balance)
        total_return = total_value - self.total_deposits
        total_return_pct = (total_return / self.total_deposits * 100) if self.total_deposits > 0 else 0.0
        
        return {
            "total_value": total_value,
            "cash_balance": cash_balance,
            "positions_value": total_value - cash_balance,
            "unrealized_pnl": unrealized_pnl,
            "total_deposits": self.total_deposits,
            "total_return": total_return,
            "total_return_percent": total_return_pct,
        }

    def _enrich_position(self, position: Dict[str, Any]) -> Dict[str, Any]:
        """Attach live-ish valuation fields expected by dashboard consumers."""
        symbol = str(position.get("symbol", "")).upper()
        quantity = self._safe_float(position.get("quantity", 0.0), 0.0)
        avg_entry_price = self._safe_float(position.get("avg_entry_price", 0.0), 0.0)
        price_hint = self._safe_float(position.get("current_price", position.get("price", 0.0)), 0.0)
        current_price = self._resolve_price(symbol, price_hint if price_hint > 0 else None)
        if current_price <= 0:
            current_price = avg_entry_price
        cost_basis = self._safe_float(position.get("cost_basis", quantity * avg_entry_price), quantity * avg_entry_price)
        market_value = quantity * current_price
        unrealized_pnl = market_value - cost_basis
        unrealized_pnl_percent = (unrealized_pnl / cost_basis * 100.0) if cost_basis > 0 else 0.0
        position["current_price"] = current_price
        position["market_value"] = market_value
        position["unrealized_pnl"] = unrealized_pnl
        position["unrealized_pnl_percent"] = unrealized_pnl_percent
        return position

    def _resolve_price(self, symbol: str, fallback_price: Optional[float]) -> float:
        """Resolve price from broker market data, then fallback."""
        if self.broker and self.broker.is_connected():
            try:
                market_data = self.broker.get_market_data(symbol)
                live_price = self._safe_float(market_data.get("price", 0.0), 0.0)
                if live_price > 0:
                    return live_price
            except (RuntimeError, ValueError, TypeError, KeyError):
                pass
        return self._safe_float(fallback_price, 0.0)

    def _resolve_cash_balance(self, default: float) -> float:
        """Resolve cash from broker account info when available."""
        account = self._get_broker_account_info()
        cash = self._safe_float(account.get("cash", default), default)
        return cash

    def _get_broker_positions(self) -> List[Dict[str, Any]]:
        if not self.broker or not self.broker.is_connected():
            return []
        try:
            rows = self.broker.get_positions()
            return rows if isinstance(rows, list) else []
        except (RuntimeError, ValueError, TypeError):
            return []

    def _get_broker_account_info(self) -> Dict[str, Any]:
        if not self.broker or not self.broker.is_connected():
            return {}
        try:
            info = self.broker.get_account_info()
            return info if isinstance(info, dict) else {}
        except (RuntimeError, ValueError, TypeError):
            return {}

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(parsed):
            return default
        return parsed
