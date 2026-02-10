"""
Tests for strategy configuration, metrics, backtesting, and tuning endpoints.
"""
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app import app
from storage.database import Base, get_db
from storage.service import StorageService


# Create test database
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_strategy_features.db"
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
def test_strategy():
    """Create a test strategy for testing."""
    db = TestingSessionLocal()
    try:
        storage = StorageService(db)
        strategy = storage.strategies.create(
            name="Test Strategy",
            strategy_type="custom",
            config={
                "symbols": ["AAPL", "MSFT"],
                "parameters": {
                    "position_size": 1000.0,
                    "stop_loss_pct": 2.0,
                }
            },
            description="Test strategy for unit tests",
        )
        db.commit()
        # Return the ID instead of the object to avoid detached instance errors
        strategy_id = strategy.id
        return type('obj', (object,), {'id': strategy_id})()
    finally:
        db.close()


class TestStrategyConfiguration:
    """Tests for strategy configuration endpoints."""
    
    def test_get_strategy_config(self, test_strategy):
        """Test getting strategy configuration."""
        response = client.get(f"/strategies/{test_strategy.id}/config")
        assert response.status_code == 200
        
        data = response.json()
        assert data["strategy_id"] == str(test_strategy.id)
        assert data["name"] == "Test Strategy"
        assert "AAPL" in data["symbols"]
        assert "MSFT" in data["symbols"]
        assert len(data["parameters"]) > 0
    
    def test_get_strategy_config_not_found(self):
        """Test getting config for non-existent strategy."""
        response = client.get("/strategies/99999/config")
        assert response.status_code == 404
    
    def test_update_strategy_config_symbols(self, test_strategy):
        """Test updating strategy symbols."""
        response = client.put(
            f"/strategies/{test_strategy.id}/config",
            json={"symbols": ["TSLA", "GOOGL", "AMZN"]}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert "TSLA" in data["symbols"]
        assert "GOOGL" in data["symbols"]
        assert "AMZN" in data["symbols"]
    
    def test_update_strategy_config_parameters(self, test_strategy):
        """Test updating strategy parameters."""
        response = client.put(
            f"/strategies/{test_strategy.id}/config",
            json={"parameters": {"position_size": 2000.0, "stop_loss_pct": 3.5}}
        )
        assert response.status_code == 200
        
        # Verify parameters were updated
        config_response = client.get(f"/strategies/{test_strategy.id}/config")
        config = config_response.json()
        
        position_size_param = next(
            p for p in config["parameters"] if p["name"] == "position_size"
        )
        assert position_size_param["value"] == 2000.0
    
    def test_update_strategy_config_enabled(self, test_strategy):
        """Test enabling/disabling strategy."""
        response = client.put(
            f"/strategies/{test_strategy.id}/config",
            json={"enabled": False}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["enabled"] is False


class TestStrategyMetrics:
    """Tests for strategy metrics endpoints."""
    
    def test_get_strategy_metrics_no_trades(self, test_strategy):
        """Test getting metrics for strategy with no trades."""
        response = client.get(f"/strategies/{test_strategy.id}/metrics")
        assert response.status_code == 200
        
        data = response.json()
        assert data["strategy_id"] == str(test_strategy.id)
        assert data["win_rate"] == 0.0
        assert data["volatility"] == 0.0
        assert data["drawdown"] == 0.0
        assert data["total_trades"] == 0
    
    def test_get_strategy_metrics_not_found(self):
        """Test getting metrics for non-existent strategy."""
        response = client.get("/strategies/99999/metrics")
        assert response.status_code == 404
    
    def test_get_strategy_metrics_structure(self, test_strategy):
        """Test metrics response structure."""
        response = client.get(f"/strategies/{test_strategy.id}/metrics")
        assert response.status_code == 200
        
        data = response.json()
        assert "win_rate" in data
        assert "volatility" in data
        assert "drawdown" in data
        assert "total_trades" in data
        assert "winning_trades" in data
        assert "losing_trades" in data
        assert "total_pnl" in data
        assert "updated_at" in data


class TestStrategyBacktesting:
    """Tests for strategy backtesting endpoints."""
    
    def test_run_backtest(self, test_strategy):
        """Test running a backtest."""
        start_date = (datetime.now() - timedelta(days=90)).date().isoformat()
        end_date = datetime.now().date().isoformat()
        
        response = client.post(
            f"/strategies/{test_strategy.id}/backtest",
            json={
                "start_date": start_date,
                "end_date": end_date,
                "initial_capital": 100000.0,
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["strategy_id"] == str(test_strategy.id)
        assert data["start_date"] == start_date
        assert data["end_date"] == end_date
        assert data["initial_capital"] == 100000.0
        assert "final_capital" in data
        assert "total_return" in data
        assert "win_rate" in data
        assert "max_drawdown" in data
        assert "sharpe_ratio" in data
        assert "trades" in data
        assert "equity_curve" in data
    
    def test_run_backtest_with_custom_capital(self, test_strategy):
        """Test backtest with custom initial capital."""
        response = client.post(
            f"/strategies/{test_strategy.id}/backtest",
            json={
                "start_date": "2024-01-01",
                "end_date": "2024-06-30",
                "initial_capital": 50000.0,
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["initial_capital"] == 50000.0
    
    def test_run_backtest_not_found(self):
        """Test backtest for non-existent strategy."""
        response = client.post(
            "/strategies/99999/backtest",
            json={
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
            }
        )
        assert response.status_code == 404
    
    def test_backtest_results_structure(self, test_strategy):
        """Test backtest results have correct structure."""
        response = client.post(
            f"/strategies/{test_strategy.id}/backtest",
            json={
                "start_date": "2024-01-01",
                "end_date": "2024-03-31",
                "initial_capital": 100000.0,
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        # Check equity curve structure
        assert isinstance(data["equity_curve"], list)
        if len(data["equity_curve"]) > 0:
            curve_point = data["equity_curve"][0]
            assert "timestamp" in curve_point
            assert "equity" in curve_point
        
        # Check trades structure
        assert isinstance(data["trades"], list)
        if len(data["trades"]) > 0:
            trade = data["trades"][0]
            assert "symbol" in trade
            assert "pnl" in trade


class TestParameterTuning:
    """Tests for parameter tuning endpoints."""
    
    def test_tune_parameter(self, test_strategy):
        """Test tuning a parameter."""
        response = client.post(
            f"/strategies/{test_strategy.id}/tune",
            json={
                "parameter_name": "position_size",
                "value": 1500.0,
            }
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["strategy_id"] == str(test_strategy.id)
        assert data["parameter_name"] == "position_size"
        assert data["new_value"] == 1500.0
        assert data["success"] is True
    
    def test_tune_parameter_validation(self, test_strategy):
        """Test parameter tuning with invalid value."""
        # Try to set value outside allowed range
        response = client.post(
            f"/strategies/{test_strategy.id}/tune",
            json={
                "parameter_name": "position_size",
                "value": 99999.0,  # Exceeds max_value
            }
        )
        assert response.status_code == 400
    
    def test_tune_unknown_parameter(self, test_strategy):
        """Test tuning unknown parameter."""
        response = client.post(
            f"/strategies/{test_strategy.id}/tune",
            json={
                "parameter_name": "unknown_param",
                "value": 100.0,
            }
        )
        assert response.status_code == 400
    
    def test_tune_parameter_not_found(self):
        """Test tuning for non-existent strategy."""
        response = client.post(
            "/strategies/99999/tune",
            json={
                "parameter_name": "position_size",
                "value": 1500.0,
            }
        )
        assert response.status_code == 404
    
    def test_tune_multiple_parameters(self, test_strategy):
        """Test tuning multiple parameters sequentially."""
        # Tune first parameter
        response1 = client.post(
            f"/strategies/{test_strategy.id}/tune",
            json={
                "parameter_name": "position_size",
                "value": 1500.0,
            }
        )
        assert response1.status_code == 200
        
        # Tune second parameter
        response2 = client.post(
            f"/strategies/{test_strategy.id}/tune",
            json={
                "parameter_name": "stop_loss_pct",
                "value": 3.0,
            }
        )
        assert response2.status_code == 200
        
        # Verify both parameters were updated
        config_response = client.get(f"/strategies/{test_strategy.id}/config")
        config = config_response.json()
        
        position_size = next(
            p for p in config["parameters"] if p["name"] == "position_size"
        )
        stop_loss = next(
            p for p in config["parameters"] if p["name"] == "stop_loss_pct"
        )
        
        assert position_size["value"] == 1500.0
        assert stop_loss["value"] == 3.0
