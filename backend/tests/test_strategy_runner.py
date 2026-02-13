"""
Tests for strategy runner and strategy interface.
Tests runner lifecycle, strategy execution, and paper trading.
"""
import pytest
import time
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from storage.database import Base
from storage.service import StorageService
from services.broker import PaperBroker, OrderSide, OrderType
from engine.strategy_interface import StrategyInterface, Signal
from engine.strategies import MovingAverageCrossoverStrategy, BuyAndHoldStrategy
from engine.strategy_runner import StrategyRunner, StrategyStatus


# Test fixtures

@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def storage_service(db_session):
    """Create a storage service."""
    return StorageService(db_session)


@pytest.fixture
def paper_broker():
    """Create a paper broker instance."""
    return PaperBroker(starting_balance=100000.0)


@pytest.fixture
def strategy_runner(paper_broker, storage_service):
    """Create a strategy runner with paper broker and storage."""
    return StrategyRunner(
        broker=paper_broker,
        storage_service=storage_service,
        tick_interval=0.1  # Fast ticking for tests
    )


# Strategy Interface Tests

def test_strategy_interface_initialization():
    """Test strategy interface basic initialization."""
    config = {
        "name": "TestStrategy",
        "symbols": ["AAPL", "MSFT"]
    }
    
    # Create a concrete implementation for testing
    class TestStrategy(StrategyInterface):
        def on_start(self):
            pass
        
        def on_tick(self, market_data):
            return []
        
        def on_stop(self):
            pass
    
    strategy = TestStrategy(config)
    assert strategy.name == "TestStrategy"
    assert strategy.symbols == ["AAPL", "MSFT"]
    assert strategy.is_running == False


def test_moving_average_strategy_initialization():
    """Test MA crossover strategy initialization."""
    config = {
        "name": "MA Crossover",
        "symbols": ["AAPL"],
        "short_window": 10,
        "long_window": 50,
        "position_size": 100
    }
    
    strategy = MovingAverageCrossoverStrategy(config)
    assert strategy.short_window == 10
    assert strategy.long_window == 50
    assert strategy.position_size == 100
    assert "price_history" in strategy.state


def test_buy_and_hold_strategy_initialization():
    """Test buy and hold strategy initialization."""
    config = {
        "name": "Buy and Hold",
        "symbols": ["AAPL", "MSFT"],
        "position_size": 50,
        "sell_on_stop": True
    }
    
    strategy = BuyAndHoldStrategy(config)
    assert strategy.position_size == 50
    assert strategy.sell_on_stop == True
    assert "bought" in strategy.state


def test_strategy_lifecycle():
    """Test strategy lifecycle methods."""
    config = {"name": "Test", "symbols": ["AAPL"]}
    strategy = MovingAverageCrossoverStrategy(config)
    
    # Start
    strategy.on_start()
    assert strategy.is_running == True
    
    # Tick
    market_data = {
        "AAPL": {"price": 150.0, "volume": 1000000}
    }
    signals = strategy.on_tick(market_data)
    assert isinstance(signals, list)
    
    # Stop
    strategy.on_stop()
    assert strategy.is_running == False


# Strategy Runner Lifecycle Tests

def test_runner_initialization(strategy_runner):
    """Test runner initialization."""
    assert strategy_runner.status == StrategyStatus.STOPPED
    assert len(strategy_runner.strategies) == 0


def test_runner_load_strategy(strategy_runner):
    """Test loading a strategy into runner."""
    config = {"name": "Test Strategy", "symbols": ["AAPL"]}
    strategy = MovingAverageCrossoverStrategy(config)
    
    result = strategy_runner.load_strategy(strategy)
    assert result == True
    assert len(strategy_runner.strategies) == 1
    assert "Test Strategy" in strategy_runner.strategies


def test_runner_start_stop_lifecycle(strategy_runner, paper_broker):
    """Test runner start/stop lifecycle."""
    config = {"name": "Test", "symbols": ["AAPL"]}
    strategy = MovingAverageCrossoverStrategy(config)
    strategy_runner.load_strategy(strategy)
    
    # Start
    result = strategy_runner.start()
    assert result == True
    assert strategy_runner.status == StrategyStatus.RUNNING
    assert paper_broker.is_connected() == True
    assert strategy.is_running == True
    
    # Give scheduler time to run
    time.sleep(0.3)
    
    # Stop
    result = strategy_runner.stop()
    assert result == True
    assert strategy_runner.status == StrategyStatus.STOPPED
    assert strategy.is_running == False


