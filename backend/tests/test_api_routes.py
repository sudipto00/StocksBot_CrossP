"""
Tests for strategy CRUD operations and audit logs with database persistence.
"""

import pytest
import os
import time
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import app
from api import routes as api_routes
from storage.database import Base, get_db
from storage.service import StorageService
from storage.models import OrderSideEnum, TradeTypeEnum
from config.strategy_config import BacktestResult
from api.models import BacktestResponse, StrategyOptimizationResponse

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


def _reset_runtime_singletons() -> None:
    """Reset process-level singleton state used by API routes."""
    try:
        runner = getattr(api_routes.runner_manager, "runner", None)
        if runner is not None:
            try:
                runner.stop()
            except Exception:
                pass
        api_routes.runner_manager.runner = None
    except Exception:
        pass
    try:
        api_routes._invalidate_broker_instance()
    except Exception:
        pass
    try:
        with api_routes._idempotency_lock:
            api_routes._idempotency_cache.clear()
    except Exception:
        pass
    # Cancel and clear optimizer background state to avoid cross-test leakage.
    try:
        try:
            api_routes.stop_optimizer_dispatcher()
        except Exception:
            pass
        with api_routes._optimizer_jobs_lock:
            active_job_ids = list(api_routes._optimizer_jobs.keys())
            active_threads = list(api_routes._optimizer_job_threads.values())
            active_processes = list(api_routes._optimizer_job_processes.values())
        for job_id in active_job_ids:
            try:
                api_routes._optimizer_request_cancel(job_id, message="Test reset", force=True)
                api_routes._optimizer_escalate_cancel(job_id, force_now=True)
            except Exception:
                pass
        for thread in active_threads:
            try:
                thread.join(timeout=2.0)
            except Exception:
                pass
        for process in active_processes:
            try:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=0.5)
            except Exception:
                pass
        with api_routes._optimizer_jobs_lock:
            job_ids = (
                set(api_routes._optimizer_jobs.keys())
                | set(api_routes._optimizer_job_threads.keys())
                | set(api_routes._optimizer_job_processes.keys())
            )
            api_routes._optimizer_jobs.clear()
            api_routes._optimizer_job_threads.clear()
            api_routes._optimizer_job_processes.clear()
        for job_id in job_ids:
            try:
                api_routes._optimizer_clear_cancel_token(str(job_id))
            except Exception:
                pass
    except Exception:
        pass


@pytest.fixture(autouse=True)
def setup_database():
    """Create and drop test database for each test."""
    app.dependency_overrides[get_db] = override_get_db
    original_session_local = api_routes.SessionLocal
    api_routes.SessionLocal = TestingSessionLocal
    _reset_runtime_singletons()
    Base.metadata.create_all(bind=engine)
    yield
    _reset_runtime_singletons()
    api_routes.SessionLocal = original_session_local
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


def test_optimize_strategy_returns_recommendation(monkeypatch):
    """Optimizer endpoint should return recommended parameters/symbols payload."""
    created = client.post(
        "/strategies",
        json={
            "name": "Optimize Test",
            "symbols": ["AAPL", "MSFT", "INTC"],
        },
    )
    assert created.status_code == 200
    strategy_id = created.json()["id"]

    def _fake_optimize(self, **kwargs):
        assert kwargs["objective"] == "return"
        assert kwargs["strict_min_trades"] is True
        assert kwargs["walk_forward_enabled"] is True
        assert kwargs["walk_forward_folds"] == 4
        assert kwargs["ensemble_mode"] is True
        assert kwargs["ensemble_runs"] == 12
        assert kwargs["max_workers"] == 4
        best = BacktestResult(
            strategy_id=strategy_id,
            start_date="2024-01-01",
            end_date="2024-03-31",
            initial_capital=100000.0,
            final_capital=104200.0,
            total_return=4.2,
            total_trades=12,
            winning_trades=7,
            losing_trades=5,
            win_rate=58.3,
            max_drawdown=2.1,
            sharpe_ratio=1.35,
            volatility=12.8,
            trades=[],
            equity_curve=[],
            diagnostics={"blocked_reasons": {}, "top_blockers": []},
        )
        return {
            "requested_iterations": 8,
            "evaluated_iterations": 8,
            "objective": "return_priority",
            "score": 142.12,
            "ensemble_mode": True,
            "ensemble_runs": 12,
            "max_workers_used": 4,
            "min_trades_target": 20,
            "strict_min_trades": True,
            "best_candidate_meets_min_trades": False,
            "recommended_parameters": {
                "position_size": 450.0,
                "stop_loss_pct": 1.75,
            },
            "recommended_symbols": ["AAPL", "MSFT"],
            "top_candidates": [
                {
                    "rank": 1,
                    "score": 142.12,
                    "meets_min_trades": False,
                    "symbol_count": 2,
                    "sharpe_ratio": 1.35,
                    "total_return": 4.2,
                    "max_drawdown": 2.1,
                    "win_rate": 58.3,
                    "total_trades": 12,
                    "parameters": {"position_size": 450.0, "stop_loss_pct": 1.75},
                }
            ],
            "best_result": best,
            "walk_forward": {
                "enabled": True,
                "objective": "return_priority",
                "strict_min_trades": True,
                "min_trades_target": 20,
                "folds_requested": 4,
                "folds_completed": 2,
                "pass_rate_pct": 50.0,
                "average_score": 12.0,
                "average_return": 1.2,
                "average_sharpe": 0.4,
                "worst_fold_return": -0.8,
                "folds": [
                    {
                        "fold_index": 1,
                        "train_start": "2024-01-01",
                        "train_end": "2024-02-28",
                        "test_start": "2024-02-29",
                        "test_end": "2024-03-31",
                        "score": 10.0,
                        "total_return": 2.0,
                        "sharpe_ratio": 0.8,
                        "max_drawdown": 1.0,
                        "win_rate": 60.0,
                        "total_trades": 25,
                        "meets_min_trades": True,
                    }
                ],
                "notes": ["wf"],
            },
            "notes": ["ok"],
        }

    monkeypatch.setattr("services.strategy_optimizer.StrategyOptimizerService.optimize", _fake_optimize)

    response = client.post(
        f"/strategies/{strategy_id}/optimize",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "initial_capital": 100000,
            "emulate_live_trading": False,
            "use_workspace_universe": False,
            "iterations": 8,
            "objective": "return",
            "strict_min_trades": True,
            "walk_forward_enabled": True,
            "walk_forward_folds": 4,
            "ensemble_mode": True,
            "ensemble_runs": 12,
            "max_workers": 4,
            "min_trades": 20,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["strategy_id"] == strategy_id
    assert payload["requested_iterations"] == 8
    assert payload["evaluated_iterations"] == 8
    assert payload["recommended_symbols"] == ["AAPL", "MSFT"]
    assert payload["recommended_parameters"]["position_size"] == 450.0
    assert payload["best_result"]["sharpe_ratio"] == 1.35
    assert payload["objective"] == "return_priority"
    assert payload["ensemble_mode"] is True
    assert payload["ensemble_runs"] == 12
    assert payload["max_workers_used"] == 4
    assert payload["strict_min_trades"] is True
    assert payload["min_trades_target"] == 20
    assert payload["best_candidate_meets_min_trades"] is False
    assert payload["walk_forward"]["folds_requested"] == 4


def test_optimize_strategy_rejects_invalid_iterations():
    """Optimizer should enforce minimum iteration count via request validation."""
    created = client.post(
        "/strategies",
        json={
            "name": "Optimize Validation Test",
            "symbols": ["AAPL", "MSFT"],
        },
    )
    assert created.status_code == 200
    strategy_id = created.json()["id"]

    response = client.post(
        f"/strategies/{strategy_id}/optimize",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "initial_capital": 100000,
            "emulate_live_trading": False,
            "use_workspace_universe": False,
            "iterations": 2,
        },
    )
    assert response.status_code == 422


def test_optimize_strategy_async_job_lifecycle(monkeypatch):
    """Async optimizer endpoints should expose job start/status/completion."""
    created = client.post(
        "/strategies",
        json={
            "name": "Optimize Async Test",
            "symbols": ["AAPL", "MSFT"],
        },
    )
    assert created.status_code == 200
    strategy_id = created.json()["id"]

    def _fake_compute(*, strategy_id: str, request, db, progress_callback=None, should_cancel=None):
        if progress_callback:
            progress_callback(1, 3, "parameter_search")
            progress_callback(2, 3, "parameter_search")
            progress_callback(3, 3, "finalizing")
        return StrategyOptimizationResponse(
            strategy_id=strategy_id,
            requested_iterations=12,
            evaluated_iterations=12,
            objective="sharpe_ratio_with_trade_count_penalty",
            score=101.0,
            recommended_parameters={"position_size": 250.0},
            recommended_symbols=["AAPL"],
            top_candidates=[],
            best_result=BacktestResponse(
                strategy_id=strategy_id,
                start_date="2024-01-01",
                end_date="2024-03-31",
                initial_capital=100000.0,
                final_capital=103000.0,
                total_return=3.0,
                total_trades=8,
                winning_trades=5,
                losing_trades=3,
                win_rate=62.5,
                max_drawdown=1.8,
                sharpe_ratio=1.2,
                volatility=10.0,
                trades=[],
                equity_curve=[],
                diagnostics={},
            ),
            notes=["ok"],
        )

    monkeypatch.setattr(api_routes, "_compute_strategy_optimization_response", _fake_compute)

    start = client.post(
        f"/strategies/{strategy_id}/optimize/start",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "initial_capital": 100000,
            "emulate_live_trading": False,
            "use_workspace_universe": False,
            "iterations": 12,
        },
    )
    assert start.status_code == 200
    job_id = start.json()["job_id"]

    status_payload = None
    for _ in range(40):
        status = client.get(f"/strategies/{strategy_id}/optimize/{job_id}")
        assert status.status_code == 200
        status_payload = status.json()
        if status_payload["status"] in {"completed", "failed", "canceled"}:
            break
        time.sleep(0.05)

    assert status_payload is not None
    assert status_payload["status"] == "completed"
    assert status_payload["result"]["strategy_id"] == strategy_id
    assert status_payload["result"]["recommended_symbols"] == ["AAPL"]


