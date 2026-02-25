"""
Tests for Alpaca broker integration.

Uses mocked Alpaca API responses to test the adapter behavior
without requiring real API credentials or making real API calls.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone
import uuid

from integrations.alpaca_broker import AlpacaBroker
from services.broker import OrderSide, OrderType, OrderStatus


@pytest.fixture
def alpaca_broker():
    """Create an AlpacaBroker instance for testing."""
    return AlpacaBroker(
        api_key="test_api_key",
        secret_key="test_secret_key",
        paper=True
    )


@pytest.fixture
def mock_account():
    """Mock Alpaca account object."""
    account = Mock()
    account.account_number = "TEST123"
    account.status = "ACTIVE"
    account.currency = "USD"
    account.cash = "50000.00"
    account.portfolio_value = "100000.00"
    account.equity = "100000.00"
    account.buying_power = "200000.00"
    account.pattern_day_trader = False
    account.trading_blocked = False
    account.transfers_blocked = False
    account.account_blocked = False
    return account


@pytest.fixture
def mock_position():
    """Mock Alpaca position object."""
    position = Mock()
    position.symbol = "AAPL"
    position.qty = "100"
    position.avg_entry_price = "150.00"
    position.current_price = "155.00"
    position.market_value = "15500.00"
    position.cost_basis = "15000.00"
    position.unrealized_pl = "500.00"
    position.unrealized_plpc = "0.0333"
    return position


@pytest.fixture
def mock_order():
    """Mock Alpaca order object."""
    from alpaca.trading.enums import OrderStatus as AlpacaOrderStatus, OrderSide as AlpacaOrderSide, OrderType as AlpacaOrderType
    
    order = Mock()
    order.id = "order-123"
    order.client_order_id = "client-123"
    order.symbol = "AAPL"
    order.side = AlpacaOrderSide.BUY
    order.order_type = AlpacaOrderType.MARKET
    order.qty = "100"
    order.filled_qty = "100"
    order.limit_price = None
    order.filled_avg_price = "150.00"
    order.status = AlpacaOrderStatus.FILLED
    order.created_at = datetime.now()
    order.updated_at = datetime.now()
    return order


@pytest.fixture
def mock_quote():
    """Mock Alpaca quote object."""
    quote = Mock()
    quote.ask_price = "155.50"
    quote.bid_price = "155.00"
    quote.ask_size = 100
    quote.bid_size = 200
    quote.timestamp = datetime.now()
    return quote


class TestAlpacaBrokerConnection:
    """Test Alpaca broker connection methods."""
    
    def test_init(self, alpaca_broker):
        """Test broker initialization."""
        assert alpaca_broker.api_key == "test_api_key"
        assert alpaca_broker.secret_key == "test_secret_key"
        assert alpaca_broker.paper is True
        assert alpaca_broker.is_connected() is False
    
    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_connect_success(self, mock_data_client, mock_trading_client, alpaca_broker, mock_account):
        """Test successful connection to Alpaca."""
        # Setup mock
        mock_client_instance = MagicMock()
        mock_client_instance.get_account.return_value = mock_account
        mock_trading_client.return_value = mock_client_instance
        
        # Connect
        result = alpaca_broker.connect()
        
        # Verify
        assert result is True
        assert alpaca_broker.is_connected() is True
        mock_trading_client.assert_called_once_with(
            api_key="test_api_key",
            secret_key="test_secret_key",
            paper=True
        )
    
    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_connect_failure(self, mock_data_client, mock_trading_client, alpaca_broker):
        """Test failed connection to Alpaca."""
        # Setup mock to raise exception
        mock_trading_client.side_effect = Exception("Invalid credentials")
        
        # Connect
        result = alpaca_broker.connect()
        
        # Verify
        assert result is False
        assert alpaca_broker.is_connected() is False
    
    def test_disconnect(self, alpaca_broker):
        """Test disconnection from Alpaca."""
        alpaca_broker._connected = True
        alpaca_broker._trading_client = Mock()
        
        result = alpaca_broker.disconnect()
        
        assert result is True
        assert alpaca_broker.is_connected() is False
        assert alpaca_broker._trading_client is None


class TestAlpacaBrokerAccount:
    """Test Alpaca account information methods."""
    
    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_get_account_info(self, mock_data_client, mock_trading_client, alpaca_broker, mock_account):
        """Test getting account information."""
        # Setup
        mock_client_instance = MagicMock()
        mock_client_instance.get_account.return_value = mock_account
        mock_trading_client.return_value = mock_client_instance
        alpaca_broker.connect()
        
        # Get account info
        info = alpaca_broker.get_account_info()
        
        # Verify
        assert info["account_number"] == "TEST123"
        assert info["status"] == "ACTIVE"
        assert info["cash"] == 50000.00
        assert info["portfolio_value"] == 100000.00
        assert info["equity"] == 100000.00
        assert info["buying_power"] == 200000.00
        assert info["pattern_day_trader"] is False
    
    def test_get_account_info_not_connected(self, alpaca_broker):
        """Test getting account info when not connected."""
        with pytest.raises(RuntimeError, match="Not connected"):
            alpaca_broker.get_account_info()


class TestAlpacaBrokerPositions:
    """Test Alpaca position management methods."""
    
    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_get_positions(self, mock_data_client, mock_trading_client, alpaca_broker, mock_position, mock_account):
        """Test getting positions."""
        # Setup
        mock_client_instance = MagicMock()
        mock_client_instance.get_account.return_value = mock_account
        mock_client_instance.get_all_positions.return_value = [mock_position]
        mock_client_instance.get_asset.return_value = Mock(
            tradable=True,
            fractionable=True,
            shortable=True,
            easy_to_borrow=True,
            marginable=True,
            asset_class="us_equity",
            name="Apple Inc.",
        )
        mock_trading_client.return_value = mock_client_instance
        alpaca_broker.connect()
        
        # Get positions
        positions = alpaca_broker.get_positions()
        
        # Verify
        assert len(positions) == 1
        pos = positions[0]
        assert pos["symbol"] == "AAPL"
        assert pos["quantity"] == 100.0
        assert pos["side"] == "long"
        assert pos["avg_entry_price"] == 150.00
        assert pos["current_price"] == 155.00
        assert pos["unrealized_pnl"] == 500.00
        assert pos["asset_type"] == "stock"
        assert abs(pos["unrealized_pnl_percent"] - 3.33) < 0.01  # Allow for float precision

    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_get_positions_classifies_etf_from_asset_class(
        self, mock_data_client, mock_trading_client, alpaca_broker, mock_position, mock_account
    ):
        """ETF asset_class should be surfaced as asset_type=etf."""
        mock_position.symbol = "SPY"
        mock_client_instance = MagicMock()
        mock_client_instance.get_account.return_value = mock_account
        mock_client_instance.get_all_positions.return_value = [mock_position]
        mock_client_instance.get_asset.return_value = Mock(
            tradable=True,
            fractionable=True,
            shortable=True,
            easy_to_borrow=True,
            marginable=True,
            asset_class="us_equity_etf",
            name="SPDR S&P 500 ETF Trust",
        )
        mock_trading_client.return_value = mock_client_instance
        alpaca_broker.connect()

        positions = alpaca_broker.get_positions()

        assert len(positions) == 1
        assert positions[0]["symbol"] == "SPY"
        assert positions[0]["asset_type"] == "etf"

    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_get_positions_classifies_etf_from_heuristic_when_asset_class_is_generic(
        self, mock_data_client, mock_trading_client, alpaca_broker, mock_position, mock_account
    ):
        """Generic us_equity should still classify ETFs using symbol/name fallback."""
        mock_position.symbol = "QQQ"
        mock_client_instance = MagicMock()
        mock_client_instance.get_account.return_value = mock_account
        mock_client_instance.get_all_positions.return_value = [mock_position]
        mock_client_instance.get_asset.return_value = Mock(
            tradable=True,
            fractionable=True,
            shortable=True,
            easy_to_borrow=True,
            marginable=True,
            asset_class="us_equity",
            name="Invesco QQQ Trust",
        )
        mock_trading_client.return_value = mock_client_instance
        alpaca_broker.connect()

        positions = alpaca_broker.get_positions()

        assert len(positions) == 1
        assert positions[0]["symbol"] == "QQQ"
        assert positions[0]["asset_type"] == "etf"
    
    def test_get_positions_not_connected(self, alpaca_broker):
        """Test getting positions when not connected."""
        with pytest.raises(RuntimeError, match="Not connected"):
            alpaca_broker.get_positions()


class TestAlpacaBrokerOrders:
    """Test Alpaca order management methods."""
    
    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_submit_market_order(self, mock_data_client, mock_trading_client, alpaca_broker, mock_order, mock_account):
        """Test submitting a market order."""
        # Setup
        mock_client_instance = MagicMock()
        mock_client_instance.get_account.return_value = mock_account
        mock_client_instance.submit_order.return_value = mock_order
        mock_trading_client.return_value = mock_client_instance
        alpaca_broker.connect()
        
        # Submit order
        result = alpaca_broker.submit_order(
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100
        )
        
        # Verify
        assert result["id"] == "order-123"
        assert result["symbol"] == "AAPL"
        assert result["side"] == "buy"
        assert result["type"] == "market"
        assert result["quantity"] == 100.0
        assert result["status"] == "filled"

    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_submit_order_normalizes_uuid_ids_to_strings(self, mock_data_client, mock_trading_client, alpaca_broker, mock_order, mock_account):
        """Broker responses with UUID ids should be normalized to strings."""
        mock_order.id = uuid.uuid4()
        mock_order.client_order_id = uuid.uuid4()
        mock_client_instance = MagicMock()
        mock_client_instance.get_account.return_value = mock_account
        mock_client_instance.submit_order.return_value = mock_order
        mock_trading_client.return_value = mock_client_instance
        alpaca_broker.connect()

        result = alpaca_broker.submit_order(
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1
        )
        assert isinstance(result["id"], str)
        assert isinstance(result["client_order_id"], str)
    
    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_submit_limit_order(self, mock_data_client, mock_trading_client, alpaca_broker, mock_order, mock_account):
        """Test submitting a limit order."""
        # Setup
        mock_order.limit_price = "150.00"
        mock_client_instance = MagicMock()
        mock_client_instance.get_account.return_value = mock_account
        mock_client_instance.submit_order.return_value = mock_order
        mock_trading_client.return_value = mock_client_instance
        alpaca_broker.connect()
        
        # Submit order
        result = alpaca_broker.submit_order(
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=150.00
        )
        
        # Verify
        assert result["price"] == 150.00
    
    def test_submit_limit_order_no_price(self, alpaca_broker):
        """Test submitting limit order without price raises error."""
        alpaca_broker._connected = True
        alpaca_broker._trading_client = Mock()
        
        with pytest.raises(ValueError, match="Price required"):
            alpaca_broker.submit_order(
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=100
            )
    
    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_submit_stop_order(self, mock_data_client, mock_trading_client, alpaca_broker, mock_order, mock_account):
        """Test submitting a stop order."""
        from alpaca.trading.enums import OrderType as AlpacaOrderType
        mock_order.order_type = AlpacaOrderType.STOP
        mock_order.limit_price = None
        mock_order.stop_price = "149.50"

        mock_client_instance = MagicMock()
        mock_client_instance.get_account.return_value = mock_account
        mock_client_instance.submit_order.return_value = mock_order
        mock_trading_client.return_value = mock_client_instance
        alpaca_broker.connect()

        result = alpaca_broker.submit_order(
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.STOP,
            quantity=100,
            price=149.50
        )
        assert result["type"] == "stop"
        assert result["price"] == 149.50

    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_submit_stop_limit_order(self, mock_data_client, mock_trading_client, alpaca_broker, mock_order, mock_account):
        """Test submitting a stop-limit order."""
        from alpaca.trading.enums import OrderType as AlpacaOrderType
        mock_order.order_type = AlpacaOrderType.STOP_LIMIT
        mock_order.limit_price = "149.00"
        mock_order.stop_price = "149.00"

        mock_client_instance = MagicMock()
        mock_client_instance.get_account.return_value = mock_account
        mock_client_instance.submit_order.return_value = mock_order
        mock_trading_client.return_value = mock_client_instance
        alpaca_broker.connect()

        result = alpaca_broker.submit_order(
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.STOP_LIMIT,
            quantity=100,
            price=149.00
        )
        assert result["type"] == "stop_limit"
        assert result["price"] == 149.00
    
    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_cancel_order(self, mock_data_client, mock_trading_client, alpaca_broker, mock_account):
        """Test cancelling an order."""
        # Setup
        mock_client_instance = MagicMock()
        mock_client_instance.get_account.return_value = mock_account
        mock_trading_client.return_value = mock_client_instance
        alpaca_broker.connect()
        
        # Cancel order
        result = alpaca_broker.cancel_order("order-123")
        
        # Verify
        assert result is True
        mock_client_instance.cancel_order_by_id.assert_called_once_with("order-123")
    
    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_get_order(self, mock_data_client, mock_trading_client, alpaca_broker, mock_order, mock_account):
        """Test getting order details."""
        # Setup
        mock_client_instance = MagicMock()
        mock_client_instance.get_account.return_value = mock_account
        mock_client_instance.get_order_by_id.return_value = mock_order
        mock_trading_client.return_value = mock_client_instance
        alpaca_broker.connect()
        
        # Get order
        result = alpaca_broker.get_order("order-123")
        
        # Verify
        assert result["id"] == "order-123"
        assert result["symbol"] == "AAPL"
    
    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_get_orders(self, mock_data_client, mock_trading_client, alpaca_broker, mock_order, mock_account):
        """Test getting list of orders."""
        # Setup
        mock_client_instance = MagicMock()
        mock_client_instance.get_account.return_value = mock_account
        mock_client_instance.get_orders.return_value = [mock_order]
        mock_trading_client.return_value = mock_client_instance
        alpaca_broker.connect()
        
        # Get orders
        result = alpaca_broker.get_orders()
        
        # Verify
        assert len(result) == 1
        assert result[0]["id"] == "order-123"

    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_get_orders_supports_filters_and_pagination(
        self, mock_data_client, mock_trading_client, alpaca_broker, mock_account
    ):
        """get_orders should pass filters to Alpaca and paginate until limit."""
        from alpaca.trading.enums import (
            OrderStatus as AlpacaOrderStatus,
            OrderSide as AlpacaOrderSide,
            OrderType as AlpacaOrderType,
        )

        def _mk_order(order_id: str, symbol: str, created_at: datetime) -> Mock:
            row = Mock()
            row.id = order_id
            row.client_order_id = f"client-{order_id}"
            row.symbol = symbol
            row.side = AlpacaOrderSide.BUY
            row.order_type = AlpacaOrderType.MARKET
            row.qty = "1"
            row.filled_qty = "0"
            row.limit_price = None
            row.stop_price = None
            row.filled_avg_price = None
            row.status = AlpacaOrderStatus.NEW
            row.created_at = created_at
            row.updated_at = created_at
            return row

        newer = datetime(2026, 2, 10, 14, 0, tzinfo=timezone.utc)
        older = datetime(2026, 2, 9, 14, 0, tzinfo=timezone.utc)
        oldest = datetime(2026, 2, 8, 14, 0, tzinfo=timezone.utc)
        page1 = [_mk_order("order-aapl-new", "AAPL", newer), _mk_order("order-msft", "MSFT", older)]
        page2 = [_mk_order("order-aapl-new", "AAPL", newer), _mk_order("order-aapl-old", "AAPL", oldest)]

        mock_client_instance = MagicMock()
        mock_client_instance.get_account.return_value = mock_account
        requests = []

        def _side_effect(*args, **kwargs):
            req = kwargs.get("filter")
            requests.append(req)
            if len(requests) == 1:
                return page1
            if len(requests) == 2:
                return page2
            return []

        mock_client_instance.get_orders.side_effect = _side_effect
        mock_trading_client.return_value = mock_client_instance
        alpaca_broker.connect()

        start = datetime(2026, 2, 1, 0, 0, 0)
        end = datetime(2026, 2, 28, 23, 59, 59)
        result = alpaca_broker.get_orders(
            status=OrderStatus.PENDING,
            start=start,
            end=end,
            limit=2,
            symbols=["aapl"],
        )

        assert [row["id"] for row in result] == ["order-aapl-new", "order-aapl-old"]
        assert all(row["symbol"] == "AAPL" for row in result)
        assert len(requests) >= 2
        assert list(requests[0].symbols) == ["AAPL"]
        assert requests[0].after is not None
        assert requests[0].until is not None


class TestAlpacaBrokerMarketData:
    """Test Alpaca market data methods."""
    
    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_get_market_data(self, mock_data_client_class, mock_trading_client, alpaca_broker, mock_quote, mock_account):
        """Test getting market data."""
        # Setup
        mock_trading_instance = MagicMock()
        mock_trading_instance.get_account.return_value = mock_account
        mock_trading_client.return_value = mock_trading_instance
        
        mock_data_instance = MagicMock()
        mock_data_instance.get_stock_latest_quote.return_value = {"AAPL": mock_quote}
        mock_data_client_class.return_value = mock_data_instance
        
        alpaca_broker.connect()
        
        # Get market data
        result = alpaca_broker.get_market_data("AAPL")
        
        # Verify
        assert result["symbol"] == "AAPL"
        assert result["ask_price"] == 155.50
        assert result["bid_price"] == 155.00
        assert result["ask_size"] == 100
        assert result["bid_size"] == 200
    
    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_get_market_data_no_quote(self, mock_data_client_class, mock_trading_client, alpaca_broker, mock_account):
        """Test getting market data when no quote available."""
        # Setup
        mock_trading_instance = MagicMock()
        mock_trading_instance.get_account.return_value = mock_account
        mock_trading_client.return_value = mock_trading_instance
        
        mock_data_instance = MagicMock()
        mock_data_instance.get_stock_latest_quote.return_value = {}
        mock_data_client_class.return_value = mock_data_instance
        
        alpaca_broker.connect()
        
        # Get market data
        result = alpaca_broker.get_market_data("INVALID")
        
        # Verify
        assert result["symbol"] == "INVALID"
        assert result["price"] == 0.0
        assert "error" in result

    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_get_market_data_multi_includes_bars_and_stream_cache_fallback(
        self, mock_data_client_class, mock_trading_client, alpaca_broker, mock_account, mock_quote
    ):
        """Multi-symbol market data should combine quote, bars, and stream-cache fallback."""
        mock_trading_instance = MagicMock()
        mock_trading_instance.get_account.return_value = mock_account
        mock_trading_client.return_value = mock_trading_instance

        mock_bar = Mock()
        mock_bar.timestamp = datetime.now(timezone.utc)
        mock_bar.open = "100.0"
        mock_bar.high = "102.0"
        mock_bar.low = "99.5"
        mock_bar.close = "101.0"
        mock_bar.volume = 1234

        mock_data_instance = MagicMock()
        mock_data_instance.get_stock_latest_quote.return_value = {"AAPL": mock_quote}
        mock_data_instance.get_stock_bars.return_value = {"AAPL": [mock_bar], "MSFT": []}
        mock_data_client_class.return_value = mock_data_instance
        alpaca_broker.connect()

        alpaca_broker._live_quote_cache["MSFT"] = {
            "price": 250.5,
            "ask_price": 250.7,
            "bid_price": 250.3,
            "ask_size": 10,
            "bid_size": 12,
            "volume": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        result = alpaca_broker.get_market_data_multi(["aapl", "msft"], include_bars=True, bars_limit=1)

        assert set(result.keys()) == {"AAPL", "MSFT"}
        assert result["AAPL"]["data_source"] == "quote"
        assert len(result["AAPL"]["bars"]) == 1
        assert result["MSFT"]["data_source"] == "stream_cache"
        assert result["MSFT"]["price"] == 250.5

    @patch('integrations.alpaca_broker.TradingClient')
    @patch('integrations.alpaca_broker.StockHistoricalDataClient')
    def test_get_market_data_multi_falls_back_to_historical_bars_when_missing_quotes(
        self, mock_data_client_class, mock_trading_client, alpaca_broker, mock_account
    ):
        """Missing quote and cache should still derive price from recent bars."""
        mock_trading_instance = MagicMock()
        mock_trading_instance.get_account.return_value = mock_account
        mock_trading_client.return_value = mock_trading_instance

        mock_data_instance = MagicMock()
        mock_data_instance.get_stock_latest_quote.return_value = {}
        mock_data_instance.get_stock_bars.return_value = {}
        mock_data_client_class.return_value = mock_data_instance
        alpaca_broker.connect()

        alpaca_broker.get_historical_bars = MagicMock(return_value=[
            {
                "timestamp": datetime.now(timezone.utc),
                "open": 299.0,
                "high": 301.0,
                "low": 298.0,
                "close": 300.5,
                "volume": 999,
            }
        ])
        result = alpaca_broker.get_market_data_multi(["TSLA"], include_bars=True, bars_limit=1)

        assert result["TSLA"]["data_source"] == "bars_fallback"
        assert result["TSLA"]["price"] == 300.5
        assert len(result["TSLA"]["bars"]) == 1
        alpaca_broker.get_historical_bars.assert_called_once()

    def test_start_market_data_stream_requires_connection(self, alpaca_broker):
        """Market-data stream should refuse to start when broker is disconnected."""
        started = alpaca_broker.start_market_data_stream(["AAPL"], lambda _: None)
        assert started is False

    def test_stop_market_data_stream_stops_underlying_socket(self, alpaca_broker):
        """stop_market_data_stream should invoke stop_ws when available."""
        mock_stream = MagicMock()
        alpaca_broker._market_data_stream = mock_stream
        alpaca_broker._market_data_stream_running = True

        stopped = alpaca_broker.stop_market_data_stream()

        assert stopped is True
        mock_stream.stop_ws.assert_called_once()
        assert alpaca_broker._market_data_stream is None
