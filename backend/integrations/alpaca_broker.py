"""
Alpaca Broker Integration.

Implements the BrokerInterface for Alpaca Markets API.
Supports both paper trading and live trading via API credentials.

TODO: Full trading logic implementation
- Real order execution and tracking
- Advanced order types (stop-loss, take-profit, etc.)
- Position management and reconciliation
- Historical data fetching
- Streaming market data
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import (
    OrderSide as AlpacaOrderSide,
    TimeInForce,
    OrderStatus as AlpacaOrderStatus,
)
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from services.broker import BrokerInterface, OrderSide, OrderType, OrderStatus

logger = logging.getLogger(__name__)


class AlpacaBroker(BrokerInterface):
    """
    Alpaca broker implementation.
    
    Supports both paper trading and live trading through Alpaca Markets API.
    
    Configuration:
        - api_key: Alpaca API key
        - secret_key: Alpaca secret key  
        - paper: Whether to use paper trading (default: True)
    """
    
    def __init__(self,
        api_key: str,
        secret_key: str,
        paper: bool = True
    ):  
        """
        Initialize Alpaca broker.
        
        Args:
            api_key: Alpaca API key
            secret_key: Alpaca secret key
            paper: Use paper trading endpoint (default: True)
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.paper = paper
        self._connected = False
        self._trading_client: Optional[TradingClient] = None
        self._data_client: Optional[StockHistoricalDataClient] = None
    
    def connect(self) -> bool:
        """
        Connect to Alpaca API.
        
        Returns:
            True if connected successfully
        """
        try:
            # Initialize trading client
            self._trading_client = TradingClient(
                api_key=self.api_key,
                secret_key=self.secret_key,
                paper=self.paper
            )
            
            # Initialize data client (no paper/live distinction)
            self._data_client = StockHistoricalDataClient(
                api_key=self.api_key,
                secret_key=self.secret_key
            )
            
            # Test connection by fetching account
            account = self._trading_client.get_account()
            logger.info(f"Connected to Alpaca ({'paper' if self.paper else 'live'})")
            logger.info(f"Account status: {account.status}")
            
            self._connected = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Alpaca: {e}")
            self._connected = False
            return False
    
    def disconnect(self) -> bool:
        """
        Disconnect from Alpaca API.
        
        Returns:
            True if disconnected successfully
        """
        self._connected = False
        self._trading_client = None
        self._data_client = None
        logger.info("Disconnected from Alpaca")
        return True
    
    def is_connected(self) -> bool:
        """
        Check if connected to Alpaca.
        
        Returns:
            True if connected
        """
        return self._connected and self._trading_client is not None
    
    def get_account_info(self) -> Dict[str, Any]:
        """
        Get Alpaca account information.
        
        Returns:
            Account info dict with balance, buying power, etc.
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to Alpaca")
        
        account = self._trading_client.get_account()
        
        return {
            "account_number": account.account_number,
            "status": account.status,
            "currency": account.currency,
            "cash": float(account.cash),
            "portfolio_value": float(account.portfolio_value),
            "equity": float(account.equity),
            "buying_power": float(account.buying_power),
            "pattern_day_trader": account.pattern_day_trader,
            "trading_blocked": account.trading_blocked,
            "transfers_blocked": account.transfers_blocked,
            "account_blocked": account.account_blocked,
        }
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """
        Get current positions from Alpaca.
        
        Returns:
            List of position dicts
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to Alpaca")
        
        positions = self._trading_client.get_all_positions()
        
        result = []
        for pos in positions:
            result.append({
                "symbol": pos.symbol,
                "quantity": float(pos.qty),
                "side": "long" if float(pos.qty) > 0 else "short",
                "avg_entry_price": float(pos.avg_entry_price),
                "current_price": float(pos.current_price),
                "market_value": float(pos.market_value),
                "cost_basis": float(pos.cost_basis),
                "unrealized_pnl": float(pos.unrealized_pl),
                "unrealized_pnl_percent": float(pos.unrealized.plpc) * 100,
            })
        
        return result
    
    def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Submit an order to Alpaca.
        
        TODO: Add support for all order types (stop, stop_limit)
        TODO: Add order validation and risk checks
        TODO: Add support for fractional shares
        TODO: Add support for extended hours trading
        
        Args:
            symbol: Stock symbol
            side: Buy or sell
            order_type: Market, limit, etc.
            quantity: Number of shares
            price: Limit price (for limit orders)
            
        Returns:
            Order confirmation dict
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to Alpaca")
        
        # Map our OrderSide to Alpaca's OrderSide
        alpaca_side = AlpacaOrderSide.BUY if side == OrderSide.BUY else AlpacaOrderSide.SELL
        
        # Submit order based on type
        if order_type == OrderType.MARKET:
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=quantity,
                side=alpaca_side,
                time_in_force=TimeInForce.DAY
            )
            order = self._trading_client.submit_order(order_data)
        
        elif order_type == OrderType.LIMIT:
            if price is None:
                raise ValueError("Price required for limit orders")
            
            order_data = LimitOrderRequest(
                symbol=symbol,
                qty=quantity,
                side=alpaca_side,
                time_in_force=TimeInForce.DAY,
                limit_price=price
            )
            order = self._trading_client.submit_order(order_data)
        
        else:
            # TODO: Implement stop and stop_limit orders
            raise NotImplementedError(f"Order type {order_type} not yet implemented")
        
        return self._map_alpaca_order(order)
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: Alpaca order ID to cancel
            
        Returns:
            True if cancelled successfully
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to Alpaca")
        
        try:
            self._trading_client.cancel_order_by_id(order_id)
            logger.info(f"Cancelled order {order_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
    
    def get_order(self, order_id: str) -> Dict[str, Any]:
        """
        Get order details.
        
        Args:
            order_id: Alpaca order ID
            
        Returns:
            Order details dict
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to Alpaca")
        
        order = self._trading_client.get_order_by_id(order_id)
        return self._map_alpaca_order(order)
    
    def get_orders(self, status: Optional[OrderStatus] = None) -> List[Dict[str, Any]]:
        """
        Get orders.
        
        TODO: Add support for filtering by date range
        TODO: Add support for pagination
        
        Args:
            status: Filter by status (optional)
            
        Returns:
            List of order dicts
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to Alpaca")
        
        # Build request filter
        request = GetOrdersRequest()
        if status:
            # Map our status to Alpaca's status
            alpaca_status = self._map_to_alpaca_status(status)
            if alpaca_status:
                request.status = alpaca_status
        
        orders = self._trading_client.get_orders(filter=request)
        
        return [self._map_alpaca_order(order) for order in orders]
    
    def get_market_data(self, symbol: str) -> Dict[str, Any]:
        """
        Get current market data for a symbol.
        
        TODO: Add support for multiple symbols in one call
        TODO: Add support for bars/candles data
        TODO: Add support for real-time streaming data
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Market data dict (price, volume, etc.)
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to Alpaca")
        
        request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        quotes = self._data_client.get_stock_latest_quote(request)
        
        if symbol not in quotes:
            return {
                "symbol": symbol,
                "price": 0.0,
                "error": "No quote data available"
            }
        
        quote = quotes[symbol]
        
        return {
            "symbol": symbol,
            "ask_price": float(quote.ask_price),
            "bid_price": float(quote.bid_price),
            "ask_size": int(quote.ask_size),
            "bid_size": int(quote.bid_size),
            "timestamp": quote.timestamp.isoformat(),
        }

    def get_historical_bars(
        self,
        symbol: str,
        start: datetime,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
        timeframe: TimeFrame = TimeFrame.Day,
    ) -> List[Dict[str, Any]]:
        """
        Get historical bars for a symbol.

        Args:
            symbol: Stock symbol
            start: Start datetime for bars
            end: Optional end datetime
            limit: Optional number of bars to return
            timeframe: Bar timeframe (default: 1 day)

        Returns:
            List of bars with OHLCV data
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to Alpaca")

        request = StockBarsRequest(
            symbol_or_symbols=[symbol],
            timeframe=timeframe,
            start=start,
            end=end,
            limit=limit,
        )
        bars = self._data_client.get_stock_bars(request)
        bar_data = bars.data if hasattr(bars, "data") else bars
        symbol_bars = bar_data.get(symbol, []) if isinstance(bar_data, dict) else []

        result = []
        for bar in symbol_bars:
            result.append({
                "timestamp": bar.timestamp,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": int(bar.volume),
            })

        return result
    
    def _map_alpaca_order(self, order) -> Dict[str, Any]:
        """
        Map Alpaca order object to our order dict format.
        
        Args:
            order: Alpaca order object
            
        Returns:
            Order dict in our format
            
        Note: Alpaca API sometimes uses 'order_type' and sometimes 'type' 
        depending on the endpoint/version. We check for both.
        """
        # Handle both 'order_type' (newer) and 'type' (older) attributes
        if hasattr(order, 'order_type'):
            order_type_value = order.order_type.value
        else:
            order_type_value = order.type.value
            
        return {
            "id": order.id,
            "client_order_id": order.client_order_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "type": order_type_value,
            "quantity": float(order.qty),
            "filled_quantity": float(order.filled_qty) if order.filled_qty else 0.0,
            "price": float(order.limit_price) if order.limit_price else None,
            "avg_fill_price": float(order.filled_avg_price) if order.filled_avg_price else None,
            "status": self._map_from_alpaca_status(order.status),
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat() if order.updated_at else order.created_at.isoformat(),
        }
    
    def _map_from_alpaca_status(self, alpaca_status: AlpacaOrderStatus) -> str:
        """Map Alpaca order status to our OrderStatus."""
        mapping = {
            AlpacaOrderStatus.NEW: OrderStatus.PENDING.value,
            AlpacaOrderStatus.PENDING_NEW: OrderStatus.PENDING.value,
            AlpacaOrderStatus.ACCEPTED: OrderStatus.SUBMITTED.value,
            AlpacaOrderStatus.PENDING_CANCEL: OrderStatus.SUBMITTED.value,
            AlpacaOrderStatus.PENDING_REPLACE: OrderStatus.SUBMITTED.value,
            AlpacaOrderStatus.PARTIALLY_FILLED: OrderStatus.PARTIALLY_FILLED.value,
            AlpacaOrderStatus.FILLED: OrderStatus.FILLED.value,
            AlpacaOrderStatus.DONE_FOR_DAY: OrderStatus.FILLED.value,
            AlpacaOrderStatus.CANCELED: OrderStatus.CANCELLED.value,
            AlpacaOrderStatus.EXPIRED: OrderStatus.CANCELLED.value,
            AlpacaOrderStatus.REPLACED: OrderStatus.CANCELLED.value,
            AlpacaOrderStatus.REJECTED: OrderStatus.REJECTED.value,
            AlpacaOrderStatus.SUSPENDED: OrderStatus.REJECTED.value,
        }
        return mapping.get(alpaca_status, OrderStatus.PENDING.value)
    
    def _map_to_alpaca_status(self, status: OrderStatus) -> Optional[AlpacaOrderStatus]:
        """Map our OrderStatus to Alpaca's (for filtering)."""
        # This is simplified - Alpaca has more granular statuses
        mapping = {
            OrderStatus.PENDING: AlpacaOrderStatus.NEW,
            OrderStatus.SUBMITTED: AlpacaOrderStatus.ACCEPTED,
            OrderStatus.FILLED: AlpacaOrderStatus.FILLED,
            OrderStatus.PARTIALLY_FILLED: AlpacaOrderStatus.PARTIALLY_FILLED,
            OrderStatus.CANCELLED: AlpacaOrderStatus.CANCELED,
            OrderStatus.REJECTED: AlpacaOrderStatus.REJECTED,
        }
        return mapping.get(status)