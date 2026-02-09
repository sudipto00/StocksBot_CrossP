"""
Tests for backend engine and services modules.

Tests module instantiation and basic functionality.
"""

import pytest
from engine.strategy_runner import StrategyRunner, StrategyStatus
from engine.risk_manager import RiskManager
from services.portfolio import PortfolioService
from services.broker import PaperBroker, OrderSide, OrderType, OrderStatus


# ============================================================================
# Engine Tests
# ============================================================================

def test_strategy_runner_instantiation():
    """Test StrategyRunner can be instantiated."""
    runner = StrategyRunner()
    assert runner is not None
    assert runner.status == StrategyStatus.STOPPED
    assert len(runner.strategies) == 0


def test_strategy_runner_load_strategy():
    """Test loading a strategy."""
    runner = StrategyRunner()
    config = {"param1": "value1"}
    result = runner.load_strategy("test-strategy", config)
    
    assert result is True
    assert "test-strategy" in runner.strategies
    assert runner.strategies["test-strategy"]["config"] == config


def test_strategy_runner_start_stop():
    """Test starting and stopping strategies."""
    runner = StrategyRunner()
    runner.load_strategy("test-strategy", {})
    
    # Start strategy
    result = runner.start_strategy("test-strategy")
    assert result is True
    assert runner.strategies["test-strategy"]["status"] == StrategyStatus.RUNNING
    assert runner.status == StrategyStatus.RUNNING
    
    # Stop strategy
    result = runner.stop_strategy("test-strategy")
    assert result is True
    assert runner.strategies["test-strategy"]["status"] == StrategyStatus.STOPPED
    assert runner.status == StrategyStatus.STOPPED


def test_risk_manager_instantiation():
    """Test RiskManager can be instantiated."""
    risk_mgr = RiskManager()
    assert risk_mgr is not None
    assert risk_mgr.max_position_size == 10000.0
    assert risk_mgr.daily_loss_limit == 500.0
    assert risk_mgr.circuit_breaker_active is False


def test_risk_manager_validate_order():
    """Test order validation."""
    risk_mgr = RiskManager(max_position_size=5000.0)
    
    # Valid order
    is_valid, error = risk_mgr.validate_order("AAPL", 10, 100.0, {})
    assert is_valid is True
    assert error is None
    
    # Order too large
    is_valid, error = risk_mgr.validate_order("AAPL", 100, 100.0, {})
    assert is_valid is False
    assert error is not None


def test_risk_manager_circuit_breaker():
    """Test circuit breaker activation."""
    risk_mgr = RiskManager()
    
    # Activate circuit breaker
    risk_mgr.activate_circuit_breaker("Test reason")
    assert risk_mgr.circuit_breaker_active is True
    
    # Orders should be rejected
    is_valid, error = risk_mgr.validate_order("AAPL", 10, 100.0, {})
    assert is_valid is False
    assert "circuit breaker" in error.lower()
    
    # Deactivate
    risk_mgr.deactivate_circuit_breaker()
    assert risk_mgr.circuit_breaker_active is False


def test_risk_manager_get_metrics():
    """Test risk metrics retrieval."""
    risk_mgr = RiskManager()
    metrics = risk_mgr.get_risk_metrics()
    
    assert "daily_pnl" in metrics
    assert "daily_loss_limit" in metrics
    assert "circuit_breaker_active" in metrics
    assert "max_position_size" in metrics


# ============================================================================
# Services Tests
# ============================================================================

def test_portfolio_service_instantiation():
    """Test PortfolioService can be instantiated."""
    portfolio = PortfolioService()
    assert portfolio is not None
    assert portfolio.cash_balance == 100000.0
    assert len(portfolio.get_positions()) == 0


def test_portfolio_service_update_position():
    """Test updating positions."""
    portfolio = PortfolioService()
    
    # Add new position
    pos = portfolio.update_position("AAPL", 100, 150.0, "long")
    assert pos["symbol"] == "AAPL"
    assert pos["quantity"] == 100
    assert pos["avg_entry_price"] == 150.0
    
    # Get position
    pos = portfolio.get_position("AAPL")
    assert pos is not None
    assert pos["symbol"] == "AAPL"


def test_portfolio_service_get_positions():
    """Test getting all positions."""
    portfolio = PortfolioService()
    portfolio.update_position("AAPL", 100, 150.0, "long")
    portfolio.update_position("MSFT", 50, 300.0, "long")
    
    positions = portfolio.get_positions()
    assert len(positions) == 2


def test_portfolio_service_calculate_value():
    """Test portfolio value calculation."""
    portfolio = PortfolioService()
    portfolio.update_position("AAPL", 100, 150.0, "long")
    
    current_prices = {"AAPL": 155.0}
    total_value = portfolio.calculate_portfolio_value(current_prices)
    
    # Should be cash + position value
    assert total_value > portfolio.cash_balance


def test_portfolio_service_get_summary():
    """Test portfolio summary."""
    portfolio = PortfolioService()
    portfolio.update_position("AAPL", 100, 150.0, "long")
    
    current_prices = {"AAPL": 155.0}
    summary = portfolio.get_portfolio_summary(current_prices)
    
    assert "total_value" in summary
    assert "cash_balance" in summary
    assert "unrealized_pnl" in summary
    assert "total_return" in summary


def test_paper_broker_instantiation():
    """Test PaperBroker can be instantiated."""
    broker = PaperBroker()
    assert broker is not None
    assert broker.balance == 100000.0
    assert broker.is_connected() is False


def test_paper_broker_connect_disconnect():
    """Test broker connection."""
    broker = PaperBroker()
    
    # Connect
    result = broker.connect()
    assert result is True
    assert broker.is_connected() is True
    
    # Disconnect
    result = broker.disconnect()
    assert result is True
    assert broker.is_connected() is False


def test_paper_broker_get_account_info():
    """Test getting account info."""
    broker = PaperBroker(starting_balance=50000.0)
    broker.connect()
    
    account = broker.get_account_info()
    assert "cash" in account
    assert "equity" in account
    assert account["cash"] == 50000.0


def test_paper_broker_submit_order():
    """Test submitting an order."""
    broker = PaperBroker()
    broker.connect()
    
    order = broker.submit_order(
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=100,
    )
    
    assert order["symbol"] == "AAPL"
    assert order["side"] == "buy"
    assert order["quantity"] == 100
    assert "id" in order


def test_paper_broker_get_orders():
    """Test getting orders."""
    broker = PaperBroker()
    broker.connect()
    
    # Submit orders
    broker.submit_order("AAPL", OrderSide.BUY, OrderType.MARKET, 100)
    broker.submit_order("MSFT", OrderSide.SELL, OrderType.LIMIT, 50, price=300.0)
    
    orders = broker.get_orders()
    assert len(orders) == 2


def test_paper_broker_cancel_order():
    """Test cancelling an order."""
    broker = PaperBroker()
    broker.connect()
    
    order = broker.submit_order("AAPL", OrderSide.BUY, OrderType.MARKET, 100)
    order_id = order["id"]
    
    result = broker.cancel_order(order_id)
    assert result is True
    
    order = broker.get_order(order_id)
    assert order["status"] == OrderStatus.CANCELLED.value


def test_paper_broker_get_market_data():
    """Test getting market data."""
    broker = PaperBroker()
    broker.connect()
    
    data = broker.get_market_data("AAPL")
    assert "symbol" in data
    assert "price" in data
    assert data["symbol"] == "AAPL"