def test_optimizer_worker_refreshes_runtime_config_from_storage(monkeypatch):
    """Detached worker path should load persisted runtime config before compute."""
    created = client.post(
        "/strategies",
        json={
            "name": "Optimize Worker Config Refresh Test",
            "symbols": ["AAPL", "MSFT"],
        },
    )
    assert created.status_code == 200
    strategy_id = str(created.json()["id"])

    observed: dict[str, str] = {}

    def _fake_compute(*, strategy_id: str, request, db, progress_callback=None, should_cancel=None):
        snapshot = api_routes._get_config_snapshot()
        observed["broker"] = str(snapshot.broker)
        observed["paper_trading"] = str(bool(snapshot.paper_trading)).lower()
        return StrategyOptimizationResponse(
            strategy_id=strategy_id,
            requested_iterations=4,
            evaluated_iterations=4,
            objective="balanced",
            score=10.0,
            recommended_parameters={"position_size": 200.0},
            recommended_symbols=["AAPL"],
            top_candidates=[],
            best_result=BacktestResponse(
                strategy_id=strategy_id,
                start_date="2024-01-01",
                end_date="2024-03-31",
                initial_capital=100000.0,
                final_capital=101500.0,
                total_return=1.5,
                total_trades=6,
                winning_trades=4,
                losing_trades=2,
                win_rate=66.7,
                max_drawdown=2.1,
                sharpe_ratio=0.7,
                volatility=10.0,
                trades=[],
                equity_curve=[],
                diagnostics={},
            ),
            notes=["ok"],
        )

    monkeypatch.setattr(api_routes, "_compute_strategy_optimization_response", _fake_compute)

    previous_snapshot = api_routes._get_config_snapshot()
    try:
        db = TestingSessionLocal()
        try:
            storage = StorageService(db)
            persisted_cfg = previous_snapshot.model_copy(
                update={
                    "broker": "alpaca",
                    "paper_trading": True,
                    "trading_enabled": True,
                }
            )
            api_routes._save_runtime_config(storage, persisted_cfg)
        finally:
            db.close()

        # Simulate stale in-memory state inherited by child process import.
        api_routes._set_config_snapshot(previous_snapshot.model_copy(update={"broker": "paper"}))

        job = api_routes._optimizer_create_job(
            strategy_id=strategy_id,
            request_payload={
                "start_date": "2024-01-01",
                "end_date": "2024-03-31",
                "initial_capital": 100000,
                "emulate_live_trading": True,
                "use_workspace_universe": False,
                "iterations": 8,
            },
        )
        job_id = str(job["job_id"])
        api_routes._run_optimizer_job(job_id)

        status = api_routes._optimizer_get_job(job_id)
        assert status is not None
        assert str(status.get("status")) == "completed"
        assert observed.get("broker") == "alpaca"
        assert observed.get("paper_trading") == "true"
    finally:
        api_routes._set_config_snapshot(previous_snapshot)


def test_optimizer_worker_credential_env_roundtrip():
    """Detached worker credential env should round-trip runtime paper/live credentials."""
    with api_routes._state_lock:
        original = {
            "paper": dict(api_routes._runtime_broker_credentials.get("paper", {})),
            "live": dict(api_routes._runtime_broker_credentials.get("live", {})),
        }
    try:
        api_routes._set_runtime_credentials("paper", "paper_key_12345678", "paper_secret_12345678")
        api_routes._set_runtime_credentials("live", "live_key_12345678", "live_secret_12345678")

        worker_env = api_routes._optimizer_worker_env_with_runtime_credentials({})
        assert worker_env.get("STOCKSBOT_OPTIMIZER_PAPER_API_KEY") == "paper_key_12345678"
        assert worker_env.get("STOCKSBOT_OPTIMIZER_PAPER_SECRET_KEY") == "paper_secret_12345678"
        assert worker_env.get("STOCKSBOT_OPTIMIZER_LIVE_API_KEY") == "live_key_12345678"
        assert worker_env.get("STOCKSBOT_OPTIMIZER_LIVE_SECRET_KEY") == "live_secret_12345678"

        with api_routes._state_lock:
            api_routes._runtime_broker_credentials["paper"]["api_key"] = None
            api_routes._runtime_broker_credentials["paper"]["secret_key"] = None
            api_routes._runtime_broker_credentials["live"]["api_key"] = None
            api_routes._runtime_broker_credentials["live"]["secret_key"] = None

        hydrated = api_routes._optimizer_hydrate_runtime_credentials_from_env(worker_env)
        assert hydrated is True
        paper_creds = api_routes._get_runtime_credentials("paper")
        live_creds = api_routes._get_runtime_credentials("live")
        assert paper_creds.get("api_key") == "paper_key_12345678"
        assert paper_creds.get("secret_key") == "paper_secret_12345678"
        assert live_creds.get("api_key") == "live_key_12345678"
        assert live_creds.get("secret_key") == "live_secret_12345678"
    finally:
        with api_routes._state_lock:
            api_routes._runtime_broker_credentials["paper"]["api_key"] = original["paper"].get("api_key")
            api_routes._runtime_broker_credentials["paper"]["secret_key"] = original["paper"].get("secret_key")
            api_routes._runtime_broker_credentials["live"]["api_key"] = original["live"].get("api_key")
            api_routes._runtime_broker_credentials["live"]["secret_key"] = original["live"].get("secret_key")
        api_routes._invalidate_broker_instance()


