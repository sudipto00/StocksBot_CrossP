"""
Tests for storage layer - CRUD operations.
Tests database models, repositories, and storage service.
"""
import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from storage.database import Base
from storage.models import (
    Position, Order, Trade, Strategy, Config,
    PositionSideEnum, OrderSideEnum, OrderTypeEnum, OrderStatusEnum, TradeTypeEnum
)
from storage.repositories import (
    PositionRepository, OrderRepository, TradeRepository,
    StrategyRepository, ConfigRepository
)
from storage.service import StorageService


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
def position_repo(db_session):
    """Create a position repository."""
    return PositionRepository(db_session)


@pytest.fixture
def order_repo(db_session):
    """Create an order repository."""
    return OrderRepository(db_session)


@pytest.fixture
def trade_repo(db_session):
    """Create a trade repository."""
    return TradeRepository(db_session)


@pytest.fixture
def strategy_repo(db_session):
    """Create a strategy repository."""
    return StrategyRepository(db_session)


@pytest.fixture
def config_repo(db_session):
    """Create a config repository."""
    return ConfigRepository(db_session)


@pytest.fixture
def storage_service(db_session):
    """Create a storage service."""
    return StorageService(db_session)


# Position Repository Tests

def test_create_position(position_repo):
    """Test creating a position."""
    position = position_repo.create(
        symbol="AAPL",
        side=PositionSideEnum.LONG,
        quantity=100.0,
        avg_entry_price=150.0,
        cost_basis=15000.0
    )
    assert position.id is not None
    assert position.symbol == "AAPL"
    assert position.quantity == 100.0
    assert position.is_open == True


def test_get_position_by_id(position_repo):
    """Test getting a position by ID."""
    position = position_repo.create(
        symbol="MSFT",
        side=PositionSideEnum.LONG,
        quantity=50.0,
        avg_entry_price=300.0,
        cost_basis=15000.0
    )
    retrieved = position_repo.get_by_id(position.id)
    assert retrieved is not None
    assert retrieved.symbol == "MSFT"


def test_get_position_by_symbol(position_repo):
    """Test getting an open position by symbol."""
    position_repo.create(
        symbol="GOOGL",
        side=PositionSideEnum.LONG,
        quantity=25.0,
        avg_entry_price=2800.0,
        cost_basis=70000.0
    )
    position = position_repo.get_by_symbol("GOOGL", is_open=True)
    assert position is not None
    assert position.symbol == "GOOGL"
    assert position.quantity == 25.0


def test_get_all_open_positions(position_repo):
    """Test getting all open positions."""
    position_repo.create(
        symbol="AAPL", side=PositionSideEnum.LONG,
        quantity=100.0, avg_entry_price=150.0, cost_basis=15000.0
    )
    position_repo.create(
        symbol="MSFT", side=PositionSideEnum.LONG,
        quantity=50.0, avg_entry_price=300.0, cost_basis=15000.0
    )
    positions = position_repo.get_all_open()
    assert len(positions) == 2


def test_close_position(position_repo):
    """Test closing a position."""
    position = position_repo.create(
        symbol="TSLA",
        side=PositionSideEnum.LONG,
        quantity=10.0,
        avg_entry_price=700.0,
        cost_basis=7000.0
    )
    closed = position_repo.close_position(position, realized_pnl=500.0)
    assert closed.is_open == False
    assert closed.realized_pnl == 500.0
    assert closed.closed_at is not None


# Order Repository Tests

def test_create_order(order_repo):
    """Test creating an order."""
    order = order_repo.create(
        symbol="AAPL",
        side=OrderSideEnum.BUY,
        type=OrderTypeEnum.LIMIT,
        quantity=100.0,
        price=150.0
    )
    assert order.id is not None
    assert order.symbol == "AAPL"
    assert order.status == OrderStatusEnum.PENDING


def test_get_order_by_id(order_repo):
    """Test getting an order by ID."""
    order = order_repo.create(
        symbol="MSFT",
        side=OrderSideEnum.BUY,
        type=OrderTypeEnum.MARKET,
        quantity=50.0
    )
    retrieved = order_repo.get_by_id(order.id)
    assert retrieved is not None
    assert retrieved.symbol == "MSFT"


def test_update_order_status(order_repo):
    """Test updating order status."""
    order = order_repo.create(
        symbol="GOOGL",
        side=OrderSideEnum.BUY,
        type=OrderTypeEnum.MARKET,
        quantity=25.0
    )
    updated = order_repo.update_status(
        order,
        OrderStatusEnum.FILLED,
        filled_quantity=25.0,
        avg_fill_price=2800.0
    )
    assert updated.status == OrderStatusEnum.FILLED
    assert updated.filled_quantity == 25.0
    assert updated.filled_at is not None


def test_get_orders_by_status(order_repo):
    """Test getting orders by status."""
    order_repo.create(
        symbol="AAPL", side=OrderSideEnum.BUY,
        type=OrderTypeEnum.MARKET, quantity=100.0
    )
    order_repo.create(
        symbol="MSFT", side=OrderSideEnum.SELL,
        type=OrderTypeEnum.LIMIT, quantity=50.0, price=310.0
    )
    pending_orders = order_repo.get_by_status(OrderStatusEnum.PENDING)
    assert len(pending_orders) == 2


# Trade Repository Tests

