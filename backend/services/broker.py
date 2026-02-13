"""
Broker Service Interface.
Abstract interface for broker integrations.

TODO: Implement concrete broker implementations
- Alpaca API integration
- Interactive Brokers integration
- Paper trading broker
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from enum import Enum


class OrderSide(Enum):
    """Order side."""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(Enum):
    """Order status."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class BrokerInterface(ABC):
    """
    Abstract broker interface.
    
    All broker implementations must inherit from this interface.
    This ensures consistent API across different brokers.
    
    TODO: Add more methods as needed
    - Account info
    - Margin requirements
    - Watchlists
    - Historical data
    """
    
    @abstractmethod
    def connect(self) -> bool:
        """
        Connect to broker API.
        
        Returns:
            True if connected successfully
        """
        pass
    
    @abstractmethod
    def disconnect(self) -> bool:
        """
        Disconnect from broker API.
        
        Returns:
            True if disconnected successfully
        """
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """
        Check if connected to broker.
        
        Returns:
            True if connected
        """
        pass
    
    @abstractmethod
    def get_account_info(self) -> Dict[str, Any]:
        """
        Get account information.
        
        Returns:
            Account info dict with balance, buying power, etc.
        """
        pass
    
    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """
        Get current positions from broker.
        
        Returns:
            List of position dicts
        """
        pass
    
    @abstractmethod
    def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Submit an order to the broker.
        
        Args:
            symbol: Stock symbol
            side: Buy or sell
            order_type: Market, limit, etc.
            quantity: Number of shares
            price: Limit price (for limit orders)
            
        Returns:
            Order confirmation dict
        """
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: Order ID to cancel
            
        Returns:
            True if cancelled successfully
        """
        pass
    
    @abstractmethod
    def get_order(self, order_id: str) -> Dict[str, Any]:
        """
        Get order details.
        
        Args:
            order_id: Order ID
            
        Returns:
            Order details dict
        """
        pass
    
    @abstractmethod
    def get_orders(self, status: Optional[OrderStatus] = None) -> List[Dict[str, Any]]:
        """
        Get orders.
        
        Args:
            status: Filter by status (optional)
            
        Returns:
            List of order dicts
        """
        pass
    
    @abstractmethod
    def get_market_data(self, symbol: str) -> Dict[str, Any]:
        """
        Get current market data for a symbol.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Market data dict (price, volume, etc.)
        """
        pass

    def start_trade_update_stream(self, on_update: Callable[[Dict[str, Any]], None]) -> bool:
        """
        Optional: start broker trade-update websocket stream.
        Default implementation returns False for brokers that do not support streaming.
        """
        return False

    def stop_trade_update_stream(self) -> bool:
        """
        Optional: stop broker trade-update websocket stream.
        Default implementation returns False for brokers that do not support streaming.
        """
        return False

    def is_market_open(self) -> bool:
        """
        Optional: whether regular market session is open.
        Default True for non-market-aware brokers.
        """
        return True

    def is_symbol_tradable(self, symbol: str) -> bool:
        """
        Optional: whether symbol is tradable.
        Default True for non-market-aware brokers.
        """
        return True

    def get_next_market_open(self) -> Optional[datetime]:
        """
        Optional: next regular market open time.
        Default None for brokers that do not expose market clock metadata.
        """
        return None


