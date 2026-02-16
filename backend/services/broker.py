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
import math


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

    def is_symbol_fractionable(self, symbol: str) -> bool:
        """
        Optional: whether symbol supports fractional-share market orders.
        Default True for brokers that do not expose asset metadata.
        """
        return True

    def get_symbol_capabilities(self, symbol: str) -> Dict[str, bool]:
        """
        Optional: fetch execution capabilities for a symbol.
        """
        return {
            "tradable": bool(self.is_symbol_tradable(symbol)),
            "fractionable": bool(self.is_symbol_fractionable(symbol)),
        }

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
        self._market_data_cache: Dict[str, Dict[str, Any]] = {}
    
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
        """
        positions_value = 0.0
        for symbol, position in self.positions.items():
            market_data = self.get_market_data(symbol)
            current_price = float(market_data.get("price", position.get("current_price", position.get("avg_entry_price", 0.0))))
            quantity = float(position.get("quantity", 0.0))
            avg_entry_price = float(position.get("avg_entry_price", 0.0))
            market_value = quantity * current_price
            cost_basis = quantity * avg_entry_price
            unrealized_pnl = market_value - cost_basis
            position.update({
                "current_price": current_price,
                "market_value": market_value,
                "cost_basis": cost_basis,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_percent": (unrealized_pnl / cost_basis * 100.0) if cost_basis > 0 else 0.0,
            })
            positions_value += market_value

        return {
            "cash": self.balance,
            "equity": self.balance + positions_value,
            "buying_power": max(0.0, self.balance),
        }
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """Get paper positions."""
        # Keep positions marked-to-market for consumers.
        _ = self.get_account_info()
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
        For limit orders, create pending order and fill later when simulated
        market price satisfies the limit criteria.
        """
        self.order_counter += 1
        order_id = f"paper-{self.order_counter}"
        symbol = symbol.upper()
        
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
            self._apply_fill_to_positions(symbol, side.value, filled_quantity, avg_fill_price, current_price)
        else:
            # Limit orders remain pending until simulated market price reaches
            # the limit condition. A later get_order/get_orders/get_market_data
            # call can trigger the fill.
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
        order = self.orders.get(order_id)
        if not order:
            return {}
        if order.get("status") == OrderStatus.PENDING.value and order.get("type") == OrderType.LIMIT.value:
            _ = self.get_market_data(str(order.get("symbol", "")))
        return order
    
    def get_orders(self, status: Optional[OrderStatus] = None) -> List[Dict[str, Any]]:
        """Get paper orders."""
        # Re-evaluate pending limit orders on each fetch.
        pending_symbols = {
            str(order.get("symbol", "")).upper()
            for order in self.orders.values()
            if order.get("status") == OrderStatus.PENDING.value and order.get("type") == OrderType.LIMIT.value
        }
        for symbol in pending_symbols:
            _ = self.get_market_data(symbol)

        if status:
            return [o for o in self.orders.values() if o["status"] == status.value]
        return list(self.orders.values())
    
    def get_market_data(self, symbol: str) -> Dict[str, Any]:
        """
        Get simulated market data.
        """
        symbol = symbol.upper()
        price = self._simulated_price(symbol)
        spread = max(0.01, round(price * 0.0005, 2))
        bid = round(max(0.01, price - spread), 2)
        ask = round(price + spread, 2)
        volume = self._simulated_volume(symbol)

        # Evaluate pending limit orders for this symbol whenever we fetch data.
        self._simulate_limit_fills_for_symbol(symbol, price)

        if symbol in self.positions:
            self._mark_position_to_market(symbol, price)

        return {
            "symbol": symbol,
            "price": price,
            "bid": bid,
            "ask": ask,
            "volume": volume,
            "timestamp": datetime.now().isoformat(),
        }

    def _simulated_price(self, symbol: str) -> float:
        """Generate stable but non-flat simulated prices per symbol."""
        now = datetime.now()
        bucket = int(now.timestamp() // 30)
        static_prices = {
            # Keep AAPL stable at 100 for backward-compatible tests.
            "AAPL": 100.0,
            "MSFT": 300.0,
        }
        if symbol in static_prices:
            return static_prices[symbol]

        state = self._market_data_cache.get(symbol)
        if state is None:
            base = self._baseline_price(symbol)
            state = {"base": base}
            self._market_data_cache[symbol] = state
        base = float(state.get("base", 100.0))
        drift_seed = (sum(ord(ch) for ch in symbol) + bucket) % 17 - 8
        drift_pct = drift_seed / 1000.0  # +/-0.8%
        price = max(1.0, round(base * (1.0 + drift_pct), 2))
        return price

    @staticmethod
    def _baseline_price(symbol: str) -> float:
        """Deterministic baseline from ticker string."""
        seed = sum((idx + 1) * ord(ch) for idx, ch in enumerate(symbol))
        # 25..425 baseline.
        return float((seed % 400) + 25)

    @staticmethod
    def _simulated_volume(symbol: str) -> int:
        base = 200_000 + (sum(ord(ch) for ch in symbol) % 2_500_000)
        return int(base)

    def _simulate_limit_fills_for_symbol(self, symbol: str, current_price: float) -> None:
        """Fill pending limit orders when simulated price reaches limit."""
        for order in self.orders.values():
            if order.get("symbol") != symbol:
                continue
            if order.get("status") != OrderStatus.PENDING.value:
                continue
            if order.get("type") != OrderType.LIMIT.value:
                continue
            limit_price = float(order.get("price") or 0.0)
            if limit_price <= 0:
                continue
            side = str(order.get("side"))
            quantity = float(order.get("quantity") or 0.0)
            if quantity <= 0:
                continue

            should_fill = False
            fill_price = current_price
            if side == OrderSide.BUY.value and current_price <= limit_price:
                should_fill = True
                fill_price = min(limit_price, current_price)
            elif side == OrderSide.SELL.value and current_price >= limit_price:
                should_fill = True
                fill_price = max(limit_price, current_price)

            if not should_fill:
                continue

            order["status"] = OrderStatus.FILLED.value
            order["filled_quantity"] = quantity
            order["avg_fill_price"] = fill_price
            order["filled_at"] = datetime.now().isoformat()
            if side == OrderSide.BUY.value:
                self.balance -= quantity * fill_price
            else:
                self.balance += quantity * fill_price
            self._apply_fill_to_positions(symbol, side, quantity, fill_price, current_price)

    def _apply_fill_to_positions(
        self,
        symbol: str,
        side: str,
        quantity: float,
        fill_price: float,
        current_price: float,
    ) -> None:
        """Update in-memory positions after a simulated fill."""
        existing = self.positions.get(symbol)
        existing_qty = float(existing.get("quantity", 0.0)) if existing else 0.0
        existing_avg = float(existing.get("avg_entry_price", fill_price)) if existing else fill_price

        if side == OrderSide.BUY.value:
            new_qty = existing_qty + quantity
            new_avg = (
                ((existing_qty * existing_avg) + (quantity * fill_price)) / new_qty
                if new_qty > 0
                else fill_price
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
            new_qty = max(0.0, existing_qty - quantity)
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

    def _mark_position_to_market(self, symbol: str, current_price: float) -> None:
        """Refresh derived valuation fields for an existing position."""
        position = self.positions.get(symbol)
        if not position:
            return
        quantity = float(position.get("quantity", 0.0))
        avg_entry_price = float(position.get("avg_entry_price", 0.0))
        market_value = quantity * current_price
        cost_basis = quantity * avg_entry_price
        unrealized_pnl = market_value - cost_basis
        position.update({
            "current_price": current_price,
            "market_value": market_value,
            "cost_basis": cost_basis,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_percent": ((current_price - avg_entry_price) / avg_entry_price * 100.0) if avg_entry_price > 0 else 0.0,
        })
