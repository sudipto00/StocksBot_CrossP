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


@pytest.fixture(autouse=True)
def setup_database():
    """Create and drop test database for each test."""
    app.dependency_overrides[get_db] = override_get_db
    _reset_runtime_singletons()
    Base.metadata.create_all(bind=engine)
    yield
    _reset_runtime_singletons()
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