def test_optimize_strategy_async_job_cancel(monkeypatch):
    """Async optimizer cancel endpoint should mark running jobs for cancellation."""
    created = client.post(
        "/strategies",
        json={
            "name": "Optimize Async Cancel Test",
            "symbols": ["AAPL", "MSFT"],
        },
    )
    assert created.status_code == 200
    strategy_id = created.json()["id"]

    def _slow_compute(*, strategy_id: str, request, db, progress_callback=None, should_cancel=None):
        total = 20
        for idx in range(total):
            if should_cancel and should_cancel():
                raise api_routes.OptimizationCancelledError("canceled")
            if progress_callback:
                progress_callback(idx + 1, total, "parameter_search")
            time.sleep(0.02)
        return StrategyOptimizationResponse(
            strategy_id=strategy_id,
            requested_iterations=20,
            evaluated_iterations=20,
            objective="sharpe_ratio_with_trade_count_penalty",
            score=88.0,
            recommended_parameters={"position_size": 200.0},
            recommended_symbols=["AAPL"],
            top_candidates=[],
            best_result=BacktestResponse(
                strategy_id=strategy_id,
                start_date="2024-01-01",
                end_date="2024-03-31",
                initial_capital=100000.0,
                final_capital=101000.0,
                total_return=1.0,
                total_trades=5,
                winning_trades=3,
                losing_trades=2,
                win_rate=60.0,
                max_drawdown=2.0,
                sharpe_ratio=0.6,
                volatility=11.0,
                trades=[],
                equity_curve=[],
                diagnostics={},
            ),
            notes=["ok"],
        )

    monkeypatch.setattr(api_routes, "_compute_strategy_optimization_response", _slow_compute)

    start = client.post(
        f"/strategies/{strategy_id}/optimize/start",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "initial_capital": 100000,
            "emulate_live_trading": False,
            "use_workspace_universe": False,
            "iterations": 20,
        },
    )
    assert start.status_code == 200
    job_id = start.json()["job_id"]

    time.sleep(0.1)
    cancel = client.post(f"/strategies/{strategy_id}/optimize/{job_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["success"] is True

    final_payload = None
    for _ in range(50):
        status = client.get(f"/strategies/{strategy_id}/optimize/{job_id}")
        assert status.status_code == 200
        final_payload = status.json()
        if final_payload["status"] in {"canceled", "failed", "completed"}:
            break
        time.sleep(0.05)

    assert final_payload is not None
    assert final_payload["status"] == "canceled"


def test_optimize_start_rejects_second_active_job_for_same_strategy(monkeypatch):
    """Only one active optimizer job should run per strategy."""
    created = client.post(
        "/strategies",
        json={
            "name": "Optimize Concurrency Guard Test",
            "symbols": ["AAPL", "MSFT"],
        },
    )
    assert created.status_code == 200
    strategy_id = created.json()["id"]

    def _slow_compute(*, strategy_id: str, request, db, progress_callback=None, should_cancel=None):
        for idx in range(50):
            if should_cancel and should_cancel():
                raise api_routes.OptimizationCancelledError("canceled")
            if progress_callback:
                progress_callback(idx + 1, 50, "parameter_search")
            time.sleep(0.02)
        return StrategyOptimizationResponse(
            strategy_id=strategy_id,
            requested_iterations=50,
            evaluated_iterations=50,
            objective="balanced",
            score=20.0,
            recommended_parameters={"position_size": 200.0},
            recommended_symbols=["AAPL"],
            top_candidates=[],
            best_result=BacktestResponse(
                strategy_id=strategy_id,
                start_date="2024-01-01",
                end_date="2024-03-31",
                initial_capital=100000.0,
                final_capital=101000.0,
                total_return=1.0,
                total_trades=6,
                winning_trades=4,
                losing_trades=2,
                win_rate=66.7,
                max_drawdown=2.0,
                sharpe_ratio=0.6,
                volatility=11.0,
                trades=[],
                equity_curve=[],
                diagnostics={},
            ),
            notes=["ok"],
        )

    monkeypatch.setattr(api_routes, "_compute_strategy_optimization_response", _slow_compute)

    payload_one = {
        "start_date": "2024-01-01",
        "end_date": "2024-03-31",
        "initial_capital": 100000,
        "emulate_live_trading": False,
        "use_workspace_universe": False,
        "iterations": 30,
    }
    payload_two = {
        "start_date": "2024-01-01",
        "end_date": "2024-03-31",
        "initial_capital": 100000,
        "emulate_live_trading": False,
        "use_workspace_universe": False,
        "iterations": 40,
    }
    first = client.post(f"/strategies/{strategy_id}/optimize/start", json=payload_one)
    assert first.status_code == 200

    second = client.post(f"/strategies/{strategy_id}/optimize/start", json=payload_two)
    assert second.status_code == 409
    assert "already has an active optimizer job" in str(second.json().get("detail", ""))


def test_optimize_start_reuses_existing_job_for_identical_payload(monkeypatch):
    """Identical start requests should return existing job id instead of creating duplicates."""
    created = client.post(
        "/strategies",
        json={
            "name": "Optimize Idempotent Payload Test",
            "symbols": ["AAPL", "MSFT"],
        },
    )
    assert created.status_code == 200
    strategy_id = created.json()["id"]

    def _slow_compute(*, strategy_id: str, request, db, progress_callback=None, should_cancel=None):
        for idx in range(30):
            if should_cancel and should_cancel():
                raise api_routes.OptimizationCancelledError("canceled")
            if progress_callback:
                progress_callback(idx + 1, 30, "parameter_search")
            time.sleep(0.02)
        return StrategyOptimizationResponse(
            strategy_id=strategy_id,
            requested_iterations=30,
            evaluated_iterations=30,
            objective="balanced",
            score=15.0,
            recommended_parameters={"position_size": 180.0},
            recommended_symbols=["AAPL"],
            top_candidates=[],
            best_result=BacktestResponse(
                strategy_id=strategy_id,
                start_date="2024-01-01",
                end_date="2024-03-31",
                initial_capital=100000.0,
                final_capital=100800.0,
                total_return=0.8,
                total_trades=5,
                winning_trades=3,
                losing_trades=2,
                win_rate=60.0,
                max_drawdown=2.2,
                sharpe_ratio=0.4,
                volatility=12.0,
                trades=[],
                equity_curve=[],
                diagnostics={},
            ),
            notes=["ok"],
        )

    monkeypatch.setattr(api_routes, "_compute_strategy_optimization_response", _slow_compute)

    payload = {
        "start_date": "2024-01-01",
        "end_date": "2024-03-31",
        "initial_capital": 100000,
        "emulate_live_trading": False,
        "use_workspace_universe": False,
        "iterations": 30,
    }
    first = client.post(f"/strategies/{strategy_id}/optimize/start", json=payload)
    second = client.post(f"/strategies/{strategy_id}/optimize/start", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["job_id"] == second.json()["job_id"]


def test_optimizer_health_endpoint_reports_snapshot():
    """Optimizer health endpoint should return counts and active job metadata."""
    created = client.post(
        "/strategies",
        json={
            "name": "Optimizer Health Test",
            "symbols": ["AAPL"],
        },
    )
    assert created.status_code == 200
    strategy_id = str(created.json()["id"])
    job = api_routes._optimizer_create_job(
        strategy_id=strategy_id,
        request_payload={
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "initial_capital": 100000,
            "iterations": 12,
        },
    )
    api_routes._optimizer_update_job(
        str(job["job_id"]),
        {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "message": "Running parameter search",
        },
    )

    response = client.get("/optimizer/health")
    assert response.status_code == 200
    payload = response.json()
    assert "status_counts" in payload
    assert "active_jobs" in payload
    assert payload["active_job_count"] >= 1


def test_optimizer_prefers_persisted_row_when_runtime_progress_advances():
    """Persisted row should replace stale in-memory row when heartbeat/progress is newer."""
    local_row = {
        "status": "running",
        "message": "Preparing symbols, universe, and live constraints",
        "progress_pct": 0.5,
        "completed_iterations": 0,
        "last_heartbeat_at": "2026-02-21T01:01:44+00:00",
    }
    persisted_row = {
        "status": "running",
        "message": "Running Monte Carlo ensemble scenarios",
        "progress_pct": 4.13,
        "completed_iterations": 32,
        "last_heartbeat_at": "2026-02-21T01:08:56+00:00",
    }
    assert api_routes._optimizer_should_prefer_persisted_row(local_row, persisted_row) is True


def test_optimizer_keeps_local_row_when_cancel_requested_not_flushed():
    """Local cancel intent should not be hidden by stale persisted snapshots."""
    local_row = {
        "status": "running",
        "cancel_requested": True,
        "cancel_requested_at": datetime.now(timezone.utc).isoformat(),
        "progress_pct": 10.0,
    }
    persisted_row = {
        "status": "running",
        "cancel_requested": False,
        "progress_pct": 11.0,
        "last_heartbeat_at": datetime.now(timezone.utc).isoformat(),
    }
    assert api_routes._optimizer_should_prefer_persisted_row(local_row, persisted_row) is False


def test_optimize_strategy_async_job_force_cancel_query(monkeypatch):
    """Force cancel query flag should be accepted and request cancellation."""
    created = client.post(
        "/strategies",
        json={
            "name": "Optimize Async Force Cancel Test",
            "symbols": ["AAPL", "MSFT"],
        },
    )
    assert created.status_code == 200
    strategy_id = created.json()["id"]

    def _slow_compute(*, strategy_id: str, request, db, progress_callback=None, should_cancel=None):
        total = 40
        for idx in range(total):
            if should_cancel and should_cancel():
                raise api_routes.OptimizationCancelledError("canceled")
            if progress_callback:
                progress_callback(idx + 1, total, "ensemble_search")
            time.sleep(0.02)
        return StrategyOptimizationResponse(
            strategy_id=strategy_id,
            requested_iterations=40,
            evaluated_iterations=40,
            objective="sharpe_ratio_with_trade_count_penalty",
            score=50.0,
            recommended_parameters={"position_size": 200.0},
            recommended_symbols=["AAPL"],
            top_candidates=[],
            best_result=BacktestResponse(
                strategy_id=strategy_id,
                start_date="2024-01-01",
                end_date="2024-03-31",
                initial_capital=100000.0,
                final_capital=101000.0,
                total_return=1.0,
                total_trades=5,
                winning_trades=3,
                losing_trades=2,
                win_rate=60.0,
                max_drawdown=2.0,
                sharpe_ratio=0.6,
                volatility=11.0,
                trades=[],
                equity_curve=[],
                diagnostics={},
            ),
            notes=["ok"],
        )

    monkeypatch.setattr(api_routes, "_compute_strategy_optimization_response", _slow_compute)

    start = client.post(
        f"/strategies/{strategy_id}/optimize/start",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "initial_capital": 100000,
            "emulate_live_trading": False,
            "use_workspace_universe": False,
            "iterations": 40,
        },
    )
    assert start.status_code == 200
    job_id = start.json()["job_id"]

    time.sleep(0.1)
    cancel = client.post(f"/strategies/{strategy_id}/optimize/{job_id}/cancel?force=true")
    assert cancel.status_code == 200
    assert cancel.json()["success"] is True

    final_payload = None
    for _ in range(60):
        status = client.get(f"/strategies/{strategy_id}/optimize/{job_id}")
        assert status.status_code == 200
        final_payload = status.json()
        if final_payload["status"] in {"canceled", "failed", "completed"}:
            break
        time.sleep(0.05)

    assert final_payload is not None
    assert final_payload["status"] == "canceled"


def test_optimizer_cancel_all_endpoint(monkeypatch):
    """Bulk optimizer cancel endpoint should request cancel for all active jobs."""
    create_one = client.post("/strategies", json={"name": "Bulk Cancel One", "symbols": ["AAPL"]})
    create_two = client.post("/strategies", json={"name": "Bulk Cancel Two", "symbols": ["MSFT"]})
    assert create_one.status_code == 200
    assert create_two.status_code == 200
    strategy_one = create_one.json()["id"]
    strategy_two = create_two.json()["id"]

    def _slow_compute(*, strategy_id: str, request, db, progress_callback=None, should_cancel=None):
        total = 60
        for idx in range(total):
            if should_cancel and should_cancel():
                raise api_routes.OptimizationCancelledError("canceled")
            if progress_callback:
                progress_callback(idx + 1, total, "parameter_search")
            time.sleep(0.015)
        return StrategyOptimizationResponse(
            strategy_id=strategy_id,
            requested_iterations=60,
            evaluated_iterations=60,
            objective="sharpe_ratio_with_trade_count_penalty",
            score=70.0,
            recommended_parameters={"position_size": 150.0},
            recommended_symbols=["AAPL"],
            top_candidates=[],
            best_result=BacktestResponse(
                strategy_id=strategy_id,
                start_date="2024-01-01",
                end_date="2024-03-31",
                initial_capital=100000.0,
                final_capital=101000.0,
                total_return=1.0,
                total_trades=5,
                winning_trades=3,
                losing_trades=2,
                win_rate=60.0,
                max_drawdown=2.0,
                sharpe_ratio=0.6,
                volatility=11.0,
                trades=[],
                equity_curve=[],
                diagnostics={},
            ),
            notes=["ok"],
        )

    monkeypatch.setattr(api_routes, "_compute_strategy_optimization_response", _slow_compute)

    start_one = client.post(
        f"/strategies/{strategy_one}/optimize/start",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "initial_capital": 100000,
            "emulate_live_trading": False,
            "use_workspace_universe": False,
            "iterations": 60,
        },
    )
    start_two = client.post(
        f"/strategies/{strategy_two}/optimize/start",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "initial_capital": 100000,
            "emulate_live_trading": False,
            "use_workspace_universe": False,
            "iterations": 60,
        },
    )
    assert start_one.status_code == 200
    assert start_two.status_code == 200
    job_one = start_one.json()["job_id"]
    job_two = start_two.json()["job_id"]

    time.sleep(0.1)
    bulk = client.post("/optimizer/cancel-all?force=true")
    assert bulk.status_code == 200
    payload = bulk.json()
    assert payload["success"] is True
    assert payload["requested_count"] >= 2

    def _wait_terminal(strategy_id: str, job_id: str) -> str:
        status_value = "running"
        for _ in range(60):
            status = client.get(f"/strategies/{strategy_id}/optimize/{job_id}")
            assert status.status_code == 200
            status_value = status.json()["status"]
            if status_value in {"canceled", "failed", "completed"}:
                break
            time.sleep(0.05)
        return status_value

    assert _wait_terminal(strategy_one, job_one) == "canceled"
    assert _wait_terminal(strategy_two, job_two) == "canceled"


