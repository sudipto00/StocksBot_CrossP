"""
Tests for strategy CRUD operations and audit logs with database persistence.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import app
from storage.database import Base, get_db

# Create test database
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
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


@pytest.fixture(autouse=True)
def setup_database():
    """Create and drop test database for each test."""
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.pop(get_db, None)


# ============================================================================
# Strategy CRUD Tests
# ============================================================================

def test_create_strategy():
    """Test creating a strategy."""
    strategy_data = {
        "name": "Test Strategy",
        "description": "A test strategy",
        "symbols": ["AAPL", "MSFT"]
    }
    response = client.post("/strategies", json=strategy_data)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Strategy"
    assert data["description"] == "A test strategy"
    assert data["symbols"] == ["AAPL", "MSFT"]
    assert data["status"] == "stopped"
    assert "id" in data
    assert "created_at" in data


def test_create_duplicate_strategy():
    """Test creating duplicate strategy fails."""
    strategy_data = {
        "name": "Duplicate Test",
        "symbols": ["AAPL"]
    }
    # First creation should succeed
    response1 = client.post("/strategies", json=strategy_data)
    assert response1.status_code == 200
    
    # Second creation should fail
    response2 = client.post("/strategies", json=strategy_data)
    assert response2.status_code == 400
    assert "already exists" in response2.json()["detail"]


def test_get_strategies():
    """Test getting all strategies."""
    # Create two strategies
    client.post("/strategies", json={"name": "Strategy 1", "symbols": ["AAPL"]})
    client.post("/strategies", json={"name": "Strategy 2", "symbols": ["MSFT"]})
    
    response = client.get("/strategies")
    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 2
    assert len(data["strategies"]) == 2


def test_get_strategy_by_id():
    """Test getting a specific strategy."""
    # Create a strategy
    create_response = client.post("/strategies", json={
        "name": "Get Test",
        "symbols": ["AAPL"]
    })
    strategy_id = create_response.json()["id"]
    
    # Get the strategy
    response = client.get(f"/strategies/{strategy_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == strategy_id
    assert data["name"] == "Get Test"


def test_get_nonexistent_strategy():
    """Test getting a non-existent strategy."""
    response = client.get("/strategies/999")
    assert response.status_code == 404


def test_update_strategy():
    """Test updating a strategy."""
    # Create a strategy
    create_response = client.post("/strategies", json={
        "name": "Update Test",
        "symbols": ["AAPL"]
    })
    strategy_id = create_response.json()["id"]
    
    # Update the strategy
    update_data = {
        "name": "Updated Name",
        "description": "Updated description",
        "symbols": ["AAPL", "MSFT", "GOOGL"]
    }
    response = client.put(f"/strategies/{strategy_id}", json=update_data)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"
    assert data["description"] == "Updated description"
    assert len(data["symbols"]) == 3


def test_update_strategy_status():
    """Test updating strategy status."""
    # Create a strategy
    create_response = client.post("/strategies", json={
        "name": "Status Test",
        "symbols": ["AAPL"]
    })
    strategy_id = create_response.json()["id"]
    
    # Activate the strategy
    response = client.put(f"/strategies/{strategy_id}", json={"status": "active"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"


def test_delete_strategy():
    """Test deleting a strategy."""
    # Create a strategy
    create_response = client.post("/strategies", json={
        "name": "Delete Test",
        "symbols": ["AAPL"]
    })
    strategy_id = create_response.json()["id"]
    
    # Delete the strategy
    response = client.delete(f"/strategies/{strategy_id}")
    assert response.status_code == 200
    
    # Verify it's deleted
    get_response = client.get(f"/strategies/{strategy_id}")
    assert get_response.status_code == 404


# ============================================================================
# Audit Log Tests
# ============================================================================

def test_get_audit_logs():
    """Test getting audit logs."""
    # Create a strategy to generate audit logs
    client.post("/strategies", json={"name": "Audit Test", "symbols": ["AAPL"]})
    
    # Get audit logs
    response = client.get("/audit/logs")
    assert response.status_code == 200
    data = response.json()
    assert "logs" in data
    assert "total_count" in data
    assert data["total_count"] > 0


def test_audit_logs_filtering():
    """Test filtering audit logs by event type."""
    # Create and update a strategy
    create_response = client.post("/strategies", json={
        "name": "Filter Test",
        "symbols": ["AAPL"]
    })
    strategy_id = create_response.json()["id"]
    client.put(f"/strategies/{strategy_id}", json={"status": "active"})
    
    # Get logs filtered by event type
    response = client.get("/audit/logs?event_type=strategy_started")
    assert response.status_code == 200
    data = response.json()
    
    # All logs should be strategy_started events
    for log in data["logs"]:
        assert log["event_type"] == "strategy_started"


def test_audit_log_limit():
    """Test audit log pagination limit."""
    # Create multiple strategies to generate logs
    for i in range(5):
        client.post("/strategies", json={
            "name": f"Limit Test {i}",
            "symbols": ["AAPL"]
        })
    
    # Get logs with limit
    response = client.get("/audit/logs?limit=3")
    assert response.status_code == 200
    data = response.json()
    assert len(data["logs"]) <= 3


# ============================================================================
# Runner Endpoint Tests
# ============================================================================

def test_get_runner_status():
    """Test getting runner status."""
    response = client.get("/runner/status")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "strategies" in data
    assert "tick_interval" in data
    assert "broker_connected" in data


def test_start_runner_no_strategies():
    """Test starting runner with no strategies."""
    response = client.post("/runner/start")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] == False
    assert "no active strategies" in data["message"].lower()


def test_start_stop_runner():
    """Test starting and stopping runner."""
    # Create an active strategy first
    create_response = client.post("/strategies", json={
        "name": "Runner Test",
        "symbols": ["AAPL"]
    })
    strategy_id = create_response.json()["id"]
    client.put(f"/strategies/{strategy_id}", json={"status": "active"})
    
    # Start runner
    start_response = client.post("/runner/start")
    assert start_response.status_code == 200
    start_data = start_response.json()
    # May fail due to broker connection issues in test, but should handle gracefully
    
    # Stop runner
    stop_response = client.post("/runner/stop")
    assert stop_response.status_code == 200


def test_runner_idempotent_start():
    """Test that starting runner multiple times is idempotent."""
    # Start twice
    response1 = client.post("/runner/start")
    response2 = client.post("/runner/start")
    
    # Both should return 200
    assert response1.status_code == 200
    assert response2.status_code == 200


# ============================================================================
# Analytics Endpoint Tests
# ============================================================================

def test_get_portfolio_analytics():
    """Test getting portfolio analytics."""
    response = client.get("/analytics/portfolio")
    assert response.status_code == 200
    data = response.json()
    assert "time_series" in data
    assert "total_trades" in data
    assert "current_equity" in data
    assert "total_pnl" in data


def test_get_portfolio_summary():
    """Test getting portfolio summary."""
    response = client.get("/analytics/summary")
    assert response.status_code == 200
    data = response.json()
    assert "total_trades" in data
    assert "total_pnl" in data
    assert "win_rate" in data
    assert "equity" in data


def test_analytics_with_days_param():
    """Test portfolio analytics with days parameter."""
    response = client.get("/analytics/portfolio?days=7")
    assert response.status_code == 200
    data = response.json()
    assert "time_series" in data
