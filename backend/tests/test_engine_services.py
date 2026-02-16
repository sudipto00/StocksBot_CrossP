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
    broker = PaperBroker()
    runner = StrategyRunner(broker=broker)
    assert runner is not None
    assert runner.status == StrategyStatus.STOPPED
    assert len(runner.strategies) == 0


def test_strategy_runner_load_strategy():
    """Test loading a strategy."""
    from engine.strategy_interface import StrategyInterface
    
    # Create a simple test strategy
    class TestStrategy(StrategyInterface):
        def on_start(self):
            self.is_running = True
        def on_tick(self, market_data):
            return []
        def on_stop(self):
            self.is_running = False
    
    broker = PaperBroker()
    runner = StrategyRunner(broker=broker)
    
    config = {"name": "test-strategy", "symbols": ["AAPL"]}
    strategy = TestStrategy(config)
    result = runner.load_strategy(strategy)
    
    assert result is True
    assert "test-strategy" in runner.strategies


def test_strategy_runner_start_stop():
    """Test starting and stopping strategies."""
    from engine.strategy_interface import StrategyInterface
    
    # Create a simple test strategy
    class TestStrategy(StrategyInterface):
        def on_start(self):
            self.is_running = True
        def on_tick(self, market_data):
            return []
        def on_stop(self):
            self.is_running = False
    
    broker = PaperBroker()
    runner = StrategyRunner(broker=broker, tick_interval=0.1)
    
    config = {"name": "test-strategy", "symbols": ["AAPL"]}
    strategy = TestStrategy(config)
    runner.load_strategy(strategy)
    
    # Start runner
    result = runner.start()
    assert result is True
    assert runner.status == StrategyStatus.RUNNING
    
    # Stop runner
    result = runner.stop()
    assert result is True
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
    assert "max_portfolio_exposure" in metrics
    assert "max_symbol_concentration_pct" in metrics
    assert "max_open_positions" in metrics
    assert "daily_loss_remaining" in metrics


def test_risk_manager_validate_order_exposure_limit():
    """Reject orders that breach portfolio exposure cap."""
    risk_mgr = RiskManager(max_position_size=50_000, max_portfolio_exposure=15_000)
    current_positions = {
        "MSFT": {"market_value": 10_000},
    }
    is_valid, error = risk_mgr.validate_order("AAPL", 60, 100.0, current_positions)  # +$6,000 => $16,000 total
    assert is_valid is False
    assert error is not None
    assert "exposure" in error.lower()


def test_risk_manager_validate_order_symbol_concentration_limit():
    """Reject orders that over-concentrate a single symbol."""
    risk_mgr = RiskManager(max_position_size=50_000, max_symbol_concentration_pct=55.0)
    current_positions = {
        "MSFT": {"market_value": 5_000},
    }
    # Adding $10k AAPL => projected concentration 66.67%
    is_valid, error = risk_mgr.validate_order("AAPL", 100, 100.0, current_positions)
    assert is_valid is False
    assert error is not None
    assert "concentration" in error.lower()


def test_risk_manager_validate_order_max_open_positions():
    """Reject new symbol orders once max open positions is reached."""
    risk_mgr = RiskManager(max_position_size=50_000, max_open_positions=2)
    current_positions = {
        "AAPL": {"market_value": 3_000},
        "MSFT": {"market_value": 3_000},
    }
    is_valid, error = risk_mgr.validate_order("NVDA", 10, 100.0, current_positions)
    assert is_valid is False
    assert error is not None
    assert "max open positions" in error.lower()


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


def test_portfolio_service_prefers_broker_account_snapshot_for_value():
    """Portfolio valuation should use broker account equity/cash when available."""
    broker = PaperBroker(starting_balance=100000.0)
    broker.connect()
    broker.submit_order("AAPL", OrderSide.BUY, OrderType.MARKET, 10)
    account = broker.get_account_info()

    portfolio = PortfolioService(broker=broker)
    total_value = portfolio.calculate_portfolio_value({})
    summary = portfolio.get_portfolio_summary({})

    assert total_value == pytest.approx(account["equity"])
    assert summary["cash_balance"] == pytest.approx(account["cash"])


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