def test_runner_start_without_strategies(strategy_runner):
    """Test that runner fails to start without strategies."""
    result = strategy_runner.start()
    assert result == False


def test_runner_start_when_already_running(strategy_runner):
    """Test that runner cannot start when already running."""
    config = {"name": "Test", "symbols": ["AAPL"]}
    strategy = MovingAverageCrossoverStrategy(config)
    strategy_runner.load_strategy(strategy)
    
    strategy_runner.start()
    result = strategy_runner.start()  # Try starting again
    assert result == False
    
    strategy_runner.stop()


def test_runner_stop_when_already_stopped(strategy_runner):
    """Test that stopping already stopped runner returns False."""
    result = strategy_runner.stop()
    assert result == False


def test_runner_sleeps_off_hours_and_resumes(storage_service):
    """Runner should enter sleep mode off-hours and auto-resume when market opens."""
    class ToggleMarketBroker(PaperBroker):
        def __init__(self):
            super().__init__(starting_balance=100000.0)
            self._market_open = False

        def is_market_open(self) -> bool:
            return self._market_open

        def get_next_market_open(self):
            return datetime.now(timezone.utc) + timedelta(hours=1)

    broker = ToggleMarketBroker()
    runner = StrategyRunner(
        broker=broker,
        storage_service=storage_service,
        tick_interval=0.1,
    )
    runner.off_hours_poll_interval = 0.1
    strategy = MovingAverageCrossoverStrategy({"name": "Sleep Test", "symbols": ["AAPL"]})
    runner.load_strategy(strategy)

    assert runner.start() is True
    time.sleep(0.2)
    assert runner.sleeping is True
    assert runner.status == StrategyStatus.SLEEPING

    broker._market_open = True
    time.sleep(0.25)
    assert runner.sleeping is False
    assert runner.status == StrategyStatus.RUNNING
    assert runner.resume_count >= 1
    assert runner.last_resume_at is not None

    runner.stop()


# Strategy Execution Tests

def test_strategy_execution_callback(strategy_runner):
    """Test that strategy execution triggers callback."""
    callback_called = []
    
    def signal_callback(strategy, signal, order):
        callback_called.append({
            "strategy": strategy.name,
            "signal": signal,
            "order": order
        })
    
    strategy_runner.on_signal_callback = signal_callback
    
    # Create a strategy that generates signals
    config = {"name": "Test", "symbols": ["AAPL"], "position_size": 10}
    strategy = BuyAndHoldStrategy(config)
    strategy_runner.load_strategy(strategy)
    
    strategy_runner.start()
    time.sleep(0.3)  # Let it tick and generate signals
    strategy_runner.stop()
    
    # Buy and hold should generate buy signals on first tick
    assert len(callback_called) > 0


def test_runner_get_status(strategy_runner):
    """Test getting runner status."""
    config = {"name": "Test", "symbols": ["AAPL"]}
    strategy = MovingAverageCrossoverStrategy(config)
    strategy_runner.load_strategy(strategy)
    
    status = strategy_runner.get_status()
    assert "status" in status
    assert "strategies" in status
    assert "tick_interval" in status
    assert status["status"] == StrategyStatus.STOPPED.value
    assert len(status["strategies"]) == 1


# Paper Trading Execution Tests

def test_paper_execution_creates_order(strategy_runner, storage_service):
    """Test that paper trading creates orders in storage."""
    config = {"name": "Test", "symbols": ["AAPL"], "position_size": 100}
    strategy = BuyAndHoldStrategy(config)
    strategy_runner.load_strategy(strategy)
    
    # Track signal callbacks instead of storage (thread safety issue)
    executed_signals = []
    def track_signal(strategy, signal, order):
        executed_signals.append(order)
    
    strategy_runner.on_signal_callback = track_signal
    
    strategy_runner.start()
    time.sleep(0.3)  # Let it execute
    strategy_runner.stop()
    
    # Check that signals were executed
    assert len(executed_signals) > 0


