"""Shared defaults for ETF-investing pivot workflows."""

from __future__ import annotations

import os
from typing import Any, Dict

ETF_INVESTING_MODE_ENABLED_DEFAULT = False
ETF_INVESTING_AUTO_ENABLED_DEFAULT = True
ETF_INVESTING_CORE_DCA_PCT_DEFAULT = 80.0
ETF_INVESTING_ACTIVE_SLEEVE_PCT_DEFAULT = 20.0
ETF_INVESTING_MAX_TRADES_PER_DAY_DEFAULT = 1
ETF_INVESTING_MAX_CONCURRENT_POSITIONS_DEFAULT = 1
ETF_INVESTING_MAX_SYMBOL_EXPOSURE_PCT_DEFAULT = 15.0
ETF_INVESTING_MAX_TOTAL_EXPOSURE_PCT_DEFAULT = 70.0
ETF_INVESTING_SINGLE_POSITION_EQUITY_THRESHOLD_DEFAULT = 1000.0
ETF_INVESTING_DAILY_LOSS_LIMIT_PCT_DEFAULT = 1.0
ETF_INVESTING_WEEKLY_LOSS_LIMIT_PCT_DEFAULT = 3.0
ETF_INVESTING_WEEKLY_CONTRIBUTION_DEFAULT = 50.0
ETF_INVESTING_EVAL_MIN_TRADES = 50
ETF_INVESTING_EVAL_MIN_MONTHS = 18

SCENARIO2_ALPHA_MIN_PCT_DEFAULT = 2.0
SCENARIO2_MAX_DRAWDOWN_PCT_DEFAULT = 25.0
SCENARIO2_MAX_SELLS_PER_MONTH_DEFAULT = 6.0
SCENARIO2_MAX_SHORT_TERM_SELL_RATIO_DEFAULT = 0.60

ETF_INVESTING_CORE_SYMBOLS = ("SPY", "QQQ", "VTI", "BND")
ETF_INVESTING_OPTIONAL_ETF_SYMBOLS = ("IWM", "XLK", "XLV", "AGG", "IEF", "GLD")
ETF_INVESTING_ALLOWED_SYMBOLS = tuple(
    dict.fromkeys(ETF_INVESTING_CORE_SYMBOLS + ETF_INVESTING_OPTIONAL_ETF_SYMBOLS).keys()
)

ETF_DCA_BENCHMARK_WEIGHTS = {
    "SPY": 0.60,
    "QQQ": 0.40,
}

ETF_INVESTING_GOVERNANCE_SCREEN_INTERVAL_DAYS_DEFAULT = 30
ETF_INVESTING_GOVERNANCE_REPLACEMENT_INTERVAL_DAYS_DEFAULT = 90
ETF_INVESTING_GOVERNANCE_MAX_REPLACEMENTS_PER_QUARTER_DEFAULT = 1
ETF_INVESTING_GOVERNANCE_MIN_HOLD_DAYS_DEFAULT = 180
ETF_INVESTING_GOVERNANCE_MIN_SCORE_DELTA_PCT_DEFAULT = 20.0
ETF_INVESTING_GOVERNANCE_MIN_DOLLAR_VOLUME_DEFAULT = 50_000_000.0
ETF_INVESTING_GOVERNANCE_MIN_HISTORY_DAYS_PREFERRED = 252 * 3
ETF_INVESTING_GOVERNANCE_REBALANCE_DRIFT_THRESHOLD_PCT_DEFAULT = 5.0
ETF_INVESTING_GOVERNANCE_BUY_ONLY_REBALANCE_DEFAULT = True
ETF_INVESTING_TLH_ENABLED_DEFAULT = False
ETF_INVESTING_TLH_MIN_LOSS_DOLLARS_DEFAULT = 250.0
ETF_INVESTING_TLH_MIN_LOSS_PCT_DEFAULT = 5.0
ETF_INVESTING_TLH_MIN_HOLD_DAYS_DEFAULT = 30
ETF_INVESTING_WASH_SALE_WINDOW_DAYS = 30
ETF_INVESTING_TRADING_WINDOW_START_ET = "09:35"
ETF_INVESTING_TRADING_WINDOW_END_ET = "15:45"
ETF_INVESTING_TLH_REPLACEMENT_MAP = {
    "SPY": "VTI",
    "VTI": "SPY",
    "QQQ": "VTI",
    "BND": "AGG",
    "AGG": "BND",
    "IEF": "BND",
}

