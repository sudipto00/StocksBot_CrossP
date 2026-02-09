"""
Tests for Alpaca broker integration.

Uses mocked Alpaca API responses to test the adapter behavior
without requiring real API credentials or making real API calls.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

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
        assert abs(pos["unrealized_pnl_percent"] - 3.33) < 0.01  # Allow for float precision
    
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
    
    def test_submit_stop_order_not_implemented(self, alpaca_broker):
        """Test that stop orders raise NotImplementedError."""
        alpaca_broker._connected = True
        alpaca_broker._trading_client = Mock()
        
        with pytest.raises(NotImplementedError):
            alpaca_broker.submit_order(
                symbol="AAPL",
                side=OrderSide.BUY,
                order_type=OrderType.STOP,
                quantity=100,
                price=150.00
            )
    
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