def test_create_trade(trade_repo):
    """Test creating a trade."""
    trade = trade_repo.create(
        order_id=1,
        symbol="AAPL",
        side=OrderSideEnum.BUY,
        type=TradeTypeEnum.OPEN,
        quantity=100.0,
        price=150.0,
        commission=1.0
    )
    assert trade.id is not None
    assert trade.symbol == "AAPL"
    assert trade.commission == 1.0


def test_get_trades_by_order(trade_repo):
    """Test getting trades by order ID."""
    trade_repo.create(
        order_id=1, symbol="AAPL", side=OrderSideEnum.BUY,
        type=TradeTypeEnum.OPEN, quantity=50.0, price=150.0
    )
    trade_repo.create(
        order_id=1, symbol="AAPL", side=OrderSideEnum.BUY,
        type=TradeTypeEnum.OPEN, quantity=50.0, price=151.0
    )
    trades = trade_repo.get_by_order_id(1)
    assert len(trades) == 2


# Strategy Repository Tests

def test_create_strategy(strategy_repo):
    """Test creating a strategy."""
    strategy = strategy_repo.create(
        name="Test Strategy",
        strategy_type="momentum",
        config={"param1": "value1", "threshold": 0.5},
        description="A test strategy"
    )
    assert strategy.id is not None
    assert strategy.name == "Test Strategy"
    assert strategy.config["param1"] == "value1"


def test_get_strategy_by_name(strategy_repo):
    """Test getting a strategy by name."""
    strategy_repo.create(
        name="Mean Reversion",
        strategy_type="mean_reversion",
        config={"window": 20}
    )
    strategy = strategy_repo.get_by_name("Mean Reversion")
    assert strategy is not None
    assert strategy.strategy_type == "mean_reversion"


def test_get_active_strategies(strategy_repo):
    """Test getting active strategies."""
    s1 = strategy_repo.create(
        name="Active Strategy",
        strategy_type="momentum",
        config={}
    )
    s1.is_active = True
    strategy_repo.update(s1)
    
    strategy_repo.create(
        name="Inactive Strategy",
        strategy_type="momentum",
        config={}
    )
    
    active = strategy_repo.get_active()
    assert len(active) == 1
    assert active[0].name == "Active Strategy"


# Config Repository Tests

def test_create_config(config_repo):
    """Test creating a config entry."""
    config = config_repo.create(
        key="trading_enabled",
        value="true",
        value_type="bool",
        description="Enable/disable trading"
    )
    assert config.id is not None
    assert config.key == "trading_enabled"


def test_get_config_by_key(config_repo):
    """Test getting config by key."""
    config_repo.create(
        key="max_position_size",
        value="10000",
        value_type="float"
    )
    config = config_repo.get_by_key("max_position_size")
    assert config is not None
    assert config.value == "10000"


def test_upsert_config(config_repo):
    """Test upserting config (create or update)."""
    # Create
    config = config_repo.upsert(
        key="risk_limit",
        value="500",
        value_type="float"
    )
    assert config.value == "500"
    
    # Update
    config = config_repo.upsert(
        key="risk_limit",
        value="1000",
        value_type="float"
    )
    assert config.value == "1000"
    
    # Verify only one entry exists
    all_configs = config_repo.get_all()
    risk_configs = [c for c in all_configs if c.key == "risk_limit"]
    assert len(risk_configs) == 1


# Storage Service Tests

def test_storage_service_create_position(storage_service):
    """Test storage service position creation."""
    position = storage_service.create_position(
        symbol="AAPL",
        side="long",
        quantity=100.0,
        avg_entry_price=150.0
    )
    assert position.symbol == "AAPL"
    assert position.cost_basis == 15000.0


def test_storage_service_get_open_positions(storage_service):
    """Test getting open positions through storage service."""
    storage_service.create_position(
        symbol="AAPL", side="long", quantity=100.0, avg_entry_price=150.0
    )
    storage_service.create_position(
        symbol="MSFT", side="long", quantity=50.0, avg_entry_price=300.0
    )
    positions = storage_service.get_open_positions()
    assert len(positions) == 2


def test_storage_service_create_order(storage_service):
    """Test storage service order creation."""
    order = storage_service.create_order(
        symbol="GOOGL",
        side="buy",
        order_type="market",
        quantity=25.0
    )
    assert order.symbol == "GOOGL"
    assert order.status == OrderStatusEnum.PENDING


def test_storage_service_record_trade(storage_service):
    """Test recording a trade through storage service."""
    # Create an order first
    order = storage_service.create_order(
        symbol="TSLA", side="buy", order_type="market", quantity=10.0
    )
    
    # Record a trade
    trade = storage_service.record_trade(
        order_id=order.id,
        symbol="TSLA",
        side="buy",
        quantity=10.0,
        price=700.0,
        commission=1.0
    )
    assert trade.order_id == order.id
    assert trade.commission == 1.0


def test_storage_service_config(storage_service):
    """Test config operations through storage service."""
    # Set config
    config = storage_service.set_config_value(
        key="trading_enabled",
        value="true",
        value_type="bool"
    )
    assert config.value == "true"
    
    # Get config
    value = storage_service.get_config_value("trading_enabled")
    assert value == "true"
    
    # Get all config
    all_config = storage_service.get_all_config()
    assert "trading_enabled" in all_config