ETF_INVESTING_ALLOW_LIST_DEFAULT = (
    {"symbol": "SPY", "role": "both", "max_weight_pct": 60.0, "min_trade_size": 1.0, "enabled": True},
    {"symbol": "QQQ", "role": "both", "max_weight_pct": 40.0, "min_trade_size": 1.0, "enabled": True},
    {"symbol": "VTI", "role": "dca", "max_weight_pct": 65.0, "min_trade_size": 1.0, "enabled": True},
    {"symbol": "BND", "role": "dca", "max_weight_pct": 35.0, "min_trade_size": 1.0, "enabled": True},
    {"symbol": "IWM", "role": "active", "max_weight_pct": 15.0, "min_trade_size": 1.0, "enabled": True},
    {"symbol": "XLK", "role": "active", "max_weight_pct": 15.0, "min_trade_size": 1.0, "enabled": True},
    {"symbol": "XLV", "role": "active", "max_weight_pct": 15.0, "min_trade_size": 1.0, "enabled": True},
    {"symbol": "AGG", "role": "dca", "max_weight_pct": 35.0, "min_trade_size": 1.0, "enabled": True},
    {"symbol": "IEF", "role": "dca", "max_weight_pct": 20.0, "min_trade_size": 1.0, "enabled": True},
    {"symbol": "GLD", "role": "active", "max_weight_pct": 10.0, "min_trade_size": 1.0, "enabled": False},
)


def _env_float(name: str, default: float, *, min_value: float, max_value: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return float(default)
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return float(default)
    if not parsed == parsed:  # NaN guard
        return float(default)
    return float(max(min_value, min(max_value, parsed)))


def _env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return int(default)
    try:
        parsed = int(float(raw))
    except (TypeError, ValueError):
        return int(default)
    return int(max(min_value, min(max_value, parsed)))


def get_scenario2_thresholds() -> Dict[str, Any]:
    """
    Runtime Scenario-2 readiness thresholds.

    Allows deploy-time tuning via environment variables:
    - STOCKSBOT_SCENARIO2_ALPHA_MIN_PCT
    - STOCKSBOT_SCENARIO2_MAX_DRAWDOWN_PCT
    - STOCKSBOT_SCENARIO2_MIN_TRADES
    - STOCKSBOT_SCENARIO2_MIN_MONTHS
    - STOCKSBOT_SCENARIO2_MAX_SELLS_PER_MONTH
    - STOCKSBOT_SCENARIO2_MAX_SHORT_TERM_SELL_RATIO
    """
    return {
        "alpha_min_pct": _env_float(
            "STOCKSBOT_SCENARIO2_ALPHA_MIN_PCT",
            SCENARIO2_ALPHA_MIN_PCT_DEFAULT,
            min_value=-20.0,
            max_value=20.0,
        ),
        "max_drawdown_pct": _env_float(
            "STOCKSBOT_SCENARIO2_MAX_DRAWDOWN_PCT",
            SCENARIO2_MAX_DRAWDOWN_PCT_DEFAULT,
            min_value=1.0,
            max_value=80.0,
        ),
        "min_trades": _env_int(
            "STOCKSBOT_SCENARIO2_MIN_TRADES",
            ETF_INVESTING_EVAL_MIN_TRADES,
            min_value=0,
            max_value=2000,
        ),
        "min_months": _env_float(
            "STOCKSBOT_SCENARIO2_MIN_MONTHS",
            float(ETF_INVESTING_EVAL_MIN_MONTHS),
            min_value=0.0,
            max_value=120.0,
        ),
        "max_sells_per_month": _env_float(
            "STOCKSBOT_SCENARIO2_MAX_SELLS_PER_MONTH",
            SCENARIO2_MAX_SELLS_PER_MONTH_DEFAULT,
            min_value=0.1,
            max_value=60.0,
        ),
        "max_short_term_sell_ratio": _env_float(
            "STOCKSBOT_SCENARIO2_MAX_SHORT_TERM_SELL_RATIO",
            SCENARIO2_MAX_SHORT_TERM_SELL_RATIO_DEFAULT,
            min_value=0.0,
            max_value=1.0,
        ),
    }