def test_optimizer_jobs_endpoint_requeues_stale_running_job():
    """Jobs endpoint should requeue stale running jobs for dispatcher recovery."""
    created = client.post(
        "/strategies",
        json={
            "name": "Stale Optimizer Job Test",
            "symbols": ["AAPL"],
        },
    )
    assert created.status_code == 200
    strategy_id = str(created.json()["id"])

    job = api_routes._optimizer_create_job(
        strategy_id=strategy_id,
        request_payload={
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "initial_capital": 100000,
            "iterations": 12,
        },
    )
    job_id = str(job["job_id"])
    api_routes._optimizer_update_job(
        job_id,
        {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "message": "Running parameter search",
        },
    )

    with api_routes._optimizer_jobs_lock:
        api_routes._optimizer_job_threads.pop(job_id, None)

    listing = client.get("/optimizer/jobs")
    assert listing.status_code == 200
    rows = listing.json().get("jobs", [])
    matched = next((row for row in rows if str(row.get("job_id")) == job_id), None)
    assert matched is not None
    assert matched["status"] in {"queued", "failed"}
    assert "queued for retry" in str(matched.get("message", "")).lower() or "not running" in str(matched.get("message", "")).lower()


def test_optimizer_status_endpoint_prefers_persisted_terminal_over_stale_local_queued():
    """Job status endpoint should return persisted terminal state over stale local queued row."""
    created = client.post(
        "/strategies",
        json={
            "name": "Optimizer Persisted Terminal Preference Test",
            "symbols": ["AAPL"],
        },
    )
    assert created.status_code == 200
    strategy_id = str(created.json()["id"])

    job = api_routes._optimizer_create_job(
        strategy_id=strategy_id,
        request_payload={
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "initial_capital": 100000,
            "iterations": 12,
        },
    )
    job_id = str(job["job_id"])
    with api_routes._optimizer_jobs_lock:
        assert str(api_routes._optimizer_jobs[job_id].get("status")) == "queued"

    failed_snapshot = dict(job)
    failed_snapshot.update(
        {
            "status": "failed",
            "message": "Failed",
            "error": "Synthetic persisted failure",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "progress_pct": 100.0,
            "eta_seconds": 0.0,
        }
    )
    api_routes._optimizer_persist_snapshot(failed_snapshot, prune_history=True)

    status = client.get(f"/strategies/{strategy_id}/optimize/{job_id}")
    assert status.status_code == 200
    payload = status.json()
    assert payload["status"] == "failed"
    assert "synthetic persisted failure" in str(payload.get("error", "")).lower()

    with api_routes._optimizer_jobs_lock:
        assert str(api_routes._optimizer_jobs[job_id].get("status")) == "failed"


def test_optimizer_status_endpoint_prefers_persisted_running_over_stale_local_queued():
    """Job status endpoint should surface persisted running state when local row is stale queued."""
    created = client.post(
        "/strategies",
        json={
            "name": "Optimizer Persisted Running Preference Test",
            "symbols": ["AAPL"],
        },
    )
    assert created.status_code == 200
    strategy_id = str(created.json()["id"])

    job = api_routes._optimizer_create_job(
        strategy_id=strategy_id,
        request_payload={
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "initial_capital": 100000,
            "iterations": 16,
        },
    )
    job_id = str(job["job_id"])
    with api_routes._optimizer_jobs_lock:
        assert str(api_routes._optimizer_jobs[job_id].get("status")) == "queued"

    now_iso = datetime.now(timezone.utc).isoformat()
    running_snapshot = dict(job)
    running_snapshot.update(
        {
            "status": "running",
            "message": "Running optimizer",
            "started_at": now_iso,
            "last_heartbeat_at": now_iso,
            "progress_pct": 33.0,
            "completed_iterations": 5,
            "total_iterations": 16,
            "elapsed_seconds": 4.2,
        }
    )
    api_routes._optimizer_persist_snapshot(running_snapshot, prune_history=False)

    status = client.get(f"/strategies/{strategy_id}/optimize/{job_id}")
    assert status.status_code == 200
    payload = status.json()
    assert payload["status"] == "running"
    assert float(payload.get("progress_pct", 0.0)) >= 30.0

    listing = client.get("/optimizer/jobs?statuses=running")
    assert listing.status_code == 200
    rows = listing.json().get("jobs", [])
    matched = next((row for row in rows if str(row.get("job_id")) == job_id), None)
    assert matched is not None
    assert str(matched.get("status")) == "running"


def test_optimize_strategy_persists_history_sync(monkeypatch):
    """Synchronous optimize endpoint should persist optimization history rows."""
    created = client.post(
        "/strategies",
        json={
            "name": "Optimize Sync History Test",
            "symbols": ["AAPL", "MSFT"],
        },
    )
    assert created.status_code == 200
    strategy_id = str(created.json()["id"])

    def _fake_compute(*, strategy_id: str, request, db, progress_callback=None, should_cancel=None):
        return StrategyOptimizationResponse(
            strategy_id=strategy_id,
            requested_iterations=10,
            evaluated_iterations=10,
            objective="balanced_score",
            score=77.25,
            recommended_parameters={"position_size": 320.0, "stop_loss_pct": 1.8},
            recommended_symbols=["AAPL", "MSFT"],
            top_candidates=[],
            best_result=BacktestResponse(
                strategy_id=strategy_id,
                start_date="2024-01-01",
                end_date="2024-04-01",
                initial_capital=100000.0,
                final_capital=104500.0,
                total_return=4.5,
                total_trades=14,
                winning_trades=8,
                losing_trades=6,
                win_rate=57.1,
                max_drawdown=2.4,
                sharpe_ratio=1.12,
                volatility=11.5,
                trades=[],
                equity_curve=[],
                diagnostics={},
            ),
            notes=["ok"],
        )

    monkeypatch.setattr(api_routes, "_compute_strategy_optimization_response", _fake_compute)

    optimize = client.post(
        f"/strategies/{strategy_id}/optimize",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-04-01",
            "initial_capital": 100000,
            "emulate_live_trading": False,
            "use_workspace_universe": False,
            "iterations": 10,
        },
    )
    assert optimize.status_code == 200

    history = client.get(f"/strategies/{strategy_id}/optimization-history?limit=5")
    assert history.status_code == 200
    payload = history.json()
    assert payload["total_count"] >= 1
    row = payload["runs"][0]
    assert row["strategy_id"] == strategy_id
    assert row["source"] == "sync"
    assert row["status"] == "completed"
    assert row["metrics_summary"]["total_return"] == pytest.approx(4.5, rel=1e-6)
    assert row["recommended_parameters"]["position_size"] == pytest.approx(320.0, rel=1e-6)


