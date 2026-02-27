"""
Tests for order execution service and POST /orders endpoint.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
import uuid

from app import app
from storage.database import Base, get_db
from services.broker import OrderSide, OrderType, OrderStatus, PaperBroker
from services.order_execution import (
    OrderExecutionService,
    OrderValidationError,
    BrokerError
)
from storage.service import StorageService
from storage.models import OrderSideEnum, TradeTypeEnum
from services.etf_investing_governance import ETFInvestingGovernanceService

# Create test database - use temporary file that gets cleaned up
import tempfile
import os

_test_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_test_db_path = _test_db_file.name
_test_db_file.close()

SQLALCHEMY_DATABASE_URL = f"sqlite:///{_test_db_path}"
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


client = TestClient(app)


def teardown_module():
    """Clean up test database file after all tests."""
    import os
    if os.path.exists(_test_db_path):
        os.unlink(_test_db_path)


@pytest.fixture(autouse=True)
def reset_broker():
    """Reset broker singleton between tests."""
    from api import routes
    routes._broker_instance = None
    yield
    routes._broker_instance = None


@pytest.fixture(autouse=True)
def setup_database():
    """Create and drop test database for each test."""
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    # Trading gate must be enabled for order endpoint tests unless explicitly
    # overridden. Also reset micro-policy toggles to avoid cross-module config
    # bleed from tests that intentionally enable micro mode.
    client.post(
        "/config",
        json={
            "trading_enabled": True,
            "micro_mode_enabled": False,
            "micro_mode_auto_enabled": True,
            "micro_mode_equity_threshold": 2500.0,
            "micro_mode_single_trade_loss_pct": 1.5,
            "micro_mode_cash_reserve_pct": 5.0,
            "micro_mode_max_spread_bps": 40.0,
            # Keep this suite on generic order-execution pathways.
            "etf_investing_mode_enabled": False,
            "etf_investing_auto_enabled": False,
        },
    )
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.pop(get_db, None)


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
        risk_limit_daily=500.0,
        enable_budget_tracking=False,  # Disable budget tracking for tests
        etf_investing_mode_enabled=False,
        etf_investing_auto_enabled=False,
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


def test_validate_order_micro_single_trade_loss_guardrail(execution_service):
    """Micro policy should block entries that exceed projected single-trade loss cap."""
    execution_service.max_position_size = 1_000_000.0
    execution_service.micro_mode_enabled = True
    execution_service.micro_mode_single_trade_loss_pct = 1.0

    with pytest.raises(OrderValidationError, match="single-trade loss cap"):
        execution_service.validate_order(
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity=1000,  # $100,000 notional -> projected 2% stop-loss = $2,000
        )


def test_validate_order_micro_spread_guardrail(execution_service):
    """Micro policy should block entries with excessive spread."""
    execution_service.max_position_size = 1_000_000.0
    execution_service.micro_mode_enabled = True
    execution_service.micro_mode_max_spread_bps = 20.0
    execution_service.broker.get_market_data = Mock(return_value={
        "price": 100.0,
        "bid": 95.0,
        "ask": 105.0,
        "volume": 100_000,
    })

    with pytest.raises(OrderValidationError, match="spread guardrail"):
        execution_service.validate_order(
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity=1,
        )


def test_validate_order_blocked_when_reconciliation_unresolved(execution_service):
    """Validation must block entries while reconciliation mismatch flag is active."""
    execution_service.storage.set_config_value(
        "broker_reconciliation_blocked_v1",
        "true",
        value_type="bool",
        description="test flag",
    )
    with pytest.raises(OrderValidationError, match="reconciliation mismatch"):
        execution_service.validate_order(
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity=1,
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
    # Note: close_position sets is_open=False but keeps the last quantity for record-keeping
    assert closed_positions[0].is_open is False
    assert closed_positions[0].realized_pnl == 0  # No P&L since buy and sell at same price


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


def test_submit_order_normalizes_uuid_external_id(execution_service):
    """UUID broker order IDs should be stored as strings to avoid sqlite binding errors."""
    broker_uuid = uuid.uuid4()
    execution_service.broker.submit_order = Mock(return_value={
        "id": broker_uuid,
        "status": "filled",
        "filled_quantity": 1.0,
        "avg_fill_price": 100.0,
        "commission": 0.0,
    })

    order = execution_service.submit_order(
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity=1,
    )
    assert isinstance(order.external_id, str)
    assert order.external_id == str(broker_uuid)


def test_update_order_status_processes_only_fill_delta(execution_service):
    """Repeated cumulative fill snapshots should process only the new delta."""
    from storage.models import OrderStatusEnum

    order = execution_service.storage.create_order(
        symbol="AAPL",
        side="buy",
        order_type="limit",
        quantity=10,
        price=99.0,
    )
    order.status = OrderStatusEnum.OPEN
    order.external_id = "ext-delta-1"
    execution_service.storage.orders.update(order)

    execution_service.broker.get_order = Mock(side_effect=[
        {
            "id": "ext-delta-1",
            "status": "partially_filled",
            "filled_quantity": 4.0,
            "avg_fill_price": 100.0,
            "commission": 2.0,
        },
        {
            "id": "ext-delta-1",
            "status": "partially_filled",
            "filled_quantity": 4.0,
            "avg_fill_price": 100.0,
            "commission": 2.0,
        },
        {
            "id": "ext-delta-1",
            "status": "filled",
            "filled_quantity": 10.0,
            "avg_fill_price": 100.0,
            "commission": 5.0,
        },
    ])

    execution_service.update_order_status(order)
    execution_service.update_order_status(order)
    execution_service.update_order_status(order)

    trades = execution_service.storage.get_recent_trades(limit=10)
    quantities = sorted(float(t.quantity) for t in trades)
    commissions = sorted(float(t.commission or 0.0) for t in trades)
    assert quantities == [4.0, 6.0]
    assert commissions == [2.0, 3.0]

    final_order = execution_service.storage.orders.get_by_id(order.id)
    assert final_order is not None
    assert final_order.status.value == "filled"
    assert float(final_order.filled_quantity or 0.0) == 10.0

    position = execution_service.storage.get_position_by_symbol("AAPL")
    assert position is not None
    assert float(position.quantity) == 10.0
    assert float(position.avg_entry_price) == pytest.approx(100.5, rel=1e-6)


def test_update_order_status_rolls_back_on_fill_side_effect_error(execution_service):
    """If fill side-effects fail, status/trade/position changes should roll back together."""
    from storage.models import OrderStatusEnum

    order = execution_service.storage.create_order(
        symbol="MSFT",
        side="buy",
        order_type="limit",
        quantity=5,
        price=250.0,
    )
    order.status = OrderStatusEnum.OPEN
    order.external_id = "ext-rollback-1"
    execution_service.storage.orders.update(order)

    execution_service.broker.get_order = Mock(return_value={
        "id": "ext-rollback-1",
        "status": "partially_filled",
        "filled_quantity": 5.0,
        "avg_fill_price": 250.0,
        "commission": 1.0,
    })
    execution_service.storage.create_audit_log = Mock(side_effect=RuntimeError("audit write failed"))

    execution_service.update_order_status(order)

    reloaded_order = execution_service.storage.orders.get_by_id(order.id)
    assert reloaded_order is not None
    assert reloaded_order.status.value == "open"
    assert float(reloaded_order.filled_quantity or 0.0) == 0.0
    assert execution_service.storage.get_position_by_symbol("MSFT") is None
    assert execution_service.storage.get_recent_trades(limit=10) == []


def test_submit_order_reuses_existing_row_for_duplicate_broker_external_id(execution_service):
    """If broker returns an already-seen external_id, do not process a duplicate fill again."""
    duplicate_response = {
        "id": "ext-duplicate-1",
        "status": "filled",
        "filled_quantity": 2.0,
        "avg_fill_price": 100.0,
        "commission": 0.0,
    }
    execution_service.broker.submit_order = Mock(return_value=duplicate_response)

    first = execution_service.submit_order(
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity=2,
    )
    second = execution_service.submit_order(
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity=2,
    )

    assert second.id == first.id
    trades = execution_service.storage.get_recent_trades(limit=10)
    assert len(trades) == 1

    orders = execution_service.storage.get_recent_orders(limit=10)
    duplicate_rows = [o for o in orders if o.status.value == "rejected" and o.external_id is None]
    live_rows = [o for o in orders if o.external_id == "ext-duplicate-1" and o.status.value == "filled"]
    assert len(duplicate_rows) == 1
    assert len(live_rows) == 1


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


def test_api_create_market_order_with_attached_exits():
    """POST /orders supports optional attached take-profit and stop-loss legs."""
    order_data = {
        "symbol": "AAPL",
        "side": "buy",
        "type": "market",
        "quantity": 2,
        "take_profit_price": 110.0,
        "stop_loss_price": 95.0,
    }

    response = client.post("/orders", json=order_data)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "filled"
    assert isinstance(data.get("attached_order_ids"), list)
    assert len(data.get("attached_order_ids", [])) == 2
    assert data.get("attached_order_warnings") == []

    orders = client.get("/orders")
    assert orders.status_code == 200
    by_id = {str(row["id"]): row for row in orders.json().get("orders", [])}
    for attached_id in data["attached_order_ids"]:
        assert str(attached_id) in by_id
        assert by_id[str(attached_id)]["symbol"] == "AAPL"
        assert by_id[str(attached_id)]["side"] == "sell"


def test_api_rejects_attached_exits_for_sell_orders():
    """Attached exit fields are valid only for buy entries."""
    response = client.post("/orders", json={
        "symbol": "AAPL",
        "side": "sell",
        "type": "market",
        "quantity": 1,
        "take_profit_price": 105.0,
    })
    assert response.status_code == 422


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


def test_api_create_order_blocked_when_trading_disabled():
    """POST /orders should be blocked when global trading is disabled."""
    client.post("/config", json={"trading_enabled": False})
    response = client.post("/orders", json={
        "symbol": "AAPL",
        "side": "buy",
        "type": "market",
        "quantity": 1,
    })
    assert response.status_code == 409
    assert "trading is disabled" in response.json()["detail"].lower()


def test_api_get_orders_returns_persisted_rows_not_stub_payload():
    """GET /orders should return persisted order rows rather than hardcoded stubs."""
    create = client.post("/orders", json={
        "symbol": "AAPL",
        "side": "buy",
        "type": "market",
        "quantity": 2,
    })
    assert create.status_code == 200
    created_id = str(create.json()["id"])

    response = client.get("/orders")
    assert response.status_code == 200
    payload = response.json()
    ids = {str(item["id"]) for item in payload.get("orders", [])}
    assert created_id in ids
    assert "order-001" not in ids


def test_safety_kill_switch_blocks_and_unblocks_order_submission():
    """Kill switch endpoint should block orders until explicitly disabled."""
    enable = client.post("/safety/kill-switch?active=true")
    assert enable.status_code == 200
    assert enable.json().get("kill_switch_active") is True

    blocked = client.post("/orders", json={
        "symbol": "AAPL",
        "side": "buy",
        "type": "market",
        "quantity": 1,
    })
    assert blocked.status_code == 409
    assert "kill switch is active" in str(blocked.json().get("detail", "")).lower()

    status = client.get("/safety/status")
    assert status.status_code == 200
    assert status.json().get("kill_switch_active") is True

    disable = client.post("/safety/kill-switch?active=false")
    assert disable.status_code == 200
    assert disable.json().get("kill_switch_active") is False

    allowed = client.post("/orders", json={
        "symbol": "AAPL",
        "side": "buy",
        "type": "market",
        "quantity": 1,
    })
    assert allowed.status_code == 200


def test_safety_preflight_reports_kill_switch_block_reason():
    """Safety preflight should expose kill-switch block reason without execution."""
    client.post("/safety/kill-switch?active=true")
    response = client.get("/safety/preflight", params={"symbol": "AAPL"})
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("allowed") is False
    assert "kill switch is active" in str(payload.get("reason", "")).lower()
    client.post("/safety/kill-switch?active=false")


def test_oco_group_cancels_sibling_after_first_exit_fill(execution_service):
    """When one OCO sibling fills, the other sibling should be cancelled."""
    # Seed a position to attach exits against.
    entry = execution_service.submit_order(
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity=1,
    )
    assert entry.status.value == "filled"

    take_profit = execution_service.submit_order(
        symbol="AAPL",
        side="sell",
        order_type="limit",
        quantity=1,
        price=95.0,  # market is ~100 so this will fill on next status reconciliation
    )
    stop_loss = execution_service.submit_order(
        symbol="AAPL",
        side="sell",
        order_type="stop",
        quantity=1,
        price=90.0,
    )
    group_id = execution_service.register_oco_group(
        parent_order_id=entry.id,
        symbol="AAPL",
        order_ids=[take_profit.id, stop_loss.id],
    )
    assert group_id is not None

    updated_tp = execution_service.update_order_status(take_profit)
    assert updated_tp.status.value in {"filled", "partially_filled"}

    refreshed_sl = execution_service.storage.orders.get_by_id(stop_loss.id)
    assert refreshed_sl is not None
    assert refreshed_sl.status.value == "cancelled"


def test_validate_order_blocks_wash_sale_rebuy(execution_service, storage_service):
    """ETF investing guard should block same-symbol rebuy inside wash-sale window after a loss sell."""
    execution_service.etf_investing_mode_enabled = True
    execution_service.etf_investing_auto_enabled = False
    execution_service.broker.get_market_data = Mock(return_value={
        "price": 100.0,
        "bid": 99.95,
        "ask": 100.05,
        "volume": 2_000_000,
    })

    order = storage_service.create_order(
        symbol="SPY",
        side="sell",
        order_type="market",
        quantity=1,
        price=100.0,
    )
    loss_trade = storage_service.trades.create(
        order_id=order.id,
        symbol="SPY",
        side=OrderSideEnum.SELL,
        type=TradeTypeEnum.CLOSE,
        quantity=1,
        price=95.0,
        executed_at=datetime.now() - timedelta(days=5),
        auto_commit=False,
    )
    loss_trade.realized_pnl = -5.0
    storage_service.db.commit()

    with pytest.raises(OrderValidationError, match="wash-sale guard"):
        execution_service.validate_order(
            symbol="SPY",
            side="buy",
            order_type="limit",
            quantity=1,
            price=100.0,
        )

    governance_state = ETFInvestingGovernanceService(storage_service).load_state()
    wash_locks = governance_state.get("wash_sale_locks", {})
    assert "SPY" in wash_locks
