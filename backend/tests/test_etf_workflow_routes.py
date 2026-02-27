"""Focused ETF workflow route integration tests after Scenario-2 pivot."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import app
from api import routes as api_routes
from storage.database import Base, get_db


SQLALCHEMY_DATABASE_URL = "sqlite:///./test_etf_workflow_routes.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)
DEFAULT_PREFS = api_routes._trading_preferences.model_copy(deep=True)


@pytest.fixture(autouse=True)
def setup_database():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=engine)
    api_routes._trading_preferences = DEFAULT_PREFS.model_copy(deep=True)
    with api_routes._market_screener_instances_lock:
        api_routes._market_screener_instances.clear()
    yield
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.pop(get_db, None)


def test_preferences_route_locks_workspace_to_etf_preset_mode():
    """ETF pivot should force workspace controls to ETF + preset."""
    response = client.post(
        "/preferences",
        json={
            "asset_type": "stock",
            "screener_mode": "most_active",
            "etf_preset": "aggressive",
            "weekly_budget": 100.0,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_type"] == "etf"
    assert payload["screener_mode"] == "preset"
    assert payload["etf_preset"] == "aggressive"
    assert payload["risk_profile"] == "aggressive"


def test_screener_all_rejects_non_etf_asset_type():
    response = client.get("/screener/all?asset_type=stock")
    assert response.status_code == 400
    assert "asset_type=etf only" in str(response.json().get("detail", "")).lower()


def test_screener_all_rejects_non_preset_mode():
    response = client.get("/screener/all?screener_mode=most_active")
    assert response.status_code == 400
    assert "screener_mode=preset only" in str(response.json().get("detail", "")).lower()


def test_screener_all_returns_assets_with_etf_workflow(monkeypatch):
    class _FakeScreener:
        def get_preset_guardrails(self, _asset_type: str, _preset: str):
            return {
                "min_dollar_volume": 5_000_000.0,
                "max_spread_bps": 80.0,
                "max_sector_weight_pct": 45.0,
            }

        def get_preset_assets(self, _asset_type: str, _preset: str, limit: int, **_kwargs):
            now = datetime.now(timezone.utc).isoformat()
            rows = [
                {
                    "symbol": "SPY",
                    "name": "SPDR S&P 500 ETF Trust",
                    "asset_type": "etf",
                    "volume": 10_000_000,
                    "price": 500.0,
                    "change_percent": 0.5,
                    "last_updated": now,
                    "sector": "broad_market",
                    "dollar_volume": 5_000_000_000.0,
                    "spread_bps": 2.0,
                },
                {
                    "symbol": "QQQ",
                    "name": "Invesco QQQ Trust",
                    "asset_type": "etf",
                    "volume": 8_000_000,
                    "price": 430.0,
                    "change_percent": 0.3,
                    "last_updated": now,
                    "sector": "technology",
                    "dollar_volume": 3_440_000_000.0,
                    "spread_bps": 3.0,
                },
            ]
            return rows[:limit]

        def get_last_preset_metadata(self):
            return {"seed_count": 2, "final_count": 2}

        def detect_market_regime(self):
            return "bull"

        def optimize_assets(self, assets, limit: int, **_kwargs):
            return list(assets)[:limit]

        def get_last_source(self):
            return "fallback"

    class _FakeGovernanceService:
        def __init__(self, _storage):
            pass

        def enforce(self, screener, assets, role, holdings_snapshot, force_screen=False):
            _ = (screener, role, holdings_snapshot, force_screen)
            symbols = [str(item.get("symbol", "")).upper() for item in assets]
            return SimpleNamespace(assets=list(assets), symbols=symbols, report={"mode": "test"})

    monkeypatch.setattr(api_routes, "_create_market_screener", lambda: _FakeScreener())
    monkeypatch.setattr(api_routes, "ETFInvestingGovernanceService", _FakeGovernanceService)

    response = client.get("/screener/all?asset_type=etf&screener_mode=preset&limit=25")
    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_type"] == "etf"
    assert payload["total_count"] == 2
    assert len(payload["assets"]) == 2
    assert payload["assets"][0]["symbol"] == "SPY"
    assert payload["applied_guardrails"]["resolved_screener_mode"] == "preset"
