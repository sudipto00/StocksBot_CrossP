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


client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    """Create and drop test database for each test."""
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.pop(get_db, None)


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

    def test_update_strategy_config_disable_auto_stops_active(self, test_strategy):
        """Disabling config should also stop an active strategy."""
        activate = client.put(
            f"/strategies/{test_strategy.id}",
            json={"status": "active"},
        )
        assert activate.status_code == 200
        assert activate.json()["status"] == "active"

        disable = client.put(
            f"/strategies/{test_strategy.id}/config",
            json={"enabled": False},
        )
        assert disable.status_code == 200
        assert disable.json()["enabled"] is False

        strategy = client.get(f"/strategies/{test_strategy.id}")
        assert strategy.status_code == 200
        assert strategy.json()["status"] == "stopped"

    def test_get_strategy_config_uses_adaptive_defaults_when_missing_params(self):
        """Config response should provide adaptive defaults for unset parameters."""
        prefs = client.post(
            "/preferences",
            json={
                "asset_type": "stock",
                "screener_mode": "preset",
                "stock_preset": "weekly_optimized",
                "weekly_budget": 200.0,
            },
        )
        assert prefs.status_code == 200

        create = client.post(
            "/strategies",
            json={
                "name": "Adaptive Defaults Strategy",
                "symbols": ["AAPL", "MSFT"],
            },
        )
        assert create.status_code == 200
        strategy_id = create.json()["id"]

        response = client.get(f"/strategies/{strategy_id}/config")
        assert response.status_code == 200
        data = response.json()
        position_size = next(
            p["value"] for p in data["parameters"] if p["name"] == "position_size"
        )
        risk_per_trade = next(
            p["value"] for p in data["parameters"] if p["name"] == "risk_per_trade"
        )
        # weekly_optimized preset defaults to 1200 position size.
        assert position_size <= 1200.0
        assert risk_per_trade >= 0.1
        # Verify max_hold_days is present in defaults.
        max_hold_days = next(
            (p["value"] for p in data["parameters"] if p["name"] == "max_hold_days"),
            None,
        )
        assert max_hold_days is not None
        assert max_hold_days >= 1


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
        assert "diagnostics" in data
        assert "blocked_reasons" in data["diagnostics"]
        assert "top_blockers" in data["diagnostics"]
    
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

    def test_backtest_with_parameter_overrides(self, test_strategy):
        """Backtest should accept supported parameter overrides including max_hold_days."""
        response = client.post(
            f"/strategies/{test_strategy.id}/backtest",
            json={
                "start_date": "2024-01-01",
                "end_date": "2024-03-31",
                "initial_capital": 100000.0,
                "symbols": ["AAPL", "MSFT"],
                "parameters": {
                    "position_size": 1200.0,
                    "risk_per_trade": 1.2,
                    "stop_loss_pct": 2.5,
                    "take_profit_pct": 6.0,
                    "trailing_stop_pct": 2.8,
                    "atr_stop_mult": 1.9,
                    "zscore_entry_threshold": -1.3,
                    "dip_buy_threshold_pct": 2.0,
                    "max_hold_days": 10.0,
                },
            }
        )
        assert response.status_code == 200
        payload = response.json()
        assert isinstance(payload["total_trades"], int)
        assert isinstance(payload["final_capital"], (int, float))
        assert isinstance(payload["diagnostics"].get("parameters_used"), dict)
        # Verify advanced metrics are included in diagnostics.
        advanced = payload["diagnostics"].get("advanced_metrics")
        assert advanced is not None
        assert "profit_factor" in advanced
        assert "sortino_ratio" in advanced
        assert "expectancy_per_trade" in advanced
        assert "max_consecutive_losses" in advanced
        assert "calmar_ratio" in advanced
        assert "avg_hold_days" in advanced
        assert "slippage_bps_applied" in advanced
        parity = payload["diagnostics"].get("live_parity")
        assert parity is not None
        assert "universe_source" in parity
        assert "max_position_size_applied" in parity
        assert "risk_limit_daily_applied" in parity
        # Verify time_exit is tracked in exit_reasons.
        assert "time_exit" in payload["diagnostics"]["exit_reasons"]

    def test_backtest_rejects_unknown_parameter(self, test_strategy):
        """Backtest should reject unknown parameters."""
        response = client.post(
            f"/strategies/{test_strategy.id}/backtest",
            json={
                "start_date": "2024-01-01",
                "end_date": "2024-03-31",
                "initial_capital": 100000.0,
                "parameters": {
                    "unknown_param": 1.0,
                },
            }
        )
        assert response.status_code == 400

    def test_backtest_emulate_live_requires_alpaca_broker(self, test_strategy):
        """Live-equivalent backtest should require Alpaca broker mode."""
        response = client.post(
            f"/strategies/{test_strategy.id}/backtest",
            json={
                "start_date": "2024-01-01",
                "end_date": "2024-03-31",
                "initial_capital": 100000.0,
                "emulate_live_trading": True,
            },
        )
        assert response.status_code == 400
        assert "requires Alpaca broker mode" in str(response.json().get("detail", ""))

    def test_backtest_workspace_universe_respects_preset_mode(self, test_strategy):
        """Workspace-backed backtests should include universe context diagnostics."""
        prefs = client.post(
            "/preferences",
            json={
                "asset_type": "stock",
                "screener_mode": "preset",
                "stock_preset": "micro_budget",
                "weekly_budget": 100.0,
            },
        )
        assert prefs.status_code == 200

        response = client.post(
            f"/strategies/{test_strategy.id}/backtest",
            json={
                "start_date": "2024-01-01",
                "end_date": "2024-03-31",
                "initial_capital": 10000.0,
                "use_workspace_universe": True,
                "preset_universe_mode": "seed_only",
                "screener_mode": "preset",
                "stock_preset": "micro_budget",
                "screener_limit": 30,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        diagnostics = payload.get("diagnostics", {})
        universe = diagnostics.get("universe_context", {})
        assert universe.get("symbols_source") == "workspace_universe"
        assert universe.get("preset_universe_mode") == "seed_only"
        parity = diagnostics.get("live_parity", {})
        assert parity.get("universe_source") == "workspace_universe"


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

    def test_tune_dca_tranches(self, test_strategy):
        """Test tuning the dca_tranches parameter."""
        response = client.post(
            f"/strategies/{test_strategy.id}/tune",
            json={
                "parameter_name": "dca_tranches",
                "value": 2.0,
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["new_value"] == 2.0
        assert data["success"] is True

    def test_tune_max_consecutive_losses(self, test_strategy):
        """Test tuning the max_consecutive_losses parameter."""
        response = client.post(
            f"/strategies/{test_strategy.id}/tune",
            json={
                "parameter_name": "max_consecutive_losses",
                "value": 5.0,
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["new_value"] == 5.0
        assert data["success"] is True

    def test_tune_max_drawdown_pct(self, test_strategy):
        """Test tuning the max_drawdown_pct parameter."""
        response = client.post(
            f"/strategies/{test_strategy.id}/tune",
            json={
                "parameter_name": "max_drawdown_pct",
                "value": 25.0,
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["new_value"] == 25.0
        assert data["success"] is True


class TestMicroBudgetPreset:
    """Tests for micro budget preset configuration."""

    def test_micro_budget_preset_defaults(self):
        """Micro budget stock preset should produce correct defaults."""
        prefs = client.post(
            "/preferences",
            json={
                "asset_type": "stock",
                "screener_mode": "preset",
                "stock_preset": "micro_budget",
                "weekly_budget": 50.0,
            },
        )
        assert prefs.status_code == 200

        create = client.post(
            "/strategies",
            json={
                "name": "Micro Strategy",
                "symbols": ["SPY"],
            },
        )
        assert create.status_code == 200
        strategy_id = create.json()["id"]

        response = client.get(f"/strategies/{strategy_id}/config")
        assert response.status_code == 200
        data = response.json()

        param_map = {p["name"]: p["value"] for p in data["parameters"]}
        # position_size may be capped by weekly budget constraints
        assert param_map.get("position_size", 0) <= 75.0
        assert param_map.get("position_size", 0) > 0
        assert param_map.get("dca_tranches") == 2.0
        assert param_map.get("max_consecutive_losses") == 2.0
        assert param_map.get("max_drawdown_pct") == 10.0

    def test_config_includes_new_parameters(self, test_strategy):
        """Strategy config should include dca_tranches, max_consecutive_losses, max_drawdown_pct."""
        response = client.get(f"/strategies/{test_strategy.id}/config")
        assert response.status_code == 200
        data = response.json()

        param_names = [p["name"] for p in data["parameters"]]
        assert "dca_tranches" in param_names
        assert "max_consecutive_losses" in param_names
        assert "max_drawdown_pct" in param_names

    def test_backtest_with_dca_tranches(self, test_strategy):
        """Backtest should accept dca_tranches parameter."""
        response = client.post(
            f"/strategies/{test_strategy.id}/backtest",
            json={
                "start_date": "2024-01-01",
                "end_date": "2024-03-31",
                "initial_capital": 5000.0,
                "parameters": {
                    "position_size": 500.0,
                    "dca_tranches": 2.0,
                    "max_consecutive_losses": 2.0,
                    "max_drawdown_pct": 10.0,
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["total_trades"], int)
        params_used = data["diagnostics"].get("parameters_used", {})
        assert params_used.get("dca_tranches") == 2.0