def test_optimize_strategy_async_job_persists_history(monkeypatch):
    """Async optimize jobs should write terminal rows to optimization history."""
    created = client.post(
        "/strategies",
        json={
            "name": "Optimize Async History Test",
            "symbols": ["AAPL", "MSFT"],
        },
    )
    assert created.status_code == 200
    strategy_id = str(created.json()["id"])

    def _fake_compute(*, strategy_id: str, request, db, progress_callback=None, should_cancel=None):
        if progress_callback:
            progress_callback(1, 2, "parameter_search")
            progress_callback(2, 2, "finalizing")
        return StrategyOptimizationResponse(
            strategy_id=strategy_id,
            requested_iterations=12,
            evaluated_iterations=12,
            objective="balanced_score",
            score=88.0,
            recommended_parameters={"position_size": 280.0},
            recommended_symbols=["AAPL"],
            top_candidates=[],
            best_result=BacktestResponse(
                strategy_id=strategy_id,
                start_date="2024-01-01",
                end_date="2024-03-31",
                initial_capital=100000.0,
                final_capital=103000.0,
                total_return=3.0,
                total_trades=9,
                winning_trades=6,
                losing_trades=3,
                win_rate=66.7,
                max_drawdown=1.9,
                sharpe_ratio=1.1,
                volatility=10.2,
                trades=[],
                equity_curve=[],
                diagnostics={},
            ),
            notes=["ok"],
        )

    monkeypatch.setattr(api_routes, "_compute_strategy_optimization_response", _fake_compute)

    start = client.post(
        f"/strategies/{strategy_id}/optimize/start",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "initial_capital": 100000,
            "emulate_live_trading": False,
            "use_workspace_universe": False,
            "iterations": 12,
        },
    )
    assert start.status_code == 200
    job_id = start.json()["job_id"]

    status_payload = None
    for _ in range(40):
        status = client.get(f"/strategies/{strategy_id}/optimize/{job_id}")
        assert status.status_code == 200
        status_payload = status.json()
        if status_payload["status"] in {"completed", "failed", "canceled"}:
            break
        time.sleep(0.05)
    assert status_payload is not None
    assert status_payload["status"] == "completed"

    history = client.get(f"/strategies/{strategy_id}/optimization-history?limit=10")
    assert history.status_code == 200
    rows = history.json()["runs"]
    matched = next((row for row in rows if row["run_id"] == job_id), None)
    assert matched is not None
    assert matched["source"] == "async"
    assert matched["status"] == "completed"


def test_optimizer_history_supports_multi_strategy_compare_query(monkeypatch):
    """Global optimization history endpoint should scope rows by strategy ids."""
    create_one = client.post("/strategies", json={"name": "History Compare One", "symbols": ["AAPL"]})
    create_two = client.post("/strategies", json={"name": "History Compare Two", "symbols": ["MSFT"]})
    assert create_one.status_code == 200
    assert create_two.status_code == 200
    strategy_one = str(create_one.json()["id"])
    strategy_two = str(create_two.json()["id"])

    def _fake_compute(*, strategy_id: str, request, db, progress_callback=None, should_cancel=None):
        return StrategyOptimizationResponse(
            strategy_id=strategy_id,
            requested_iterations=8,
            evaluated_iterations=8,
            objective="balanced_score",
            score=60.0 if strategy_id == strategy_one else 45.0,
            recommended_parameters={"position_size": 200.0 if strategy_id == strategy_one else 150.0},
            recommended_symbols=["AAPL"] if strategy_id == strategy_one else ["MSFT"],
            top_candidates=[],
            best_result=BacktestResponse(
                strategy_id=strategy_id,
                start_date="2024-01-01",
                end_date="2024-02-29",
                initial_capital=100000.0,
                final_capital=101000.0,
                total_return=1.0,
                total_trades=5,
                winning_trades=3,
                losing_trades=2,
                win_rate=60.0,
                max_drawdown=1.5,
                sharpe_ratio=0.8,
                volatility=9.5,
                trades=[],
                equity_curve=[],
                diagnostics={},
            ),
            notes=["ok"],
        )

    monkeypatch.setattr(api_routes, "_compute_strategy_optimization_response", _fake_compute)

    first = client.post(
        f"/strategies/{strategy_one}/optimize",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-02-29",
            "initial_capital": 100000,
            "emulate_live_trading": False,
            "use_workspace_universe": False,
            "iterations": 8,
        },
    )
    second = client.post(
        f"/strategies/{strategy_two}/optimize",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-02-29",
            "initial_capital": 100000,
            "emulate_live_trading": False,
            "use_workspace_universe": False,
            "iterations": 8,
        },
    )
    assert first.status_code == 200
    assert second.status_code == 200

    listing = client.get(f"/optimizer/history?strategy_ids={strategy_one},{strategy_two}&limit_per_strategy=1")
    assert listing.status_code == 200
    payload = listing.json()
    assert payload["total_count"] == 2
    strategy_ids = sorted(row["strategy_id"] for row in payload["runs"])
    assert strategy_ids == sorted([strategy_one, strategy_two])


def test_optimizer_status_falls_back_to_persisted_job_row_after_memory_loss():
    """Status endpoint should remain available from persisted async rows."""
    created = client.post(
        "/strategies",
        json={
            "name": "Persisted Status Fallback Test",
            "symbols": ["AAPL"],
        },
    )
    assert created.status_code == 200
    strategy_id = str(created.json()["id"])

    job = api_routes._optimizer_create_job(
        strategy_id=strategy_id,
        request_payload={
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "initial_capital": 100000,
            "iterations": 12,
        },
    )
    job_id = str(job["job_id"])
    api_routes._optimizer_update_job(
        job_id,
        {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "message": "Running parameter search",
        },
    )

    with api_routes._optimizer_jobs_lock:
        api_routes._optimizer_jobs.pop(job_id, None)
        api_routes._optimizer_job_threads.pop(job_id, None)

    status = client.get(f"/strategies/{strategy_id}/optimize/{job_id}")
    assert status.status_code == 200
    payload = status.json()
    assert payload["job_id"] == job_id
    assert payload["status"] in {"failed", "canceled", "completed", "running", "queued"}