class PaperBroker(BrokerInterface):
    """
    Paper trading broker implementation.
    Simulates trading without real money.
    
    TODO: Implement full paper trading logic
    - Simulate order fills
    - Track paper positions
    - Simulate market data
    """
    
    def __init__(self, starting_balance: float = 100000.0):
        """
        Initialize paper broker.
        
        Args:
            starting_balance: Starting cash balance
        """
        self.connected = False
        self.balance = starting_balance
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.order_counter = 0
    
    def connect(self) -> bool:
        """Connect to paper broker (always succeeds)."""
        self.connected = True
        return True
    
    def disconnect(self) -> bool:
        """Disconnect from paper broker."""
        self.connected = False
        return True
    
    def is_connected(self) -> bool:
        """Check if connected."""
        return self.connected
    
    def get_account_info(self) -> Dict[str, Any]:
        """
        Get paper account info.
        
        TODO: Calculate buying power and equity
        """
        positions_value = sum(float(position.get("market_value", 0.0)) for position in self.positions.values())
        return {
            "cash": self.balance,
            "equity": self.balance + positions_value,
            "buying_power": self.balance,
        }
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """Get paper positions."""
        return list(self.positions.values())
    
    def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Submit a paper order.
        
        For market orders, immediately fill at the current simulated price.
        For limit orders, create pending order (fill simulation not yet implemented).
        """
        self.order_counter += 1
        order_id = f"paper-{self.order_counter}"
        
        # Get current market price
        market_data = self.get_market_data(symbol)
        current_price = market_data["price"]
        
        # Determine if order should be filled immediately
        if order_type == OrderType.MARKET:
            # Market orders fill immediately at current price
            status = OrderStatus.FILLED.value
            filled_quantity = quantity
            avg_fill_price = current_price
            
            # Update balance for buy orders
            if side == OrderSide.BUY:
                cost = filled_quantity * avg_fill_price
                self.balance -= cost
            else:  # SELL
                proceeds = filled_quantity * avg_fill_price
                self.balance += proceeds

            # Update paper positions so dashboard/holdings reflect actual state.
            existing = self.positions.get(symbol)
            existing_qty = float(existing.get("quantity", 0.0)) if existing else 0.0
            existing_avg = float(existing.get("avg_entry_price", avg_fill_price)) if existing else avg_fill_price
            if side == OrderSide.BUY:
                new_qty = existing_qty + filled_quantity
                new_avg = (
                    ((existing_qty * existing_avg) + (filled_quantity * avg_fill_price)) / new_qty
                    if new_qty > 0
                    else avg_fill_price
                )
                self.positions[symbol] = {
                    "symbol": symbol,
                    "quantity": new_qty,
                    "side": "long",
                    "avg_entry_price": new_avg,
                    "current_price": current_price,
                    "market_value": new_qty * current_price,
                    "cost_basis": new_qty * new_avg,
                    "unrealized_pnl": (new_qty * current_price) - (new_qty * new_avg),
                    "unrealized_pnl_percent": ((current_price - new_avg) / new_avg * 100.0) if new_avg > 0 else 0.0,
                }
            else:
                new_qty = max(0.0, existing_qty - filled_quantity)
                if new_qty <= 0:
                    self.positions.pop(symbol, None)
                else:
                    self.positions[symbol] = {
                        "symbol": symbol,
                        "quantity": new_qty,
                        "side": "long",
                        "avg_entry_price": existing_avg,
                        "current_price": current_price,
                        "market_value": new_qty * current_price,
                        "cost_basis": new_qty * existing_avg,
                        "unrealized_pnl": (new_qty * current_price) - (new_qty * existing_avg),
                        "unrealized_pnl_percent": ((current_price - existing_avg) / existing_avg * 100.0) if existing_avg > 0 else 0.0,
                    }
        else:
            # Limit orders stay pending (TODO: implement fill simulation)
            status = OrderStatus.PENDING.value
            filled_quantity = 0.0
            avg_fill_price = None
        
        order = {
            "id": order_id,
            "symbol": symbol,
            "side": side.value,
            "type": order_type.value,
            "quantity": quantity,
            "price": price,
            "status": status,
            "filled_quantity": filled_quantity,
            "avg_fill_price": avg_fill_price,
            "created_at": datetime.now().isoformat(),
        }
        
        self.orders[order_id] = order
        return order
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a paper order."""
        if order_id in self.orders:
            self.orders[order_id]["status"] = OrderStatus.CANCELLED.value
            return True
        return False
    
    def get_order(self, order_id: str) -> Dict[str, Any]:
        """Get paper order details."""
        return self.orders.get(order_id, {})
    
    def get_orders(self, status: Optional[OrderStatus] = None) -> List[Dict[str, Any]]:
        """Get paper orders."""
        if status:
            return [o for o in self.orders.values() if o["status"] == status.value]
        return list(self.orders.values())
    
    def get_market_data(self, symbol: str) -> Dict[str, Any]:
        """
        Get simulated market data.
        
        TODO: Integrate with real market data provider
        """
        return {
            "symbol": symbol,
            "price": 100.0,  # Placeholder
            "volume": 1000000,
            "timestamp": datetime.now().isoformat(),
        }