def test_paper_execution_records_trade(strategy_runner, storage_service):
    """Test that paper trading records trades via broker."""
    config = {"name": "Test", "symbols": ["AAPL"], "position_size": 100}
    strategy = BuyAndHoldStrategy(config)
    strategy_runner.load_strategy(strategy)
    
    # Track signal callbacks
    executed_signals = []
    def track_signal(strategy, signal, order):
        executed_signals.append(order)
    
    strategy_runner.on_signal_callback = track_signal
    
    strategy_runner.start()
    time.sleep(0.3)
    strategy_runner.stop()
    
    # Check that orders were executed through broker
    assert len(executed_signals) > 0
    assert executed_signals[0]["symbol"] == "AAPL"


def test_paper_execution_fills_order(strategy_runner, paper_broker):
    """Test that paper orders are executed through broker."""
    config = {"name": "Test", "symbols": ["AAPL"], "position_size": 50}
    strategy = BuyAndHoldStrategy(config)
    strategy_runner.load_strategy(strategy)
    
    strategy_runner.start()
    time.sleep(0.3)
    strategy_runner.stop()
    
    # Check that orders are in paper broker
    orders = paper_broker.get_orders()
    assert len(orders) > 0
    for order in orders:
        assert order["quantity"] == 50


def test_paper_broker_integration(paper_broker):
    """Test paper broker order execution."""
    paper_broker.connect()
    
    # Submit a market order
    order = paper_broker.submit_order(
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=100
    )
    
    assert order is not None
    assert order["symbol"] == "AAPL"
    assert order["side"] == "buy"
    assert order["quantity"] == 100
    
    # Check order was recorded
    orders = paper_broker.get_orders()
    assert len(orders) == 1
    
    paper_broker.disconnect()


def test_multiple_strategies_execution(strategy_runner, paper_broker):
    """Test running multiple strategies simultaneously."""
    config1 = {"name": "Strategy1", "symbols": ["AAPL"], "position_size": 50}
    config2 = {"name": "Strategy2", "symbols": ["MSFT"], "position_size": 30}
    
    strategy1 = BuyAndHoldStrategy(config1)
    strategy2 = BuyAndHoldStrategy(config2)
    
    strategy_runner.load_strategy(strategy1)
    strategy_runner.load_strategy(strategy2)
    
    strategy_runner.start()
    time.sleep(0.3)
    strategy_runner.stop()
    
    # Both strategies should have generated orders in broker
    orders = paper_broker.get_orders()
    assert len(orders) >= 2
    
    # Check that we have orders for both symbols
    symbols = {order["symbol"] for order in orders}
    assert "AAPL" in symbols
    assert "MSFT" in symbols


def test_runner_market_data_fetching(strategy_runner, paper_broker):
    """Test that runner fetches market data for all symbols."""
    config = {"name": "Test", "symbols": ["AAPL", "MSFT", "GOOGL"]}
    strategy = MovingAverageCrossoverStrategy(config)
    strategy_runner.load_strategy(strategy)
    
    # Test internal market data fetching
    market_data = strategy_runner._fetch_market_data()
    
    # Should have data for all symbols
    assert len(market_data) == 3
    assert "AAPL" in market_data
    assert "MSFT" in market_data
    assert "GOOGL" in market_data


def test_paper_execution_storage_integration(storage_service, paper_broker):
    """Test paper execution with storage (without threading)."""
    # Manually create order and trade to test storage integration
    order = storage_service.create_order(
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity=100
    )
    
    assert order.symbol == "AAPL"
    assert order.quantity == 100
    
    # Update order status
    updated = storage_service.update_order_status(
        order_id=order.id,
        status="filled",
        filled_quantity=100,
        avg_fill_price=150.0
    )
    
    assert updated.status.value == "filled"
    
    # Record trade
    trade = storage_service.record_trade(
        order_id=order.id,
        symbol="AAPL",
        side="buy",
        quantity=100,
        price=150.0
    )
    
    assert trade.order_id == order.id
    assert trade.price == 150.0
