"""
Targeted tests for backtest confidence reporting.
"""

from services.strategy_analytics import StrategyAnalyticsService


def _service_without_init() -> StrategyAnalyticsService:
    # Confidence builder is pure over diagnostics; no DB/storage needed.
    return StrategyAnalyticsService.__new__(StrategyAnalyticsService)


def test_backtest_confidence_uses_live_parity_requested_universe_size():
    service = _service_without_init()
    diagnostics = {
        "symbols_requested": 4,
        "symbols_with_data": 4,
        "entry_checks": 20,
        "entry_signals": 8,
        "entries_opened": 4,
        "blocked_reasons": {},
        "live_parity": {
            "strict_real_data_required": True,
            "data_provider": "alpaca",
            "symbol_capabilities_enforced": True,
            "slippage_model": "dynamic_bar_range",
            "fee_model": "fee_bps_plus_sec_taf_on_sells",
            "emulate_live_trading": True,
            # Universe size before live capability filtering.
            "symbols_requested": 40,
            "symbols_selected_for_entries": 10,
            "symbols_filtered_out_count": 30,
        },
    }

    report = service._build_backtest_confidence_report(
        diagnostics=diagnostics,
        total_trades=10,
    )

    assert report["data_coverage_pct"] == 10.0
    assert report["executable_universe_pct"] == 25.0
    assert report["symbols_filtered_out_count"] == 30


def test_backtest_confidence_penalizes_filtered_execution_universe():
    service = _service_without_init()
    base_diagnostics = {
        "symbols_requested": 40,
        "symbols_with_data": 40,
        "entry_checks": 30,
        "entry_signals": 12,
        "entries_opened": 8,
        "blocked_reasons": {},
        "live_parity": {
            "strict_real_data_required": True,
            "data_provider": "alpaca",
            "symbol_capabilities_enforced": True,
            "slippage_model": "dynamic_bar_range",
            "fee_model": "fee_bps_plus_sec_taf_on_sells",
            "emulate_live_trading": True,
            "symbols_requested": 40,
            "symbols_selected_for_entries": 40,
            "symbols_filtered_out_count": 0,
        },
    }

    full_universe = service._build_backtest_confidence_report(
        diagnostics=base_diagnostics,
        total_trades=10,
    )

    filtered_diagnostics = dict(base_diagnostics)
    filtered_live = dict(base_diagnostics["live_parity"])
    filtered_live["symbols_selected_for_entries"] = 10
    filtered_live["symbols_filtered_out_count"] = 30
    filtered_diagnostics["live_parity"] = filtered_live

    filtered_universe = service._build_backtest_confidence_report(
        diagnostics=filtered_diagnostics,
        total_trades=10,
    )

    assert filtered_universe["overall_confidence_score"] < full_universe["overall_confidence_score"]
    assert any("filtered out" in str(note).lower() for note in filtered_universe["notes"])
