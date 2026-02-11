"""
Tests for order execution service and POST /orders endpoint.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime

from app import app
from storage.database import Base, get_db
from services.broker import OrderSide, OrderType, OrderStatus, PaperBroker
from services.order_execution import (
    OrderExecutionService,
    OrderValidationError,
    BrokerError
)
from storage.service import StorageService

# Create test database
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_orders.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Override database dependency for testing."""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    """Create and drop test database for each test."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    """Create a database session for testing."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def paper_broker():
    """Create a paper broker instance for testing."""
    broker = PaperBroker(starting_balance=100000.0)
    broker.connect()
    return broker


@pytest.fixture
def storage_service(db_session):
    """Create a storage service for testing."""
    return StorageService(db_session)


@pytest.fixture
def execution_service(paper_broker, storage_service):
    """Create an order execution service for testing."""
    return OrderExecutionService(
        broker=paper_broker,
        storage=storage_service,
        max_position_size=10000.0,
        risk_limit_daily=500.0
    )


# ============================================================================
# OrderExecutionService Unit Tests
# ============================================================================

def test_validate_order_valid(execution_service):
    """Test validation of a valid order."""
    # Should not raise any exception
    execution_service.validate_order(
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity=10
    )


def test_validate_order_invalid_quantity(execution_service):
    """Test validation fails for invalid quantity."""
    with pytest.raises(OrderValidationError, match="quantity must be positive"):
        execution_service.validate_order(
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity=-10
        )


def test_validate_order_limit_without_price(execution_service):
    """Test validation fails for limit order without price."""
    with pytest.raises(OrderValidationError, match="Price required for limit orders"):
        execution_service.validate_order(
            symbol="AAPL",
            side="buy",
            order_type="limit",
            quantity=10,
            price=None
        )


def test_validate_order_exceeds_position_size(execution_service):
    """Test validation fails when order exceeds max position size."""
    with pytest.raises(OrderValidationError, match="exceeds maximum position size"):
        execution_service.validate_order(
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity=1000,  # 1000 * $100 = $100,000 > $10,000 limit
        )


def test_validate_order_exceeds_buying_power(execution_service):
    """Test validation fails when order exceeds buying power."""
    # Set a very small balance
    execution_service.broker.balance = 100.0
    
    with pytest.raises(OrderValidationError, match="Insufficient buying power"):
        execution_service.validate_order(
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity=10,  # 10 * $100 = $1,000 > $100 balance
        )


def test_submit_market_order_buy(execution_service):
    """Test submitting a market buy order."""
    order = execution_service.submit_order(
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity=10
    )
    
    assert order is not None
    assert order.symbol == "AAPL"
    assert order.side.value == "buy"
    assert order.type.value == "market"
    assert order.quantity == 10
    assert order.status.value == "filled"
    assert order.filled_quantity == 10
    assert order.avg_fill_price == 100.0
    assert order.external_id is not None


def test_submit_market_order_sell(execution_service):
    """Test submitting a market sell order."""
    # First buy to have a position
    execution_service.submit_order(
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity=10
    )
    
    # Then sell
    order = execution_service.submit_order(
        symbol="AAPL",
        side="sell",
        order_type="market",
        quantity=10
    )
    
    assert order is not None
    assert order.symbol == "AAPL"
    assert order.side.value == "sell"
    assert order.status.value == "filled"


def test_submit_limit_order(execution_service):
    """Test submitting a limit order."""
    order = execution_service.submit_order(
        symbol="AAPL",
        side="buy",
        order_type="limit",
        quantity=10,
        price=95.0
    )
    
    assert order is not None
    assert order.symbol == "AAPL"
    assert order.type.value == "limit"
    assert order.price == 95.0
    assert order.status.value == "pending"  # Limit orders stay pending in paper broker


def test_order_creates_trade_and_position(execution_service, db_session):
    """Test that filled order creates trade and position."""
    # Submit order
    order = execution_service.submit_order(
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity=10
    )
    
    # Check that trade was created
    trades = execution_service.storage.get_recent_trades(limit=10)
    assert len(trades) == 1
    assert trades[0].order_id == order.id
    assert trades[0].symbol == "AAPL"
    assert trades[0].quantity == 10
    assert trades[0].price == 100.0
    
    # Check that position was created
    position = execution_service.storage.get_position_by_symbol("AAPL")
    assert position is not None
    assert position.symbol == "AAPL"
    assert position.side.value == "long"
    assert position.quantity == 10
    assert position.avg_entry_price == 100.0
    assert position.is_open is True


def test_order_updates_existing_position(execution_service):
    """Test that subsequent orders update existing position."""
    # First order
    execution_service.submit_order(
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity=10
    )
    
    # Second order
    execution_service.submit_order(
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity=5
    )
    
    # Check position
    position = execution_service.storage.get_position_by_symbol("AAPL")
    assert position.quantity == 15
    assert position.avg_entry_price == 100.0