# ============================================================================
# Consecutive Loss Circuit Breaker Tests
# ============================================================================

def test_risk_manager_consecutive_loss_tracking():
    """Test that consecutive losses are tracked correctly."""
    risk_mgr = RiskManager(max_consecutive_losses=3)

    # Record two losses - should not trigger
    risk_mgr.record_trade_result(-50.0)
    assert risk_mgr._consecutive_losses == 1
    assert risk_mgr.circuit_breaker_active is False

    risk_mgr.record_trade_result(-30.0)
    assert risk_mgr._consecutive_losses == 2
    assert risk_mgr.circuit_breaker_active is False

    # Third loss triggers circuit breaker
    risk_mgr.record_trade_result(-20.0)
    assert risk_mgr._consecutive_losses == 3
    assert risk_mgr.circuit_breaker_active is True
    assert "consecutive" in risk_mgr.circuit_breaker_reason.lower()


def test_risk_manager_consecutive_loss_reset_on_win():
    """Test that a winning trade resets the consecutive loss counter."""
    risk_mgr = RiskManager(max_consecutive_losses=3)

    risk_mgr.record_trade_result(-50.0)
    risk_mgr.record_trade_result(-30.0)
    assert risk_mgr._consecutive_losses == 2

    # A win resets the counter
    risk_mgr.record_trade_result(100.0)
    assert risk_mgr._consecutive_losses == 0
    assert risk_mgr.circuit_breaker_active is False


def test_risk_manager_consecutive_loss_deactivate_resets():
    """Deactivating circuit breaker resets the consecutive loss counter."""
    risk_mgr = RiskManager(max_consecutive_losses=2)

    risk_mgr.record_trade_result(-50.0)
    risk_mgr.record_trade_result(-30.0)
    assert risk_mgr.circuit_breaker_active is True

    risk_mgr.deactivate_circuit_breaker()
    assert risk_mgr.circuit_breaker_active is False
    assert risk_mgr._consecutive_losses == 0


# ============================================================================
# Drawdown Kill Switch Tests
# ============================================================================

def test_risk_manager_drawdown_tracking():
    """Test equity drawdown monitoring."""
    risk_mgr = RiskManager(max_drawdown_pct=10.0)

    # Set peak equity
    risk_mgr.update_equity(10000.0)
    assert risk_mgr._peak_equity == 10000.0
    assert risk_mgr.circuit_breaker_active is False

    # Drop 5% - should not trigger
    risk_mgr.update_equity(9500.0)
    assert risk_mgr.circuit_breaker_active is False
    assert risk_mgr._current_drawdown_pct == pytest.approx(5.0)


def test_risk_manager_drawdown_triggers_kill_switch():
    """Test that drawdown beyond threshold triggers circuit breaker."""
    risk_mgr = RiskManager(max_drawdown_pct=10.0)

    risk_mgr.update_equity(10000.0)

    # Drop 10% - should trigger
    risk_mgr.update_equity(9000.0)
    assert risk_mgr.circuit_breaker_active is True
    assert "drawdown" in risk_mgr.circuit_breaker_reason.lower()


def test_risk_manager_drawdown_peak_updates():
    """Peak equity should update when equity rises."""
    risk_mgr = RiskManager(max_drawdown_pct=10.0)

    risk_mgr.update_equity(10000.0)
    assert risk_mgr._peak_equity == 10000.0

    risk_mgr.update_equity(12000.0)
    assert risk_mgr._peak_equity == 12000.0

    # 8.3% drawdown from new peak - should not trigger
    risk_mgr.update_equity(11000.0)
    assert risk_mgr.circuit_breaker_active is False


def test_risk_manager_metrics_include_new_fields():
    """Risk metrics should include consecutive loss and drawdown tracking."""
    risk_mgr = RiskManager(max_consecutive_losses=5, max_drawdown_pct=20.0)
    risk_mgr.record_trade_result(-10.0)
    risk_mgr.record_trade_result(50.0)
    risk_mgr.update_equity(10000.0)

    metrics = risk_mgr.get_risk_metrics()

    assert "consecutive_losses" in metrics
    assert "max_consecutive_losses" in metrics
    assert metrics["max_consecutive_losses"] == 5
    assert "total_wins" in metrics
    assert metrics["total_wins"] == 1
    assert "total_losses" in metrics
    assert metrics["total_losses"] == 1
    assert "peak_equity" in metrics
    assert metrics["peak_equity"] == 10000.0
    assert "current_drawdown_pct" in metrics
    assert "max_drawdown_pct" in metrics
    assert metrics["max_drawdown_pct"] == 20.0


