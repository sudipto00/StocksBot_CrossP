"""Scenario-2 threshold configuration regression tests."""

from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.investing_defaults import get_scenario2_thresholds
from services.strategy_analytics import StrategyAnalyticsService


def test_scenario2_threshold_env_override_and_clamp(monkeypatch):
    monkeypatch.setenv("STOCKSBOT_SCENARIO2_ALPHA_MIN_PCT", "4.2")
    monkeypatch.setenv("STOCKSBOT_SCENARIO2_MAX_DRAWDOWN_PCT", "120")  # clamp -> 80
    monkeypatch.setenv("STOCKSBOT_SCENARIO2_MIN_TRADES", "-5")  # clamp -> 0
    monkeypatch.setenv("STOCKSBOT_SCENARIO2_MIN_MONTHS", "24")
    monkeypatch.setenv("STOCKSBOT_SCENARIO2_MAX_SELLS_PER_MONTH", "3.5")
    monkeypatch.setenv("STOCKSBOT_SCENARIO2_MAX_SHORT_TERM_SELL_RATIO", "1.5")  # clamp -> 1.0

    thresholds = get_scenario2_thresholds()
    assert thresholds["alpha_min_pct"] == 4.2
    assert thresholds["max_drawdown_pct"] == 80.0
    assert thresholds["min_trades"] == 0
    assert thresholds["min_months"] == 24.0
    assert thresholds["max_sells_per_month"] == 3.5
    assert thresholds["max_short_term_sell_ratio"] == 1.0


def test_scenario2_report_uses_runtime_thresholds(monkeypatch):
    monkeypatch.setenv("STOCKSBOT_SCENARIO2_ALPHA_MIN_PCT", "8.0")
    monkeypatch.setenv("STOCKSBOT_SCENARIO2_MAX_DRAWDOWN_PCT", "5.0")
    monkeypatch.setenv("STOCKSBOT_SCENARIO2_MIN_TRADES", "20")
    monkeypatch.setenv("STOCKSBOT_SCENARIO2_MIN_MONTHS", "18")
    monkeypatch.setenv("STOCKSBOT_SCENARIO2_MAX_SELLS_PER_MONTH", "2.0")
    monkeypatch.setenv("STOCKSBOT_SCENARIO2_MAX_SHORT_TERM_SELL_RATIO", "0.25")

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        service = StrategyAnalyticsService(db)
        report = service._build_scenario2_report(
            start_date=date(2024, 1, 1),
            end_date=date(2025, 12, 31),
            initial_capital=10000.0,
            contribution_amount=0.0,
            contribution_frequency="none",
            contribution_dates=[],
            total_contributions=0.0,
            final_capital=10800.0,
            benchmark_final_capital=10600.0,
            xirr_pct=0.0,
            benchmark_xirr_pct=0.0,
            xirr_excess_pct=0.0,
            equity_curve=[
                {"timestamp": "2024-01-02T00:00:00Z", "equity": 10000.0},
                {"timestamp": "2024-06-02T00:00:00Z", "equity": 9800.0},
                {"timestamp": "2024-12-02T00:00:00Z", "equity": 10400.0},
                {"timestamp": "2025-06-02T00:00:00Z", "equity": 10100.0},
                {"timestamp": "2025-12-30T00:00:00Z", "equity": 10800.0},
            ],
            trades=[
                {"pnl": 40.0, "days_held": 30, "exit_date": "2024-01-20"},
                {"pnl": -20.0, "days_held": 22, "exit_date": "2024-02-11"},
                {"pnl": 35.0, "days_held": 40, "exit_date": "2024-03-12"},
                {"pnl": 22.0, "days_held": 25, "exit_date": "2024-04-10"},
                {"pnl": 15.0, "days_held": 15, "exit_date": "2024-05-18"},
                {"pnl": -10.0, "days_held": 18, "exit_date": "2024-06-14"},
                {"pnl": 26.0, "days_held": 27, "exit_date": "2024-07-09"},
                {"pnl": -14.0, "days_held": 20, "exit_date": "2024-08-22"},
                {"pnl": 18.0, "days_held": 33, "exit_date": "2024-09-24"},
                {"pnl": 12.0, "days_held": 19, "exit_date": "2024-10-29"},
                {"pnl": 16.0, "days_held": 16, "exit_date": "2024-11-21"},
                {"pnl": -8.0, "days_held": 12, "exit_date": "2024-12-18"},
            ],
            diagnostics={
                "trading_days_evaluated": 400,
                "execution_summary": {"entry_fills": 12, "exit_fills": 12, "average_effective_slippage_bps": 6.0},
                "universe_context": {"short_term_tax_rate": 0.3, "long_term_tax_rate": 0.15},
            },
            investing_core_dca_pct=80.0,
            investing_active_sleeve_pct=20.0,
            active_exposure_samples=[],
            total_exposure_samples=[],
            concentration_samples=[],
            no_activity_days=120,
        )
    finally:
        db.close()
        engine.dispose()

    readiness = report["readiness"]
    thresholds = readiness["thresholds"]
    assert thresholds["alpha_min_pct"] == 8.0
    assert thresholds["max_drawdown_pct"] == 5.0
    assert thresholds["min_trades"] == 20
    assert thresholds["min_months"] == 18.0
    assert thresholds["max_sells_per_month"] == 2.0
    assert thresholds["max_short_term_sell_ratio"] == 0.25
    assert readiness["minimum_trades_required"] == 20
    assert readiness["minimum_months_required"] == 18.0
    assert readiness["gate_results"]["minimum_trades"] is False
    assert readiness["status"] in {"inconclusive", "fail"}
