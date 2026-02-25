"""
Targeted tests for execution realism simulation primitives.
"""

import random

from services.strategy_analytics import StrategyAnalyticsService


def _service_without_init() -> StrategyAnalyticsService:
    # Execution helpers are pure and do not require DB/storage state.
    return StrategyAnalyticsService.__new__(StrategyAnalyticsService)


def test_execution_fill_caps_entry_quantity_by_participation_limit():
    service = _service_without_init()

    fill = service._simulate_execution_fill(
        side="buy",
        order_style="entry_market",
        open_price=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        daily_volume=10_000.0,
        requested_notional=None,
        requested_qty=500.0,
        fee_bps=0.0,
        base_slippage_bps=5.0,
        emulate_live=True,
        latency_ms=250.0,
        queue_position_bps=6.0,
        max_participation_rate=0.01,  # 100 shares capacity
        simulate_queue_position=True,
        enforce_liquidity_limits=True,
        allow_partial=True,
        rng=random.Random(7),
        reconcile_fees_with_broker=True,
    )

    assert fill["liquidity_limited"] is True
    assert fill["filled_qty"] <= 100.000001
    assert fill["filled_qty"] > 0


def test_execution_fill_forced_exit_still_fills_with_penalty_when_over_capacity():
    service = _service_without_init()

    fill = service._simulate_execution_fill(
        side="sell",
        order_style="stop_exit",
        open_price=100.0,
        high=101.0,
        low=95.0,
        close=96.0,
        daily_volume=5_000.0,
        requested_notional=None,
        requested_qty=500.0,
        fee_bps=0.0,
        base_slippage_bps=5.0,
        emulate_live=True,
        latency_ms=300.0,
        queue_position_bps=7.0,
        max_participation_rate=0.01,  # 50 shares capacity
        simulate_queue_position=True,
        enforce_liquidity_limits=True,
        allow_partial=False,
        rng=random.Random(11),
        reconcile_fees_with_broker=True,
    )

    assert fill["liquidity_limited"] is True
    assert fill["filled_qty"] == 500.0
    assert fill["effective_slippage_bps"] > 5.0


def test_fee_reconciliation_applies_broker_style_rounding():
    service = _service_without_init()

    fee = service._estimate_trade_fees(
        side="sell",
        notional=12_345.0,
        quantity=10.0,
        fee_bps=0.0,
        emulate_live=True,
        reconcile_fees_with_broker=True,
    )

    # SEC: round(12345 * 0.000008, 2) = 0.10
    # TAF: round(max(0.01, 10 * 0.000166), 2) = 0.01
    assert fee == 0.11