# ============================================================================
# Budget Tracker Tests
# ============================================================================

def test_budget_tracker_basic():
    """Test basic budget tracker functionality."""
    from services.budget_tracker import WeeklyBudgetTracker

    tracker = WeeklyBudgetTracker(weekly_budget=200.0)
    status = tracker.get_budget_status()

    assert status["weekly_budget"] == 200.0
    assert status["used_budget"] == 0.0
    assert status["remaining_budget"] == 200.0
    assert status["trades_this_week"] == 0


def test_budget_tracker_record_trade():
    """Test recording a buy trade uses budget."""
    from services.budget_tracker import WeeklyBudgetTracker

    tracker = WeeklyBudgetTracker(weekly_budget=200.0)
    result = tracker.record_trade(100.0, is_buy=True)
    assert result is True

    status = tracker.get_budget_status()
    assert status["used_budget"] == 100.0
    assert status["remaining_budget"] == 100.0
    assert status["trades_this_week"] == 1


def test_budget_tracker_reinvestment():
    """Test profit reinvestment adds back to available budget."""
    from services.budget_tracker import WeeklyBudgetTracker

    tracker = WeeklyBudgetTracker(
        weekly_budget=200.0,
        reinvest_profits=True,
        reinvest_pct=50.0,
    )

    # Use $150 of budget
    tracker.record_trade(150.0, is_buy=True)
    assert tracker.get_remaining_budget() == pytest.approx(50.0)

    # Record a $40 profit - 50% reinvested = $20 freed up
    tracker.record_trade(0, is_buy=False, realized_pnl=40.0)

    status = tracker.get_budget_status()
    assert status["reinvested_amount"] == pytest.approx(20.0)
    # Remaining should be 50 + 20 = 70
    assert status["remaining_budget"] == pytest.approx(70.0)


def test_budget_tracker_no_reinvestment_on_loss():
    """Losses should not trigger reinvestment."""
    from services.budget_tracker import WeeklyBudgetTracker

    tracker = WeeklyBudgetTracker(
        weekly_budget=200.0,
        reinvest_profits=True,
        reinvest_pct=50.0,
    )

    tracker.record_trade(100.0, is_buy=True)
    tracker.record_trade(0, is_buy=False, realized_pnl=-30.0)

    status = tracker.get_budget_status()
    assert status["reinvested_amount"] == 0.0
    assert status["weekly_pnl"] == -30.0


def test_budget_tracker_can_trade():
    """Test budget limit enforcement."""
    from services.budget_tracker import WeeklyBudgetTracker

    tracker = WeeklyBudgetTracker(weekly_budget=100.0)

    can, _ = tracker.can_trade(80.0)
    assert can is True

    tracker.record_trade(80.0, is_buy=True)

    can, reason = tracker.can_trade(50.0)
    assert can is False
    assert "budget" in reason.lower()


def test_budget_tracker_status_fields():
    """Budget status should include all compounding/scaling fields."""
    from services.budget_tracker import WeeklyBudgetTracker

    tracker = WeeklyBudgetTracker(
        weekly_budget=50.0,
        reinvest_profits=True,
        reinvest_pct=40.0,
        auto_scale_budget=True,
        auto_scale_pct=10.0,
    )
    status = tracker.get_budget_status()

    assert "base_weekly_budget" in status
    assert status["base_weekly_budget"] == 50.0
    assert "reinvest_profits" in status
    assert status["reinvest_profits"] is True
    assert "reinvest_pct" in status
    assert status["reinvest_pct"] == 40.0
    assert "auto_scale_budget" in status
    assert status["auto_scale_budget"] is True
    assert "auto_scale_pct" in status
    assert status["auto_scale_pct"] == 10.0
    assert "cumulative_pnl" in status
    assert "consecutive_profitable_weeks" in status