def test_optimizer_jobs_endpoint_includes_persisted_async_rows():
    """Jobs listing should include persisted async rows even without in-memory state."""
    created = client.post(
        "/strategies",
        json={
            "name": "Persisted Job Listing Test",
            "symbols": ["AAPL"],
        },
    )
    assert created.status_code == 200
    strategy_id = str(created.json()["id"])

    job = api_routes._optimizer_create_job(
        strategy_id=strategy_id,
        request_payload={
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "initial_capital": 100000,
            "iterations": 12,
        },
    )
    job_id = str(job["job_id"])
    api_routes._optimizer_update_job(
        job_id,
        {
            "status": "completed",
            "progress_pct": 100.0,
            "message": "Completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    with api_routes._optimizer_jobs_lock:
        api_routes._optimizer_jobs.pop(job_id, None)
        api_routes._optimizer_job_threads.pop(job_id, None)

    listing = client.get("/optimizer/jobs")
    assert listing.status_code == 200
    rows = listing.json().get("jobs", [])
    matched = next((row for row in rows if str(row.get("job_id")) == job_id), None)
    assert matched is not None
    assert matched["status"] in {"completed", "failed", "canceled"}


def test_optimizer_jobs_endpoint_supports_filters_and_pagination():
    """Optimizer jobs endpoint should honor status filter + offset pagination."""
    created = client.post(
        "/strategies",
        json={
            "name": "Optimizer Jobs Paging Test",
            "symbols": ["AAPL"],
        },
    )
    assert created.status_code == 200
    strategy_id = str(created.json()["id"])

    first = api_routes._optimizer_create_job(
        strategy_id=strategy_id,
        request_payload={
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "initial_capital": 100000,
            "iterations": 8,
        },
    )
    second = api_routes._optimizer_create_job(
        strategy_id=strategy_id,
        request_payload={
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "initial_capital": 100000,
            "iterations": 10,
        },
    )
    api_routes._optimizer_update_job(
        str(first["job_id"]),
        {
            "status": "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "message": "Completed",
        },
    )

    listing = client.get("/optimizer/jobs?statuses=queued,running&limit=1&offset=0")
    assert listing.status_code == 200
    payload = listing.json()
    assert int(payload.get("total_count", 0)) >= 1
    assert int(payload.get("limit", 0)) == 1
    assert int(payload.get("offset", 0)) == 0
    assert len(payload.get("jobs", [])) == 1
    assert payload["jobs"][0]["status"] in {"queued", "running"}

    second_page = client.get("/optimizer/jobs?statuses=queued,running&limit=1&offset=1")
    assert second_page.status_code == 200
    second_payload = second_page.json()
    assert int(second_payload.get("offset", 0)) == 1
    assert int(second_payload.get("total_count", 0)) >= 1
    assert str(second["job_id"]) != str(first["job_id"])


def test_purge_optimizer_jobs_endpoint_removes_canceled_async_rows():
    """DELETE /optimizer/jobs should remove canceled async rows."""
    created = client.post(
        "/strategies",
        json={
            "name": "Purge Jobs Test",
            "symbols": ["AAPL"],
        },
    )
    assert created.status_code == 200
    strategy_id = str(created.json()["id"])

    job = api_routes._optimizer_create_job(
        strategy_id=strategy_id,
        request_payload={
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "initial_capital": 100000,
            "iterations": 12,
        },
    )
    job_id = str(job["job_id"])
    api_routes._optimizer_update_job(
        job_id,
        {
            "status": "canceled",
            "message": "Canceled by user",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    purge = client.delete("/optimizer/jobs?statuses=canceled")
    assert purge.status_code == 200
    assert int(purge.json().get("deleted_count", 0)) >= 1

    history = client.get(f"/optimizer/history?strategy_ids={strategy_id}&statuses=canceled")
    assert history.status_code == 200
    rows = history.json().get("runs", [])
    assert all(str(row.get("run_id")) != job_id for row in rows)


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


def test_audit_logs_accept_runner_events():
    """Audit logs endpoint should support runner_* events."""
    db = TestingSessionLocal()
    try:
        storage = StorageService(db)
        storage.create_audit_log(
            event_type="runner_started",
            description="Runner started from test",
            details={"source": "test"},
        )
    finally:
        db.close()

    response = client.get("/audit/logs")
    assert response.status_code == 200
    data = response.json()
    assert any(log["event_type"] == "runner_started" for log in data["logs"])


def test_get_audit_trades():
    """Test getting complete trade history for audit mode."""
    db = TestingSessionLocal()
    try:
        storage = StorageService(db)
        order = storage.create_order(
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity=1.0,
        )
        storage.record_trade(
            order_id=order.id,
            symbol="AAPL",
            side="buy",
            quantity=1.0,
            price=190.0,
        )
    finally:
        db.close()

    response = client.get("/audit/trades")
    assert response.status_code == 200
    data = response.json()
    assert "trades" in data
    assert data["total_count"] >= 1
    assert any(t["symbol"] == "AAPL" for t in data["trades"])


# ============================================================================
# Summary Notification Tests
# ============================================================================

def test_send_summary_notification_now_timezone_safe(monkeypatch):
    """send-now should handle naive/aware datetimes without crashing."""
    prefs_response = client.post(
        "/notifications/summary/preferences",
        json={
            "enabled": True,
            "frequency": "daily",
            "channel": "email",
            "recipient": "test@example.com",
        },
    )
    assert prefs_response.status_code == 200

    db = TestingSessionLocal()
    try:
        storage = StorageService(db)
        order = storage.create_order(
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity=1.0,
        )
        # Intentionally store naive datetime to cover sqlite/runtime behavior.
        trade = storage.trades.create(
            order_id=order.id,
            symbol="AAPL",
            side=OrderSideEnum.BUY,
            type=TradeTypeEnum.OPEN,
            quantity=1.0,
            price=100.0,
            executed_at=datetime.now(),
        )
        trade.realized_pnl = 5.0
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(
        "services.notification_delivery.NotificationDeliveryService.send_summary",
        lambda self, channel, recipient, subject, body: f"Email sent to {recipient}",
    )

    response = client.post("/notifications/summary/send-now")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "Email sent to test@example.com" in data["message"]


def test_send_summary_notification_now_delivery_failure(monkeypatch):
    """Transport failures should return success=false with actionable message."""
    prefs_response = client.post(
        "/notifications/summary/preferences",
        json={
            "enabled": True,
            "frequency": "daily",
            "channel": "sms",
            "recipient": "+15551234567",
        },
    )
    assert prefs_response.status_code == 200

    db = TestingSessionLocal()
    try:
        storage = StorageService(db)
        order = storage.create_order(
            symbol="MSFT",
            side="buy",
            order_type="market",
            quantity=1.0,
        )
        storage.trades.create(
            order_id=order.id,
            symbol="MSFT",
            side=OrderSideEnum.BUY,
            type=TradeTypeEnum.OPEN,
            quantity=1.0,
            price=200.0,
            executed_at=datetime.now(timezone.utc),
        )
        db.commit()
    finally:
        db.close()

    def _raise_delivery_error(*_args, **_kwargs):
        raise RuntimeError("Twilio delivery failed: missing credentials")

    monkeypatch.setattr(
        "services.notification_delivery.NotificationDeliveryService.send_summary",
        _raise_delivery_error,
    )

    response = client.post("/notifications/summary/send-now")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "Summary delivery failed" in data["message"]


def test_scheduled_summary_dispatch_daily_once(monkeypatch):
    """Scheduled daily summary should send once per completed day window."""
    prefs_response = client.post(
        "/notifications/summary/preferences",
        json={
            "enabled": True,
            "frequency": "daily",
            "channel": "email",
            "recipient": "daily@example.com",
        },
    )
    assert prefs_response.status_code == 200

    db = TestingSessionLocal()
    try:
        storage = StorageService(db)
        order = storage.create_order(
            symbol="AAPL",
            side="buy",
            order_type="market",
            quantity=1.0,
        )
        # Falls into previous-day completed window for now=2026-02-14.
        trade = storage.trades.create(
            order_id=order.id,
            symbol="AAPL",
            side=OrderSideEnum.BUY,
            type=TradeTypeEnum.OPEN,
            quantity=1.0,
            price=180.0,
            executed_at=datetime(2026, 2, 13, 14, 0, 0, tzinfo=timezone.utc),
        )
        trade.realized_pnl = 3.5
        db.commit()

        sent_calls = {"count": 0}

        def _send(*_args, **_kwargs):
            sent_calls["count"] += 1
            return "Email sent to daily@example.com"

        monkeypatch.setattr(
            "services.notification_delivery.NotificationDeliveryService.send_summary",
            _send,
        )

        now = datetime(2026, 2, 14, 12, 0, 0, tzinfo=timezone.utc)
        first = api_routes._dispatch_scheduled_summary(storage=storage, now_utc=now)
        assert first["status"] == "sent"
        assert first["period_id"] == "2026-02-13"
        assert sent_calls["count"] == 1

        second = api_routes._dispatch_scheduled_summary(storage=storage, now_utc=now)
        assert second["status"] == "skipped"
        assert second["reason"] == "already_sent"
        assert sent_calls["count"] == 1
    finally:
        db.close()


def test_scheduled_summary_dispatch_retry_backoff(monkeypatch):
    """Scheduled summary should back off after failure and retry later."""
    prefs_response = client.post(
        "/notifications/summary/preferences",
        json={
            "enabled": True,
            "frequency": "weekly",
            "channel": "sms",
            "recipient": "+15551230000",
        },
    )
    assert prefs_response.status_code == 200

    db = TestingSessionLocal()
    try:
        storage = StorageService(db)
        order = storage.create_order(
            symbol="MSFT",
            side="buy",
            order_type="market",
            quantity=2.0,
        )
        # In completed week 2026-02-09 .. 2026-02-15 for now=2026-02-18.
        trade = storage.trades.create(
            order_id=order.id,
            symbol="MSFT",
            side=OrderSideEnum.BUY,
            type=TradeTypeEnum.OPEN,
            quantity=2.0,
            price=300.0,
            executed_at=datetime(2026, 2, 10, 10, 0, 0, tzinfo=timezone.utc),
        )
        trade.realized_pnl = -4.0
        db.commit()

        attempts = {"count": 0}

        def _flaky_send(*_args, **_kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("Twilio outage")
            return "SMS sent to +15551230000"

        monkeypatch.setattr(
            "services.notification_delivery.NotificationDeliveryService.send_summary",
            _flaky_send,
        )

        now = datetime(2026, 2, 18, 12, 0, 0, tzinfo=timezone.utc)
        first = api_routes._dispatch_scheduled_summary(storage=storage, now_utc=now)
        assert first["status"] == "failed"
        assert attempts["count"] == 1

        second = api_routes._dispatch_scheduled_summary(storage=storage, now_utc=now)
        assert second["status"] == "skipped"
        assert second["reason"] == "retry_backoff"
        assert attempts["count"] == 1

        later = now + timedelta(seconds=1900)
        third = api_routes._dispatch_scheduled_summary(storage=storage, now_utc=later)
        assert third["status"] == "sent"
        assert attempts["count"] == 2
    finally:
        db.close()


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


def test_get_runner_status_includes_poll_telemetry():
    """Runner status should always include poll telemetry fields."""
    response = client.get("/runner/status")
    assert response.status_code == 200
    data = response.json()
    assert "poll_success_count" in data
    assert "poll_error_count" in data
    assert "last_poll_error" in data
    assert "last_poll_at" in data
    assert "last_successful_poll_at" in data


def test_start_runner_no_strategies():
    """Test starting runner with no strategies."""
    response = client.post("/runner/start")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] == False
    assert "no active strategies" in data["message"].lower()


def test_start_runner_workspace_universe_override(monkeypatch):
    """Runner start should scope workspace universe symbols to the requested strategy."""
    captured: dict[str, object] = {}

    class _DummyBroker:
        def get_account_info(self):
            return {"equity": 10000.0, "buying_power": 10000.0}

    def _fake_resolve_workspace(**_kwargs):
        return (["AAPL", "MSFT", "INTC"], {"symbols_source": "workspace_universe"})

    def _fake_start_runner(**kwargs):
        captured["symbol_universe_overrides"] = kwargs.get("symbol_universe_overrides")
        return {"success": True, "message": "Runner started", "status": "running"}

    monkeypatch.setattr(api_routes, "get_broker", lambda: _DummyBroker())
    monkeypatch.setattr(api_routes, "_resolve_workspace_universe_for_backtest", _fake_resolve_workspace)
    monkeypatch.setattr(api_routes.runner_manager, "start_runner", _fake_start_runner)

    create_response = client.post("/strategies", json={"name": "Workspace Override Test", "symbols": ["AAPL"]})
    assert create_response.status_code == 200
    strategy_id = str(create_response.json()["id"])
    activate_response = client.put(f"/strategies/{strategy_id}", json={"status": "active"})
    assert activate_response.status_code == 200
    config_response = client.post("/config", json={"trading_enabled": True})
    assert config_response.status_code == 200

    response = client.post(
        "/runner/start",
        json={
            "use_workspace_universe": True,
            "target_strategy_id": strategy_id,
            "asset_type": "stock",
            "screener_mode": "preset",
            "stock_preset": "micro_budget",
            "preset_universe_mode": "seed_only",
            "screener_limit": 25,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert captured.get("symbol_universe_overrides") == {strategy_id: ["AAPL", "MSFT", "INTC"]}


def test_start_runner_workspace_universe_requires_target_strategy(monkeypatch):
    """Workspace universe runner starts must explicitly scope to one strategy."""
    class _DummyBroker:
        def get_account_info(self):
            return {"equity": 10000.0, "buying_power": 10000.0}

    monkeypatch.setattr(api_routes, "get_broker", lambda: _DummyBroker())

    response = client.post("/runner/start", json={"use_workspace_universe": True})
    assert response.status_code == 400
    assert "target_strategy_id is required" in response.json()["detail"]


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


def test_start_runner_blocked_when_trading_disabled_with_active_strategy():
    """Runner start should be blocked when trading is disabled and active strategies exist."""
    create_response = client.post("/strategies", json={
        "name": "Disabled Runner Test",
        "symbols": ["AAPL"],
    })
    strategy_id = create_response.json()["id"]
    client.put(f"/strategies/{strategy_id}", json={"status": "active"})
    client.post("/config", json={"trading_enabled": False})

    response = client.post("/runner/start")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert "trading is disabled" in payload["message"].lower()


def test_runner_idempotent_start():
    """Test that starting runner multiple times is idempotent."""
    # Start twice
    response1 = client.post("/runner/start")
    response2 = client.post("/runner/start")
    
    # Both should return 200
    assert response1.status_code == 200
    assert response2.status_code == 200


def test_maintenance_storage_and_cleanup(tmp_path):
    """Maintenance endpoints should expose storage config and perform cleanup."""
    log_dir = tmp_path / "logs"
    audit_dir = tmp_path / "audits"
    log_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)

    old_log = log_dir / "old.log"
    old_audit = audit_dir / "old.csv"
    old_log.write_text("old log")
    old_audit.write_text("old audit")
    old_ts = time.time() - (3 * 24 * 60 * 60)
    os.utime(old_log, (old_ts, old_ts))
    os.utime(old_audit, (old_ts, old_ts))

    cfg_response = client.post(
        "/config",
        json={
            "log_directory": str(log_dir),
            "audit_export_directory": str(audit_dir),
            "log_retention_days": 1,
            "audit_retention_days": 1,
        },
    )
    assert cfg_response.status_code == 200

    storage_response = client.get("/maintenance/storage")
    assert storage_response.status_code == 200
    storage_data = storage_response.json()
    assert storage_data["log_directory"] == str(log_dir.resolve())
    assert storage_data["audit_export_directory"] == str(audit_dir.resolve())
    assert "log_files" in storage_data
    assert "audit_files" in storage_data

    cleanup_response = client.post("/maintenance/cleanup")
    assert cleanup_response.status_code == 200
    cleanup_data = cleanup_response.json()
    assert cleanup_data["success"] is True
    assert cleanup_data["log_files_deleted"] >= 0
    assert cleanup_data["audit_files_deleted"] >= 0
    assert cleanup_data["optimization_rows_deleted"] >= 0
    assert not old_log.exists()
    assert not old_audit.exists()


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
    assert len(data["time_series"]) >= 1


def test_dashboard_analytics_bundle_endpoint():
    """Dashboard analytics bundle should include summary + analytics + broker account sections."""
    response = client.get("/analytics/dashboard?days=30")
    assert response.status_code == 200
    data = response.json()
    assert "generated_at" in data
    assert "summary" in data
    assert "analytics" in data
    assert "broker_account" in data
    assert "time_series" in data["analytics"]
    assert "equity" in data["summary"]


def test_normalize_portfolio_time_series_dedupes_identical_timestamps():
    """Time-series normalization should collapse duplicate timestamps to the latest row."""
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows = [
        {
            "timestamp": ts,
            "equity": 100000.0,
            "pnl": 5.0,
            "cumulative_pnl": 5.0,
            "symbol": "AAPL",
        },
        {
            "timestamp": ts,
            "equity": 100010.0,
            "pnl": 1.0,
            "cumulative_pnl": 6.0,
            "symbol": "MSFT",
        },
    ]

    normalized = api_routes._normalize_portfolio_time_series(rows)
    assert len(normalized) == 1
    assert abs(float(normalized[0]["equity"]) - 100010.0) < 1e-6
    assert abs(float(normalized[0]["pnl"]) - 1.0) < 1e-6
    assert abs(float(normalized[0]["cumulative_pnl"]) - 6.0) < 1e-6
    assert normalized[0]["symbol"] == "MSFT"


def test_analytics_days_filters_old_trades():
    """Ensure days parameter excludes older trades from curve and totals."""
    db = TestingSessionLocal()
    try:
        storage = StorageService(db)
        old_trade = storage.trades.create(
            order_id=1,
            symbol="AAPL",
            side=OrderSideEnum.BUY,
            type=TradeTypeEnum.OPEN,
            quantity=1,
            price=100.0,
            executed_at=datetime.now(timezone.utc) - timedelta(days=20),
        )
        old_trade.realized_pnl = 50.0

        new_trade = storage.trades.create(
            order_id=2,
            symbol="MSFT",
            side=OrderSideEnum.SELL,
            type=TradeTypeEnum.CLOSE,
            quantity=1,
            price=200.0,
            executed_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        new_trade.realized_pnl = 25.0
        db.commit()
    finally:
        db.close()

    response = client.get("/analytics/portfolio?days=7")
    assert response.status_code == 200
    data = response.json()

    assert data["total_trades"] == 1
    assert abs(data["total_pnl"] - 25.0) < 1e-6
    assert len(data["time_series"]) >= 1
    assert all("equity" in point for point in data["time_series"])


def test_analytics_returns_baseline_when_no_scoped_trades():
    """Analytics should still return one baseline point when scoped trade set is empty."""
    db = TestingSessionLocal()
    try:
        storage = StorageService(db)
        old_trade = storage.trades.create(
            order_id=1,
            symbol="AAPL",
            side=OrderSideEnum.BUY,
            type=TradeTypeEnum.OPEN,
            quantity=1,
            price=100.0,
            executed_at=datetime.now(timezone.utc) - timedelta(days=120),
        )
        old_trade.realized_pnl = 10.0
        db.commit()
    finally:
        db.close()

    response = client.get("/analytics/portfolio?days=7")
    assert response.status_code == 200
    data = response.json()
    assert data["total_trades"] == 0
    assert len(data["time_series"]) == 1
    assert data["time_series"][0]["symbol"] == "PORTFOLIO"
    assert abs(float(data["time_series"][0]["pnl"])) < 1e-6


def test_analytics_persists_snapshot_points():
    """Analytics should persist snapshot history and expose growing series."""
    first = client.get("/analytics/portfolio?days=7")
    assert first.status_code == 200
    first_data = first.json()
    first_len = len(first_data["time_series"])
    assert first_len >= 1

    second = client.get("/analytics/portfolio?days=7")
    assert second.status_code == 200
    second_data = second.json()
    second_len = len(second_data["time_series"])
    assert second_len >= first_len


def test_holdings_snapshot_uses_broker_truth_when_empty():
    """Broker empty-position response should not fall back to stale local rows."""
    db = TestingSessionLocal()
    try:
        storage = StorageService(db)
        storage.create_position(symbol="AAPL", side="long", quantity=5.0, avg_entry_price=100.0)

        class EmptyBroker:
            def get_positions(self):
                return []

        holdings = api_routes._load_holdings_snapshot(storage, EmptyBroker())  # type: ignore[arg-type]
        assert holdings == []
    finally:
        db.close()


def test_capture_portfolio_snapshot_filters_micro_drift_between_polls():
    """Repeated API polls should not persist extra rows for tiny quote drift."""
    db = TestingSessionLocal()
    try:
        storage = StorageService(db)

        class TinyDriftBroker:
            def __init__(self):
                self.tick = 0

            def is_market_open(self) -> bool:
                return True

            def get_account_info(self):
                drift = self.tick * 0.005
                return {
                    "equity": 1_000.0 + drift,
                    "cash": 500.0,
                    "buying_power": 2_000.0,
                }

            def get_positions(self):
                drift = self.tick * 0.005
                return [
                    {
                        "symbol": "SPY",
                        "quantity": 1.0,
                        "side": "long",
                        "avg_entry_price": 500.0,
                        "current_price": 500.0 + drift,
                        "market_value": 500.0 + drift,
                    }
                ]

        broker = TinyDriftBroker()
        first = api_routes._capture_portfolio_snapshot(storage, broker)  # type: ignore[arg-type]
        assert first is not None
        assert len(storage.get_recent_portfolio_snapshots(limit=100)) == 1

        broker.tick += 1
        second = api_routes._capture_portfolio_snapshot(storage, broker)  # type: ignore[arg-type]
        assert second is not None

        snapshots = storage.get_recent_portfolio_snapshots(limit=100)
        assert len(snapshots) == 1
        assert snapshots[0].equity == pytest.approx(float(first["equity"]))
    finally:
        db.close()


def test_capture_portfolio_snapshot_off_hours_ignores_transient_position_flicker():
    """Off-hours empty-position flicker should not persist a new snapshot row."""
    db = TestingSessionLocal()
    try:
        storage = StorageService(db)

        class FlickerBroker:
            def __init__(self):
                self.empty = False

            def is_market_open(self) -> bool:
                return False

            def get_account_info(self):
                return {
                    "equity": 1_000.0,
                    "cash": 500.0,
                    "buying_power": 2_000.0,
                }

            def get_positions(self):
                if self.empty:
                    return []
                return [
                    {
                        "symbol": "SPY",
                        "quantity": 1.0,
                        "side": "long",
                        "avg_entry_price": 500.0,
                        "current_price": 500.0,
                        "market_value": 500.0,
                    }
                ]

        broker = FlickerBroker()
        first = api_routes._capture_portfolio_snapshot(storage, broker)  # type: ignore[arg-type]
        assert first is not None
        assert len(storage.get_recent_portfolio_snapshots(limit=100)) == 1

        broker.empty = True
        second = api_routes._capture_portfolio_snapshot(storage, broker)  # type: ignore[arg-type]
        assert second is not None
        snapshots = storage.get_recent_portfolio_snapshots(limit=100)
        assert len(snapshots) == 1
        assert float(second["equity"]) == pytest.approx(float(first["equity"]))
    finally:
        db.close()


def test_normalize_portfolio_time_series_suppresses_transient_spike():
    """A short-lived A->B->A equity blip without PnL change should be dropped."""
    rows = [
        {
            "timestamp": datetime(2026, 2, 17, 10, 0, tzinfo=timezone.utc).isoformat(),
            "equity": 100000.0,
            "pnl": 0.0,
            "cumulative_pnl": 0.0,
            "symbol": "PORTFOLIO",
        },
        {
            "timestamp": datetime(2026, 2, 17, 10, 5, tzinfo=timezone.utc).isoformat(),
            "equity": 100180.0,
            "pnl": 0.0,
            "cumulative_pnl": 0.0,
            "symbol": "PORTFOLIO",
        },
        {
            "timestamp": datetime(2026, 2, 17, 10, 10, tzinfo=timezone.utc).isoformat(),
            "equity": 100000.0,
            "pnl": 0.0,
            "cumulative_pnl": 0.0,
            "symbol": "PORTFOLIO",
        },
    ]

    normalized = api_routes._normalize_portfolio_time_series(rows)
    assert len(normalized) == 2
    assert normalized[0]["equity"] == pytest.approx(100000.0)
    assert normalized[-1]["equity"] == pytest.approx(100000.0)


# ============================================================================
# Screener Preset Regression Tests
# ============================================================================

def test_screener_preset_micro_budget_stock_returns_assets():
    """micro_budget stock preset should be accepted by screener preset endpoint."""
    response = client.get(
        "/screener/preset",
        params={
            "asset_type": "stock",
            "preset": "micro_budget",
            "limit": 20,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["asset_type"] == "stock"
    assert isinstance(data["assets"], list)
    assert len(data["assets"]) > 0


def test_screener_all_preset_mode_uses_micro_budget_preference():
    """screener/all preset mode should not fail when stored stock_preset is micro_budget."""
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

    response = client.get(
        "/screener/all",
        params={
            "asset_type": "stock",
            "screener_mode": "preset",
            "limit": 20,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["asset_type"] == "stock"
    assert isinstance(data["assets"], list)
    assert len(data["assets"]) > 0


def test_screener_preset_seed_only_returns_seed_symbols_only():
    """seed_only=true should disable preset backfill from active universe."""
    response = client.get(
        "/screener/preset",
        params={
            "asset_type": "stock",
            "preset": "micro_budget",
            "limit": 50,
            "seed_only": "true",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["asset_type"] == "stock"
    seed_symbols = {"SPY", "INTC", "PFE", "CSCO", "KO", "VTI", "XLF", "DIS"}
    returned_symbols = {row["symbol"] for row in data["assets"]}
    assert returned_symbols
    assert returned_symbols.issubset(seed_symbols)
    assert data.get("applied_guardrails", {}).get("seed_only") is True


def test_screener_all_preset_seed_only_uses_seed_universe():
    """screener/all should pass seed_only through when running in preset mode."""
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

    response = client.get(
        "/screener/all",
        params={
            "asset_type": "stock",
            "screener_mode": "preset",
            "seed_only": "true",
            "limit": 50,
        },
    )
    assert response.status_code == 200
    data = response.json()
    seed_symbols = {"SPY", "INTC", "PFE", "CSCO", "KO", "VTI", "XLF", "DIS"}
    returned_symbols = {row["symbol"] for row in data["assets"]}
    assert returned_symbols
    assert returned_symbols.issubset(seed_symbols)
    assert data.get("applied_guardrails", {}).get("seed_only") is True


def test_screener_preset_guardrail_only_uses_active_universe_candidates():
    """preset_universe_mode=guardrail_only should not be constrained to seed symbols."""
    response = client.get(
        "/screener/preset",
        params={
            "asset_type": "stock",
            "preset": "micro_budget",
            "preset_universe_mode": "guardrail_only",
            "limit": 40,
        },
    )
    assert response.status_code == 200
    data = response.json()
    seed_symbols = {"SPY", "INTC", "PFE", "CSCO", "KO", "VTI", "XLF", "DIS"}
    returned_symbols = {row["symbol"] for row in data["assets"]}
    assert returned_symbols
    assert any(symbol not in seed_symbols for symbol in returned_symbols)
    assert data.get("applied_guardrails", {}).get("preset_universe_mode") == "guardrail_only"
    assert data.get("applied_guardrails", {}).get("seed_only") is False


def test_screener_all_preset_guardrail_only_passes_mode():
    """screener/all should accept preset_universe_mode and expose it in guardrails payload."""
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

    response = client.get(
        "/screener/all",
        params={
            "asset_type": "stock",
            "screener_mode": "preset",
            "preset_universe_mode": "guardrail_only",
            "limit": 40,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("applied_guardrails", {}).get("preset_universe_mode") == "guardrail_only"
    assert data.get("applied_guardrails", {}).get("seed_only") is False


def test_runner_preflight_returns_strategy_readiness():
    """Runner preflight should summarize symbol eligibility for active strategies."""
    created = client.post(
        "/strategies",
        json={
            "name": "Preflight Test",
            "symbols": ["AAPL", "MSFT"],
        },
    )
    assert created.status_code == 200
    strategy_id = created.json()["id"]

    activated = client.put(f"/strategies/{strategy_id}", json={"status": "active"})
    assert activated.status_code == 200

    response = client.get("/runner/preflight")
    assert response.status_code == 200
    payload = response.json()
    assert "runner_ready" in payload
    assert "strategies" in payload
    assert payload["summary"]["active_strategy_count"] >= 1
    first = payload["strategies"][0]
    assert first["symbol_count"] >= 1
    assert "symbols" in first