def test_order_closes_position(execution_service):
    """Test that sell order closes position."""
    # Buy
    execution_service.submit_order(
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity=10
    )
    
    # Sell same amount
    execution_service.submit_order(
        symbol="AAPL",
        side="sell",
        order_type="market",
        quantity=10
    )
    
    # Check position is closed - get_position_by_symbol only returns open positions
    # So closed positions return None
    position = execution_service.storage.get_position_by_symbol("AAPL")
    assert position is None  # Position should be None since it's closed
    
    # Verify position was closed by checking all positions
    all_positions = execution_service.storage.positions.get_all()
    closed_positions = [p for p in all_positions if p.symbol == "AAPL" and not p.is_open]
    assert len(closed_positions) == 1
    assert closed_positions[0].quantity == 0
    assert closed_positions[0].is_open is False


def test_broker_error_marks_order_rejected(execution_service):
    """Test that broker errors mark order as rejected."""
    # Mock broker to raise error
    execution_service.broker.submit_order = Mock(side_effect=Exception("Broker error"))
    
    with pytest.raises(BrokerError):
        execution_service.submit_order(
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity=10
        )
    
    # Check that order was created and marked as rejected
    orders = execution_service.storage.get_recent_orders(limit=10)
    assert len(orders) == 1
    assert orders[0].status.value == "rejected"


# ============================================================================
# POST /orders API Endpoint Tests
# ============================================================================

def test_api_create_market_order_success():
    """Test POST /orders creates a market order successfully."""
    order_data = {
        "symbol": "AAPL",
        "side": "buy",
        "type": "market",
        "quantity": 10
    }
    
    response = client.post("/orders", json=order_data)
    
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "AAPL"
    assert data["side"] == "buy"
    assert data["type"] == "market"
    assert data["quantity"] == 10
    assert data["status"] == "filled"
    assert data["filled_quantity"] == 10
    assert data["avg_fill_price"] == 100.0
    assert "id" in data
    assert "created_at" in data


def test_api_create_limit_order_success():
    """Test POST /orders creates a limit order successfully."""
    order_data = {
        "symbol": "MSFT",
        "side": "buy",
        "type": "limit",
        "quantity": 5,
        "price": 250.0
    }
    
    response = client.post("/orders", json=order_data)
    
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "MSFT"
    assert data["type"] == "limit"
    assert data["price"] == 250.0
    assert data["status"] == "pending"  # Limit orders stay pending


def test_api_create_order_validation_error():
    """Test POST /orders returns 400 for validation errors."""
    order_data = {
        "symbol": "AAPL",
        "side": "buy",
        "type": "market",
        "quantity": -10  # Invalid quantity
    }
    
    response = client.post("/orders", json=order_data)
    
    # Should fail pydantic validation
    assert response.status_code == 422  # Validation error from pydantic


def test_api_create_order_exceeds_position_size():
    """Test POST /orders returns 400 when exceeding position size limit."""
    order_data = {
        "symbol": "AAPL",
        "side": "buy",
        "type": "market",
        "quantity": 1000  # Exceeds $10,000 limit
    }
    
    response = client.post("/orders", json=order_data)
    
    assert response.status_code == 400
    assert "exceeds maximum position size" in response.json()["detail"]


def test_api_create_order_insufficient_buying_power():
    """Test POST /orders returns 400 for insufficient buying power."""
    # Create multiple large orders to deplete balance
    order_data = {
        "symbol": "AAPL",
        "side": "buy",
        "type": "market",
        "quantity": 99  # $9,900
    }
    
    # First 10 orders should succeed
    for _ in range(10):
        response = client.post("/orders", json=order_data)
        assert response.status_code == 200
    
    # 11th order should fail due to insufficient balance
    response = client.post("/orders", json=order_data)
    assert response.status_code == 400
    assert "Insufficient buying power" in response.json()["detail"]


def test_api_create_limit_order_without_price():
    """Test POST /orders returns 400 for limit order without price."""
    order_data = {
        "symbol": "AAPL",
        "side": "buy",
        "type": "limit",
        "quantity": 10
        # price is missing
    }
    
    response = client.post("/orders", json=order_data)
    
    assert response.status_code == 400
    assert "Price required for limit orders" in response.json()["detail"]


def test_api_orders_persist_to_database():
    """Test that orders persist to database."""
    # Create an order
    order_data = {
        "symbol": "AAPL",
        "side": "buy",
        "type": "market",
        "quantity": 10
    }
    
    response = client.post("/orders", json=order_data)
    assert response.status_code == 200
    order_id = response.json()["id"]
    
    # Verify it's in the database by checking with storage service
    db = TestingSessionLocal()
    try:
        storage = StorageService(db)
        orders = storage.get_recent_orders(limit=10)
        assert len(orders) == 1
        assert str(orders[0].id) == order_id
    finally:
        db.close()


def test_api_multiple_orders_create_correct_positions():
    """Test that multiple orders create correct positions."""
    # Buy 10 shares
    client.post("/orders", json={
        "symbol": "AAPL",
        "side": "buy",
        "type": "market",
        "quantity": 10
    })
    
    # Buy 5 more shares
    client.post("/orders", json={
        "symbol": "AAPL",
        "side": "buy",
        "type": "market",
        "quantity": 5
    })
    
    # Sell 3 shares
    client.post("/orders", json={
        "symbol": "AAPL",
        "side": "sell",
        "type": "market",
        "quantity": 3
    })
    
    # Check position
    db = TestingSessionLocal()
    try:
        storage = StorageService(db)
        position = storage.get_position_by_symbol("AAPL")
        assert position is not None
        assert position.quantity == 12  # 10 + 5 - 3
        assert position.is_open is True
    finally:
        db.close()
