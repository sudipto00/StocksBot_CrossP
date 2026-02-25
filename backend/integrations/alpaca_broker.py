"""
Alpaca Broker Integration.

Implements the BrokerInterface for Alpaca Markets API.
Supports both paper trading and live trading via API credentials.
"""

from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta, timezone
import logging
import threading

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    StopOrderRequest,
    StopLimitOrderRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import (
    OrderSide as AlpacaOrderSide,
    OrderType as AlpacaOrderType,
    TimeInForce,
    OrderStatus as AlpacaOrderStatus,
    QueryOrderStatus,
)
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.common.exceptions import APIError

from services.broker import BrokerInterface, OrderSide, OrderType, OrderStatus

logger = logging.getLogger(__name__)

_KNOWN_ETF_SYMBOLS = {
    "SPY", "QQQ", "IWM", "VTI", "VOO", "IVV", "DIA", "AGG", "TLT", "XLF",
    "XLK", "XLE", "XLI", "XLV", "XLP", "XLY", "XLC", "XLB", "XLU", "XLRE",
    "VEA", "VWO", "EEM", "BND", "LQD", "HYG", "IYR", "VNQ", "SCHD", "VIG",
    "RSP", "MTUM", "QUAL", "USMV", "GDX", "SLV", "GLD", "SMH", "SOXX", "ARKK",
    "SCHA", "SCHB", "SCHF", "VT", "ACWI", "BIL", "SGOV", "MUB", "EMB", "PFF",
    "GBTC", "ETHE", "BITO", "BIZD", "GLL", "VTWO",
}
_ETF_HINT_TERMS = (
    " etf", "fund", "trust", "index", "ishares", "vanguard", "spdr",
    "invesco", "proshares", "direxion", "wisdomtree", "schwab", "global x",
    "first trust", "vaneck", "graniteshares", "exchange traded", "select sector",
)
_STOCK_HINT_TERMS = (
    " inc.", " inc ", " corp.", " corp ", " co.", " co ", " ltd.", " ltd ",
    " plc ", " s.a.", " n.v.", " ag ", " se ", " technologies ",
    " pharmaceuticals ", " holdings inc", " group inc",
)


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
        self._trade_stream = None
        self._trade_stream_thread: Optional[threading.Thread] = None
        self._trade_stream_running = False
        self._trade_update_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self._market_data_stream = None
        self._market_data_stream_thread: Optional[threading.Thread] = None
        self._market_data_stream_running = False
        self._market_data_update_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self._market_data_stream_symbols: List[str] = []
        self._live_quote_cache: Dict[str, Dict[str, Any]] = {}
        self._live_quote_cache_lock = threading.Lock()
        self._asset_capabilities_cache: Dict[str, Dict[str, Any]] = {}
        self._asset_capabilities_ttl = timedelta(minutes=15)
        self._last_connect_error: Optional[str] = None
    
    def connect(self) -> bool:
        """
        Connect to Alpaca API.
        
        Returns:
            True if connected successfully
        """
        try:
            self._last_connect_error = None
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
            self._last_connect_error = str(e)
            self._connected = False
            return False
    
    def disconnect(self) -> bool:
        """
        Disconnect from Alpaca API.
        
        Returns:
            True if disconnected successfully
        """
        self.stop_trade_update_stream()
        self.stop_market_data_stream()
        self._connected = False
        self._trading_client = None
        self._data_client = None
        self._asset_capabilities_cache = {}
        with self._live_quote_cache_lock:
            self._live_quote_cache.clear()
        logger.info("Disconnected from Alpaca")
        return True
    
    def is_connected(self) -> bool:
        """
        Check if connected to Alpaca.
        
        Returns:
            True if connected
        """
        return self._connected and self._trading_client is not None

    def get_last_connection_error(self) -> Optional[str]:
        """Return the most recent Alpaca connection error if one occurred."""
        return self._last_connect_error
    
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

    def is_market_open(self) -> bool:
        """Return Alpaca clock market-open state when available."""
        if not self.is_connected():
            return False
        try:
            clock = self._trading_client.get_clock()
            return bool(getattr(clock, "is_open", False))
        except (RuntimeError, APIError, OSError):
            return False

    def is_symbol_tradable(self, symbol: str) -> bool:
        """Return whether Alpaca marks the asset as tradable."""
        return bool(self.get_symbol_capabilities(symbol).get("tradable", False))

    def is_symbol_fractionable(self, symbol: str) -> bool:
        """Return whether Alpaca marks the asset as fractionable."""
        return bool(self.get_symbol_capabilities(symbol).get("fractionable", False))

    def get_symbol_capabilities(self, symbol: str) -> Dict[str, bool]:
        """Fetch tradable/fractionable metadata from Alpaca asset details."""
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return {"tradable": False, "fractionable": False}
        if not self.is_connected():
            return {"tradable": False, "fractionable": False}
        raw = self._get_asset_capabilities(normalized)
        return {
            "tradable": bool(raw.get("tradable", False)),
            "fractionable": bool(raw.get("fractionable", False)),
        }

    def _get_asset_capabilities(self, symbol: str) -> Dict[str, Any]:
        now = datetime.utcnow()
        cached = self._asset_capabilities_cache.get(symbol)
        if cached:
            expires_at = cached.get("expires_at")
            if isinstance(expires_at, datetime) and expires_at > now:
                return dict(cached.get("data", {}))
        try:
            asset = self._trading_client.get_asset(symbol)
            payload = {
                "tradable": bool(getattr(asset, "tradable", False)),
                "fractionable": bool(getattr(asset, "fractionable", False)),
                "shortable": bool(getattr(asset, "shortable", False)),
                "easy_to_borrow": bool(getattr(asset, "easy_to_borrow", False)),
                "marginable": bool(getattr(asset, "marginable", False)),
                "asset_class": str(getattr(asset, "asset_class", getattr(asset, "class", "")) or ""),
                "name": str(getattr(asset, "name", "") or ""),
            }
        except (RuntimeError, APIError, OSError):
            payload = {
                "tradable": False,
                "fractionable": False,
                "shortable": False,
                "easy_to_borrow": False,
                "marginable": False,
                "asset_class": "",
                "name": "",
            }
        self._asset_capabilities_cache[symbol] = {
            "data": payload,
            "expires_at": now + self._asset_capabilities_ttl,
        }
        return dict(payload)

    def _is_probable_etf_asset(self, symbol: str, name: str) -> bool:
        """Fallback ETF classifier when Alpaca asset_class is generic."""
        normalized_symbol = str(symbol or "").strip().upper()
        if normalized_symbol in _KNOWN_ETF_SYMBOLS:
            return True
        text = f" {normalized_symbol} {str(name or '')} ".lower()
        if any(term in text for term in _STOCK_HINT_TERMS):
            return False
        return any(term in text for term in _ETF_HINT_TERMS)

    def _resolve_asset_type(self, symbol: str, asset_meta: Dict[str, Any]) -> str:
        """
        Resolve stock/ETF type from Alpaca asset metadata.
        - Primary: explicit asset_class signals.
        - Fallback: known ETF set + name/symbol heuristic.
        """
        asset_class = str(asset_meta.get("asset_class", "")).strip().lower().replace("-", "_")
        is_etf_by_asset_class = ("etf" in asset_class) or ("fund" in asset_class)
        is_explicit_stock_by_asset_class = (
            ("stock" in asset_class or "common_stock" in asset_class)
            and not is_etf_by_asset_class
        )
        if is_etf_by_asset_class:
            return "etf"
        if is_explicit_stock_by_asset_class:
            return "stock"
        return "etf" if self._is_probable_etf_asset(symbol, str(asset_meta.get("name", ""))) else "stock"

    def get_next_market_open(self) -> Optional[datetime]:
        """Return next market-open timestamp from Alpaca clock when available."""
        if not self.is_connected():
            return None
        try:
            clock = self._trading_client.get_clock()
            next_open = getattr(clock, "next_open", None)
            if next_open is None:
                return None
            if isinstance(next_open, datetime):
                return next_open
            return None
        except (RuntimeError, APIError, OSError):
            return None
    
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
            symbol = str(pos.symbol).upper()
            asset_meta = self._get_asset_capabilities(symbol)
            result.append({
                "symbol": symbol,
                "quantity": float(pos.qty),
                "side": "long" if float(pos.qty) > 0 else "short",
                "avg_entry_price": float(pos.avg_entry_price),
                "current_price": float(pos.current_price),
                "market_value": float(pos.market_value),
                "cost_basis": float(pos.cost_basis),
                "unrealized_pnl": float(pos.unrealized_pl),
                "unrealized_pnl_percent": float(pos.unrealized_plpc) * 100,
                "asset_type": self._resolve_asset_type(symbol, asset_meta),
            })
        
        return result
    
    def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Submit an order to Alpaca.

        Args:
            symbol: Stock symbol
            side: Buy or sell
            order_type: Market, limit, etc.
            quantity: Number of shares
            price: Limit/stop price for non-market orders
            client_order_id: Client-generated idempotency key

        Returns:
            Order confirmation dict
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to Alpaca")

        # Map our OrderSide to Alpaca's OrderSide
        alpaca_side = AlpacaOrderSide.BUY if side == OrderSide.BUY else AlpacaOrderSide.SELL

        # Common kwargs for idempotency
        common_kwargs: Dict[str, Any] = {}
        if client_order_id:
            common_kwargs["client_order_id"] = client_order_id

        # Submit order based on type
        if order_type == OrderType.MARKET:
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=round(quantity, 9),
                side=alpaca_side,
                time_in_force=TimeInForce.DAY,
                **common_kwargs,
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
                limit_price=price,
                **common_kwargs,
            )
            order = self._trading_client.submit_order(order_data)

        elif order_type == OrderType.STOP:
            if price is None:
                raise ValueError("Price required for stop orders")

            order_data = StopOrderRequest(
                symbol=symbol,
                qty=quantity,
                side=alpaca_side,
                time_in_force=TimeInForce.DAY,
                stop_price=price,
                **common_kwargs,
            )
            order = self._trading_client.submit_order(order_data)

        elif order_type == OrderType.STOP_LIMIT:
            if price is None:
                raise ValueError("Price required for stop_limit orders")
            order_data = StopLimitOrderRequest(
                symbol=symbol,
                qty=quantity,
                side=alpaca_side,
                time_in_force=TimeInForce.DAY,
                stop_price=price,
                limit_price=price,
                **common_kwargs,
            )
            order = self._trading_client.submit_order(order_data)

        else:
            raise ValueError(f"Unsupported order type: {order_type}")

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
    
    def cancel_all_orders(self) -> int:
        """Cancel all open orders on the broker. Returns count cancelled (-1 if unknown)."""
        if not self.is_connected():
            raise RuntimeError("Not connected to Alpaca")
        try:
            cancel_responses = self._trading_client.cancel_orders()
            count = len(cancel_responses) if cancel_responses else 0
            logger.info("Cancelled all open orders (%d)", count)
            return count
        except Exception as e:
            logger.error("Failed to cancel all orders: %s", e)
            return 0

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
    
    @staticmethod
    def _to_utc_datetime(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def get_orders(
        self,
        status: Optional[OrderStatus] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
        symbols: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get orders with optional filtering and pagination.
        
        Args:
            status: Filter by status (optional)
            start: Optional start datetime (inclusive)
            end: Optional end datetime (inclusive)
            limit: Optional max rows to return
            symbols: Optional list of symbols to include
            
        Returns:
            List of order dicts
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to Alpaca")

        parsed_start = self._to_utc_datetime(start)
        parsed_end = self._to_utc_datetime(end)
        target_limit = max(1, int(limit)) if limit is not None else 500
        page_size = max(1, min(500, target_limit))

        normalized_symbols = [
            str(symbol or "").strip().upper()
            for symbol in (symbols or [])
            if str(symbol or "").strip()
        ]
        use_symbol_filter = len(normalized_symbols) > 0

        collected: List[Dict[str, Any]] = []
        next_until = parsed_end
        seen_ids: set[str] = set()

        while len(collected) < target_limit:
            request = GetOrdersRequest(limit=page_size)
            if status:
                alpaca_status = self._map_to_alpaca_status(status)
                if alpaca_status:
                    request.status = alpaca_status
            if parsed_start is not None:
                request.after = parsed_start
            if next_until is not None:
                request.until = next_until
            if use_symbol_filter:
                request.symbols = list(normalized_symbols)

            rows = self._trading_client.get_orders(filter=request)
            if not rows:
                break

            all_mapped_rows = [self._map_alpaca_order(row) for row in rows]
            mapped_rows = list(all_mapped_rows)
            if status is not None:
                mapped_rows = [
                    row for row in mapped_rows
                    if str(row.get("status", "")).strip().lower() == status.value
                ]
            if use_symbol_filter:
                symbol_set = set(normalized_symbols)
                mapped_rows = [
                    row for row in mapped_rows
                    if str(row.get("symbol", "")).upper() in symbol_set
                ]
            for row in mapped_rows:
                row_id = str(row.get("id", "")).strip()
                if not row_id or row_id in seen_ids:
                    continue
                seen_ids.add(row_id)
                collected.append(row)
                if len(collected) >= target_limit:
                    break

            oldest_created_at: Optional[datetime] = None
            for mapped in all_mapped_rows:
                created_raw = str(mapped.get("created_at", "")).strip()
                if not created_raw:
                    continue
                candidate = created_raw
                if candidate.endswith("Z"):
                    candidate = f"{candidate[:-1]}+00:00"
                try:
                    created_at = datetime.fromisoformat(candidate)
                except ValueError:
                    continue
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                if oldest_created_at is None or created_at < oldest_created_at:
                    oldest_created_at = created_at
            if oldest_created_at is None:
                break
            # Cursor pagination: fetch older rows next loop.
            next_until = oldest_created_at - timedelta(microseconds=1)
            if parsed_start is not None and next_until < parsed_start:
                break
            if len(rows) < page_size:
                break

        collected.sort(key=lambda row: str(row.get("created_at", "")), reverse=True)
        return collected[:target_limit]
    
    def get_market_data(
        self,
        symbol: str,
        include_bars: bool = False,
        bars_timeframe: TimeFrame = TimeFrame.Minute,
        bars_limit: int = 30,
    ) -> Dict[str, Any]:
        """
        Get current market data for a symbol.
        
        Args:
            symbol: Stock symbol
            include_bars: Include recent candle bars in response
            bars_timeframe: Bar timeframe for candles
            bars_limit: Number of bars to request
            
        Returns:
            Market data dict (price, volume, etc.)
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to Alpaca")

        normalized = str(symbol or "").strip().upper()
        if not normalized:
            return {"symbol": "", "price": 0.0, "error": "Invalid symbol"}

        multi = self.get_market_data_multi(
            symbols=[normalized],
            include_bars=include_bars,
            bars_timeframe=bars_timeframe,
            bars_limit=bars_limit,
        )
        return multi.get(normalized, {"symbol": normalized, "price": 0.0, "error": "No quote data available"})

    def get_market_data_multi(
        self,
        symbols: List[str],
        include_bars: bool = False,
        bars_timeframe: TimeFrame = TimeFrame.Minute,
        bars_limit: int = 30,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Get current market data for multiple symbols in one request.
        Optionally includes recent bars/candles for richer context.
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to Alpaca")

        normalized_symbols = [
            str(symbol or "").strip().upper()
            for symbol in symbols
            if str(symbol or "").strip()
        ]
        if not normalized_symbols:
            return {}

        quotes_map: Dict[str, Any] = {}
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=normalized_symbols)
            quotes_map = self._data_client.get_stock_latest_quote(request) or {}
        except (RuntimeError, APIError, OSError) as exc:
            logger.warning("Failed to fetch latest quotes for %s: %s", normalized_symbols, exc)
            quotes_map = {}

        result: Dict[str, Dict[str, Any]] = {}
        now_iso = datetime.now(timezone.utc).isoformat()

        for symbol in normalized_symbols:
            quote = quotes_map.get(symbol)
            if quote is not None:
                ask_price = self._safe_optional_float(getattr(quote, "ask_price", None)) or 0.0
                bid_price = self._safe_optional_float(getattr(quote, "bid_price", None)) or 0.0
                mid_price = float((ask_price + bid_price) / 2.0) if (ask_price > 0 and bid_price > 0) else max(ask_price, bid_price)
                row = {
                    "symbol": symbol,
                    "price": mid_price,
                    "ask_price": ask_price,
                    "bid_price": bid_price,
                    "ask_size": int(getattr(quote, "ask_size", 0) or 0),
                    "bid_size": int(getattr(quote, "bid_size", 0) or 0),
                    "volume": 0,
                    "timestamp": getattr(quote, "timestamp", datetime.now(timezone.utc)).isoformat(),
                    "data_source": "quote",
                }
            else:
                # Fallback path: use live stream cache or latest bar close.
                cached_quote = None
                with self._live_quote_cache_lock:
                    cached_quote = dict(self._live_quote_cache.get(symbol, {})) if symbol in self._live_quote_cache else None
                if cached_quote:
                    row = {
                        "symbol": symbol,
                        "price": float(cached_quote.get("price", 0.0) or 0.0),
                        "ask_price": self._safe_optional_float(cached_quote.get("ask_price")) or 0.0,
                        "bid_price": self._safe_optional_float(cached_quote.get("bid_price")) or 0.0,
                        "ask_size": int(cached_quote.get("ask_size", 0) or 0),
                        "bid_size": int(cached_quote.get("bid_size", 0) or 0),
                        "volume": int(cached_quote.get("volume", 0) or 0),
                        "timestamp": str(cached_quote.get("timestamp") or now_iso),
                        "data_source": "stream_cache",
                    }
                else:
                    row = {
                        "symbol": symbol,
                        "price": 0.0,
                        "ask_price": 0.0,
                        "bid_price": 0.0,
                        "ask_size": 0,
                        "bid_size": 0,
                        "volume": 0,
                        "timestamp": now_iso,
                        "error": "No quote data available",
                        "data_source": "unavailable",
                    }
                if include_bars:
                    try:
                        fallback_bars = self.get_historical_bars(
                            symbol=symbol,
                            start=datetime.now(timezone.utc) - timedelta(days=2),
                            end=datetime.now(timezone.utc),
                            limit=max(1, int(bars_limit)),
                            timeframe=bars_timeframe,
                        )
                    except (RuntimeError, APIError, OSError):
                        fallback_bars = []
                    if fallback_bars:
                        latest_close = self._safe_optional_float(fallback_bars[-1].get("close")) or 0.0
                        if latest_close > 0 and float(row.get("price", 0.0) or 0.0) <= 0:
                            row["price"] = latest_close
                            row["data_source"] = "bars_fallback"
                        row["bars"] = fallback_bars
                result[symbol] = row
                continue

            result[symbol] = row

        if include_bars:
            start = datetime.now(timezone.utc) - timedelta(days=2)
            end = datetime.now(timezone.utc)
            request = StockBarsRequest(
                symbol_or_symbols=normalized_symbols,
                timeframe=bars_timeframe,
                start=start,
                end=end,
                limit=max(1, int(bars_limit)),
            )
            try:
                bars_response = self._data_client.get_stock_bars(request)
                bars_data = bars_response.data if hasattr(bars_response, "data") else bars_response
            except (RuntimeError, APIError, OSError) as exc:
                logger.warning("Failed to fetch bars for %s: %s", normalized_symbols, exc)
                bars_data = {}

            for symbol in normalized_symbols:
                raw_bars = bars_data.get(symbol, []) if isinstance(bars_data, dict) else []
                bar_rows: List[Dict[str, Any]] = []
                for bar in raw_bars:
                    bar_rows.append({
                        "timestamp": getattr(bar, "timestamp", None),
                        "open": float(getattr(bar, "open", 0.0) or 0.0),
                        "high": float(getattr(bar, "high", 0.0) or 0.0),
                        "low": float(getattr(bar, "low", 0.0) or 0.0),
                        "close": float(getattr(bar, "close", 0.0) or 0.0),
                        "volume": int(getattr(bar, "volume", 0) or 0),
                    })
                if symbol in result:
                    if bar_rows:
                        result[symbol]["bars"] = bar_rows
                    elif "bars" not in result[symbol]:
                        result[symbol]["bars"] = []
                    if (
                        (self._safe_optional_float(result[symbol].get("price")) or 0.0) <= 0
                        and len(bar_rows) > 0
                    ):
                        result[symbol]["price"] = float(bar_rows[-1]["close"] or 0.0)
                        result[symbol]["data_source"] = "bars_fallback"

        return result

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

    def start_trade_update_stream(self, on_update: Callable[[Dict[str, Any]], None]) -> bool:
        """
        Start Alpaca trading websocket stream for trade updates.
        Safe to call multiple times.
        """
        if not self.is_connected():
            logger.warning("Cannot start trade update stream: broker not connected")
            return False
        if self._trade_stream_running:
            return True

        self._trade_update_callback = on_update
        self._trade_stream_running = True

        def _run_stream() -> None:
            try:
                from alpaca.trading.stream import TradingStream
            except (ImportError, ModuleNotFoundError) as exc:
                logger.warning(f"TradingStream not available, streaming disabled: {exc}")
                self._trade_stream_running = False
                return

            async def _handler(data: Any) -> None:
                try:
                    payload = {
                        "event": str(getattr(data, "event", "")),
                        "order_id": str(getattr(data, "order_id", "")),
                        "symbol": str(getattr(data, "symbol", "")),
                        "status": str(getattr(data, "order_status", "")),
                    }
                    if self._trade_update_callback:
                        self._trade_update_callback(payload)
                except (RuntimeError, ValueError, TypeError) as callback_exc:
                    logger.warning(f"Trade update callback error: {callback_exc}")

            try:
                self._trade_stream = TradingStream(self.api_key, self.secret_key, paper=self.paper)
                self._trade_stream.subscribe_trade_updates(_handler)
                self._trade_stream.run()
            except (RuntimeError, APIError, OSError) as stream_exc:
                logger.warning(f"Trade update stream ended: {stream_exc}")
            finally:
                self._trade_stream_running = False
                self._trade_stream = None

        self._trade_stream_thread = threading.Thread(target=_run_stream, daemon=True)
        self._trade_stream_thread.start()
        logger.info("Alpaca trade update stream started")
        return True

    def start_market_data_stream(
        self,
        symbols: List[str],
        on_update: Callable[[Dict[str, Any]], None],
    ) -> bool:
        """
        Start Alpaca market-data websocket stream for quote updates.
        Captures quotes into an in-memory cache and forwards updates to callback.
        """
        if not self.is_connected():
            logger.warning("Cannot start market data stream: broker not connected")
            return False
        normalized_symbols = [
            str(symbol or "").strip().upper()
            for symbol in symbols
            if str(symbol or "").strip()
        ]
        if not normalized_symbols:
            logger.warning("Cannot start market data stream: no symbols provided")
            return False
        if self._market_data_stream_running:
            return True

        self._market_data_stream_symbols = list(dict.fromkeys(normalized_symbols))
        self._market_data_update_callback = on_update
        self._market_data_stream_running = True

        def _run_stream() -> None:
            try:
                from alpaca.data.live.stock import StockDataStream  # type: ignore
            except (ImportError, ModuleNotFoundError) as exc:
                logger.warning(f"StockDataStream not available, market-data streaming disabled: {exc}")
                self._market_data_stream_running = False
                return

            async def _quote_handler(data: Any) -> None:
                try:
                    symbol = str(getattr(data, "symbol", "")).strip().upper()
                    ask_price = self._safe_optional_float(getattr(data, "ask_price", None)) or 0.0
                    bid_price = self._safe_optional_float(getattr(data, "bid_price", None)) or 0.0
                    mid_price = float((ask_price + bid_price) / 2.0) if (ask_price > 0 and bid_price > 0) else max(ask_price, bid_price)
                    payload = {
                        "event": "quote",
                        "symbol": symbol,
                        "price": mid_price,
                        "ask_price": ask_price,
                        "bid_price": bid_price,
                        "ask_size": int(getattr(data, "ask_size", 0) or 0),
                        "bid_size": int(getattr(data, "bid_size", 0) or 0),
                        "timestamp": getattr(data, "timestamp", datetime.now(timezone.utc)).isoformat(),
                    }
                    if symbol:
                        with self._live_quote_cache_lock:
                            self._live_quote_cache[symbol] = dict(payload)
                    if self._market_data_update_callback:
                        self._market_data_update_callback(payload)
                except (RuntimeError, ValueError, TypeError) as callback_exc:
                    logger.warning(f"Market data stream callback error: {callback_exc}")

            try:
                self._market_data_stream = StockDataStream(self.api_key, self.secret_key)
                self._market_data_stream.subscribe_quotes(_quote_handler, *self._market_data_stream_symbols)
                self._market_data_stream.run()
            except (RuntimeError, APIError, OSError) as stream_exc:
                logger.warning(f"Market data stream ended: {stream_exc}")
            finally:
                self._market_data_stream_running = False
                self._market_data_stream = None

        self._market_data_stream_thread = threading.Thread(target=_run_stream, daemon=True)
        self._market_data_stream_thread.start()
        logger.info("Alpaca market data stream started for %d symbol(s)", len(self._market_data_stream_symbols))
        return True

    def stop_market_data_stream(self) -> bool:
        """Stop Alpaca market-data websocket stream."""
        self._market_data_stream_running = False
        try:
            if self._market_data_stream is not None:
                stop_ws = getattr(self._market_data_stream, "stop_ws", None)
                if callable(stop_ws):
                    stop_ws()
            self._market_data_stream = None
            return True
        except (RuntimeError, OSError) as exc:
            logger.warning(f"Failed to stop market data stream cleanly: {exc}")
            return False

    def stop_trade_update_stream(self) -> bool:
        """Stop Alpaca trade update websocket stream."""
        self._trade_stream_running = False
        try:
            if self._trade_stream is not None:
                stop_ws = getattr(self._trade_stream, "stop_ws", None)
                if callable(stop_ws):
                    stop_ws()
            self._trade_stream = None
            return True
        except (RuntimeError, OSError) as exc:
            logger.warning(f"Failed to stop trade update stream cleanly: {exc}")
            return False
    
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
            raw_order_type = order.order_type
        else:
            raw_order_type = order.type
        order_type_value = self._map_from_alpaca_order_type(raw_order_type)

        limit_price = getattr(order, "limit_price", None)
        stop_price = getattr(order, "stop_price", None)
        normalized_limit_price = self._safe_optional_float(limit_price)
        normalized_stop_price = self._safe_optional_float(stop_price)
        normalized_price = normalized_limit_price if normalized_limit_price is not None else normalized_stop_price
            
        return {
            "id": str(order.id),
            "client_order_id": str(order.client_order_id) if order.client_order_id is not None else None,
            "symbol": order.symbol,
            "side": order.side.value,
            "type": order_type_value,
            "quantity": float(order.qty),
            "filled_quantity": float(order.filled_qty) if order.filled_qty else 0.0,
            "price": normalized_price,
            "stop_price": normalized_stop_price,
            "avg_fill_price": float(order.filled_avg_price) if order.filled_avg_price else None,
            "status": self._map_from_alpaca_status(order.status),
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat() if order.updated_at else order.created_at.isoformat(),
            "commission": self._safe_optional_float(getattr(order, "commission", None)) or 0.0,
        }

    def _map_from_alpaca_order_type(self, alpaca_order_type: Any) -> str:
        """Map Alpaca order type object/value to our normalized order-type string."""
        raw = alpaca_order_type.value if hasattr(alpaca_order_type, "value") else str(alpaca_order_type)
        mapping = {
            AlpacaOrderType.MARKET.value: OrderType.MARKET.value,
            AlpacaOrderType.LIMIT.value: OrderType.LIMIT.value,
            AlpacaOrderType.STOP.value: OrderType.STOP.value,
            AlpacaOrderType.STOP_LIMIT.value: OrderType.STOP_LIMIT.value,
        }
        return mapping.get(str(raw).lower(), str(raw).lower())

    @staticmethod
    def _safe_optional_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    
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
    
    def _map_to_alpaca_status(self, status: OrderStatus) -> Optional[QueryOrderStatus]:
        """Map our OrderStatus to Alpaca query status (open/closed)."""
        mapping = {
            OrderStatus.PENDING: QueryOrderStatus.OPEN,
            OrderStatus.SUBMITTED: QueryOrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED: QueryOrderStatus.OPEN,
            OrderStatus.FILLED: QueryOrderStatus.CLOSED,
            OrderStatus.CANCELLED: QueryOrderStatus.CLOSED,
            OrderStatus.REJECTED: QueryOrderStatus.CLOSED,
        }
        return mapping.get(status)
