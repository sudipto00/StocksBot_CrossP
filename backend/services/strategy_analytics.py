"""
Strategy Analytics Service.
Provides functionality for calculating strategy metrics, backtesting,
and performance analysis.
"""
from typing import List, Dict, Any, Optional, Callable, Tuple
from datetime import datetime, timedelta, timezone, date as date_type
import hashlib
import math
import random as _random_mod
import statistics
from sqlalchemy.orm import Session

from storage.service import StorageService
from config.strategy_config import (
    StrategyMetrics,
    BacktestRequest,
    BacktestResult,
)
from config.investing_defaults import (
    ETF_DCA_BENCHMARK_WEIGHTS,
    ETF_INVESTING_EVAL_MIN_MONTHS,
    ETF_INVESTING_EVAL_MIN_TRADES,
    get_scenario2_thresholds,
)
from engine.risk_manager import RiskManager
from services.market_screener import MarketScreener

# Default slippage applied to each fill (basis points).
_DEFAULT_SLIPPAGE_BPS = 5.0


class BacktestCancelledError(RuntimeError):
    """Raised when a caller requests backtest cancellation."""


def compute_risk_based_position_size(
    equity: float,
    risk_per_trade_pct: float,
    stop_loss_pct: float,
    position_size_cap: float,
    cash: float,
) -> float:
    """Shared position-sizing logic used by both backtest and live runner.

    Sizes the position so that a full stop-loss hit equals the intended
    risk-per-trade dollar amount: position = risk_dollars / stop_loss_pct.
    The result is further capped by the requested position_size, available
    cash, and a 10%-of-equity guardrail.
    """
    risk_pct = max(0.1, min(5.0, risk_per_trade_pct))
    sl_pct = max(0.5, min(10.0, stop_loss_pct))
    caps: list[float] = [position_size_cap]
    if equity > 0:
        risk_dollars = equity * (risk_pct / 100.0)
        caps.append(max(50.0, risk_dollars / (sl_pct / 100.0)))
        caps.append(max(75.0, equity * 0.10))
    if cash > 0:
        caps.append(cash)
    sized = min(caps)
    return max(25.0, round(sized, 2))


class StrategyAnalyticsService:
    """Service for strategy analytics and backtesting."""

    def __init__(
        self,
        db: Session,
        alpaca_creds: Optional[Dict[str, str]] = None,
        require_real_data: bool = False,
    ):
        self.db = db
        self.storage = StorageService(db)
        self._alpaca_creds = alpaca_creds
        self._require_real_data = bool(require_real_data)
        # In-process cache to avoid repeated historical bar pulls during
        # optimization/backtest loops for the same symbol window.
        self._historical_bars_cache: Dict[str, List[Dict[str, Any]]] = {}

    def get_strategy_metrics(self, strategy_id: int) -> StrategyMetrics:
        """
        Calculate real-time performance metrics for a strategy.

        Args:
            strategy_id: ID of the strategy

        Returns:
            StrategyMetrics with calculated performance data
        """
        trades = self.storage.get_trades_by_strategy(strategy_id)

        if not trades:
            return StrategyMetrics(
                strategy_id=str(strategy_id),
                win_rate=0.0,
                volatility=0.0,
                drawdown=0.0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                total_pnl=0.0,
                sharpe_ratio=None,
            )

        total_trades = len(trades)
        winning_trades = len([t for t in trades if (t.realized_pnl or 0.0) > 0])
        losing_trades = len([t for t in trades if (t.realized_pnl or 0.0) < 0])
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
        total_pnl = sum(t.realized_pnl or 0.0 for t in trades)

        # Use percentage returns instead of raw dollar P&L for meaningful
        # volatility and Sharpe calculations.
        pct_returns: List[float] = []
        for t in trades:
            pnl = t.realized_pnl
            if pnl is None:
                continue
            cost_basis = 0.0
            qty = getattr(t, "quantity", 0.0) or 0.0
            price = getattr(t, "price", 0.0) or 0.0
            cost_basis = qty * price if qty > 0 and price > 0 else 0.0
            if cost_basis > 0:
                pct_returns.append(pnl / cost_basis)
            elif pnl != 0:
                pct_returns.append(0.0)

        volatility = self._calculate_annualized_volatility(pct_returns)

        # Compute drawdown from actual account snapshots if available,
        # otherwise fall back to trade-based estimate using actual equity.
        drawdown = self._calculate_drawdown_from_trades(trades)

        sharpe_ratio = self._calculate_sharpe_ratio(pct_returns) if pct_returns else None

        return StrategyMetrics(
            strategy_id=str(strategy_id),
            win_rate=win_rate,
            volatility=volatility,
            drawdown=drawdown,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            total_pnl=total_pnl,
            sharpe_ratio=sharpe_ratio,
        )

    def run_backtest(
        self,
        request: BacktestRequest,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> BacktestResult:
        """
        Run a deterministic historical backtest for a strategy.

        Args:
            request: Backtest configuration

        Returns:
            BacktestResult with deterministic performance data
        """
        start_dt = datetime.fromisoformat(request.start_date.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(request.end_date.replace("Z", "+00:00"))
        if end_dt < start_dt:
            raise ValueError("end_date must be greater than or equal to start_date")

        symbols = self._normalize_symbols(request.symbols or ["AAPL", "MSFT"])
        if not symbols:
            symbols = ["AAPL", "MSFT"]

        params = self._resolve_backtest_parameters(request.parameters or {})
        initial_capital = float(request.initial_capital)
        contribution_amount = max(0.0, float(getattr(request, "contribution_amount", 0.0) or 0.0))
        contribution_frequency = str(getattr(request, "contribution_frequency", "none") or "none").strip().lower()
        if contribution_frequency not in {"none", "weekly", "monthly"}:
            contribution_frequency = "none"
        if contribution_amount <= 0:
            contribution_frequency = "none"
        micro_strategy_mode = str(getattr(request, "micro_strategy_mode", "auto") or "auto").strip().lower()
        if micro_strategy_mode not in {"off", "auto", "on"}:
            micro_strategy_mode = "auto"
        micro_equity_threshold = max(
            100.0,
            float(getattr(request, "micro_equity_threshold", 2500.0) or 2500.0),
        )
        micro_single_trade_loss_pct = max(
            0.1,
            min(10.0, float(getattr(request, "micro_single_trade_loss_pct", 1.5) or 1.5)),
        )
        micro_cash_reserve_pct = max(
            0.0,
            min(50.0, float(getattr(request, "micro_cash_reserve_pct", 5.0) or 5.0)),
        )
        micro_max_spread_bps = max(
            1.0,
            min(300.0, float(getattr(request, "micro_max_spread_bps", 40.0) or 40.0)),
        )
        preset_hint = ""
        if isinstance(request.universe_context, dict):
            preset_hint = str(request.universe_context.get("preset", "") or "").strip().lower()
        recurring_profile = contribution_frequency in {"weekly", "monthly"} and contribution_amount > 0
        auto_micro = (
            initial_capital <= micro_equity_threshold
            or (recurring_profile and initial_capital <= (micro_equity_threshold * 1.5))
            or preset_hint == "micro_budget"
        )
        if micro_strategy_mode == "on":
            micro_policy_active = True
            micro_policy_reason = "request_mode_on"
        elif micro_strategy_mode == "off":
            micro_policy_active = False
            micro_policy_reason = "request_mode_off"
        else:
            micro_policy_active = bool(auto_micro)
            micro_policy_reason = "auto_triggered" if auto_micro else "auto_not_triggered"
        live_parity_ctx = {}
        if isinstance(request.universe_context, dict):
            candidate_ctx = request.universe_context.get("live_parity_context")
            if isinstance(candidate_ctx, dict):
                live_parity_ctx = candidate_ctx
        investing_policy_ctx = {}
        if isinstance(live_parity_ctx.get("investing_policy"), dict):
            investing_policy_ctx = dict(live_parity_ctx.get("investing_policy") or {})
        investing_policy_active = bool(
            live_parity_ctx.get("investing_policy_active", False)
            or investing_policy_ctx.get("active", False)
        )
        investing_policy_reason = str(
            live_parity_ctx.get("investing_policy_reason")
            or investing_policy_ctx.get("reason")
            or ("active" if investing_policy_active else "inactive")
        )
        investing_param_overrides: Dict[str, Any] = {
            "active": False,
            "adjusted_fields": [],
        }
        if investing_policy_active:
            params, investing_param_overrides = self._apply_investing_parameter_overrides(params)

        investing_core_dca_pct = max(
            50.0,
            min(95.0, float(investing_policy_ctx.get("core_dca_pct", 80.0) or 80.0)),
        )
        investing_active_sleeve_pct = max(
            5.0,
            min(50.0, float(investing_policy_ctx.get("active_sleeve_pct", 20.0) or 20.0)),
        )
        investing_max_positions = max(
            1,
            int(investing_policy_ctx.get("max_concurrent_positions", 1) or 1),
        )
        contribution_anchor_weekday = start_dt.date().weekday()
        contribution_anchor_day = start_dt.date().day
        total_contributions = 0.0
        contribution_events = 0
        contribution_dates: List[date_type] = []
        cash = initial_capital
        trade_id = 1
        emulate_live_trading = bool(request.emulate_live_trading)
        require_fractionable = bool(request.require_fractionable)
        symbol_capabilities = request.symbol_capabilities if isinstance(request.symbol_capabilities, dict) else {}
        max_position_size = max(1.0, float(request.max_position_size or params.get("position_size", 1000.0)))
        daily_risk_limit = max(1.0, float(request.risk_limit_daily or max(50.0, initial_capital * 0.05)))
        fee_bps = max(0.0, float(request.fee_bps or 0.0))
        execution_latency_ms = max(0.0, float(getattr(request, "execution_latency_ms", 220.0) or 0.0))
        queue_position_bps = max(0.0, float(getattr(request, "queue_position_bps", 6.0) or 0.0))
        max_participation_rate = max(
            0.001,
            min(0.5, float(getattr(request, "max_participation_rate", 0.03) or 0.03)),
        )
        simulate_queue_position = bool(getattr(request, "simulate_queue_position", emulate_live_trading))
        enforce_liquidity_limits = bool(getattr(request, "enforce_liquidity_limits", emulate_live_trading))
        reconcile_fees_with_broker = bool(getattr(request, "reconcile_fees_with_broker", emulate_live_trading))
        execution_seed = self._resolve_execution_seed(
            request=request,
            symbols=symbols,
            params=params,
        )
        execution_rng = _random_mod.Random(execution_seed)
        # Monte Carlo price noise: per-bar multiplicative Gaussian noise.
        price_noise_bps = max(0.0, float(getattr(request, "price_noise_bps", 0.0) or 0.0))
        _price_noise_rng: Optional[_random_mod.Random] = None
        if price_noise_bps > 0:
            _price_noise_seed = getattr(request, "price_noise_seed", None)
            _price_noise_rng = _random_mod.Random(_price_noise_seed)
        risk_manager = RiskManager(
            max_position_size=max_position_size,
            daily_loss_limit=daily_risk_limit,
            max_portfolio_exposure=max(initial_capital * 2.0, max_position_size * 25.0),
            max_symbol_concentration_pct=45.0,
            max_open_positions=25,
            max_consecutive_losses=max(1, int(params.get("max_consecutive_losses", 3))),
            max_drawdown_pct=max(1.0, float(params.get("max_drawdown_pct", 15.0))),
        )
        risk_manager.update_equity(initial_capital)
        diagnostics: Dict[str, Any] = {
            "symbols_requested": len(symbols),
            "symbols_with_data": 0,
            "symbols_without_data": [],
            "symbol_data_errors": [],
            "trading_days_evaluated": 0,
            "bars_evaluated": 0,
            "entry_checks": 0,
            "entry_signals": 0,
            "entries_opened": 0,
            "blocked_reasons": {
                "insufficient_history": 0,
                "no_dip_signal": 0,
                "regime_filtered": 0,
                "already_in_position": 0,
                "risk_cap_too_low": 0,
                "invalid_position_size": 0,
                "cash_insufficient": 0,
                "micro_single_trade_loss": 0,
                "micro_cash_reserve": 0,
                "micro_spread_guardrail": 0,
                "investing_trend_filter": 0,
                "investing_max_positions": 0,
                "investing_core_unavailable": 0,
                "not_tradable": 0,
                "not_fractionable": 0,
                "liquidity_no_fill": 0,
                "daily_risk_limit": 0,
                "risk_circuit_breaker": 0,
                "risk_validation_failed": 0,
            },
            "exit_reasons": {
                "stop_exit": 0,
                "take_profit_exit": 0,
                "time_exit": 0,
                "end_of_backtest": 0,
            },
            "parameters_used": {k: float(v) for k, v in params.items()},
            "emulate_live_trading": emulate_live_trading,
            "require_fractionable": require_fractionable,
            "max_position_size_applied": max_position_size,
            "risk_limit_daily_applied": daily_risk_limit,
            "fee_bps_applied": fee_bps,
            "execution_latency_ms": execution_latency_ms,
            "queue_position_bps": queue_position_bps,
            "max_participation_rate": max_participation_rate,
            "simulate_queue_position": simulate_queue_position,
            "enforce_liquidity_limits": enforce_liquidity_limits,
            "reconcile_fees_with_broker": reconcile_fees_with_broker,
            "execution_seed": execution_seed,
            "contribution_amount": contribution_amount,
            "contribution_frequency": contribution_frequency,
            "micro_strategy_mode": micro_strategy_mode,
            "micro_policy_active": micro_policy_active,
            "micro_policy_reason": micro_policy_reason,
            "micro_equity_threshold": micro_equity_threshold,
            "micro_single_trade_loss_pct": micro_single_trade_loss_pct,
            "micro_cash_reserve_pct": micro_cash_reserve_pct,
            "micro_max_spread_bps": micro_max_spread_bps,
            "investing_policy_active": investing_policy_active,
            "investing_policy_reason": investing_policy_reason,
            "investing_policy": dict(investing_policy_ctx),
            "investing_parameter_overrides": dict(investing_param_overrides),
            "investing_core_dca_pct": investing_core_dca_pct,
            "investing_active_sleeve_pct": investing_active_sleeve_pct,
            "contribution_events": 0,
            "capital_contributions_total": 0.0,
            "partial_entry_fills": 0,
            "execution_summary": {
                "fills": 0,
                "entry_fills": 0,
                "exit_fills": 0,
                "liquidity_capped_fills": 0,
                "effective_slippage_bps_sum": 0.0,
                "effective_latency_ms_sum": 0.0,
                "queue_penalty_bps_sum": 0.0,
                "impact_bps_sum": 0.0,
                "spread_bps_sum": 0.0,
                "filled_notional_total": 0.0,
                "entry_notional_total": 0.0,
                "fees_total": 0.0,
                "participation_rate_sum": 0.0,
            },
        }
        if isinstance(request.universe_context, dict) and request.universe_context:
            diagnostics["universe_context"] = dict(request.universe_context)

        lookback_days = max(320, (end_dt.date() - start_dt.date()).days + 320)
        screener = MarketScreener(
            alpaca_client=self._alpaca_creds,
            require_real_data=self._require_real_data,
        )
        cancel_check_counter = 0

        def _check_cancel() -> None:
            nonlocal cancel_check_counter
            if should_cancel is None:
                return
            cancel_check_counter += 1
            # Avoid callback overhead on every micro-step while still staying responsive.
            if cancel_check_counter % 8 != 0:
                return
            if should_cancel():
                raise BacktestCancelledError("Backtest canceled")

        series_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        # Build date-keyed index per symbol for O(1) lookups.
        date_index_by_symbol: Dict[str, Dict[date_type, Dict[str, Any]]] = {}
        latest_price_by_symbol: Dict[str, float] = {}
        latest_volume_by_symbol: Dict[str, float] = {}
        all_dates: set[date_type] = set()
        for symbol in symbols:
            _check_cancel()
            cache_key = (
                f"{symbol.upper()}:"
                f"{start_dt.date().isoformat()}:"
                f"{end_dt.date().isoformat()}:"
                f"{lookback_days}"
            )
            points = self._historical_bars_cache.get(cache_key)
            if points is None:
                try:
                    fetched = screener.get_symbol_chart_window(
                        symbol=symbol,
                        days=lookback_days,
                        start_date=(start_dt - timedelta(days=320)),
                        end_date=end_dt,
                    )
                    points = [dict(point) for point in fetched if isinstance(point, dict)]
                    self._historical_bars_cache[cache_key] = points
                except RuntimeError as exc:
                    diagnostics["symbols_without_data"].append(symbol)
                    diagnostics["symbol_data_errors"].append({
                        "symbol": symbol,
                        "error": str(exc),
                    })
                    continue
            parsed = self._prepare_series(points, start_dt=start_dt, end_dt=end_dt)
            if not parsed:
                diagnostics["symbols_without_data"].append(symbol)
                continue
            diagnostics["symbols_with_data"] += 1
            series_by_symbol[symbol] = parsed
            idx: Dict[date_type, Dict[str, Any]] = {}
            for point in parsed:
                d = point["date"]
                idx[d] = point
                all_dates.add(d)
            date_index_by_symbol[symbol] = idx

        benchmark_series_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        for benchmark_symbol in sorted(ETF_DCA_BENCHMARK_WEIGHTS.keys()):
            source_series = series_by_symbol.get(benchmark_symbol)
            if source_series:
                benchmark_series_by_symbol[benchmark_symbol] = source_series
                continue
            _check_cancel()
            cache_key = (
                f"{benchmark_symbol.upper()}:"
                f"{start_dt.date().isoformat()}:"
                f"{end_dt.date().isoformat()}:"
                f"{lookback_days}"
            )
            points = self._historical_bars_cache.get(cache_key)
            if points is None:
                try:
                    fetched = screener.get_symbol_chart_window(
                        symbol=benchmark_symbol,
                        days=lookback_days,
                        start_date=(start_dt - timedelta(days=320)),
                        end_date=end_dt,
                    )
                    points = [dict(point) for point in fetched if isinstance(point, dict)]
                    self._historical_bars_cache[cache_key] = points
                except RuntimeError:
                    continue
            parsed = self._prepare_series(points, start_dt=start_dt, end_dt=end_dt)
            if parsed:
                benchmark_series_by_symbol[benchmark_symbol] = parsed

        core_holdings: Dict[str, float] = {}
        core_initial_allocated = False
        core_last_price_by_symbol: Dict[str, float] = {}

        if not series_by_symbol or not all_dates:
            diagnostics["advanced_metrics"] = {
                "profit_factor": 0.0,
                "sortino_ratio": 0.0,
                "expectancy_per_trade": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "avg_win_loss_ratio": 0.0,
                "max_consecutive_losses": 0,
                "recovery_factor": 0.0,
                "calmar_ratio": 0.0,
                "avg_hold_days": 0.0,
                "slippage_bps_applied": _DEFAULT_SLIPPAGE_BPS,
            }
            diagnostics["live_parity"] = self._build_live_parity_report(
                diagnostics=diagnostics,
                emulate_live_trading=emulate_live_trading,
                require_fractionable=require_fractionable,
                symbol_capabilities=symbol_capabilities,
                max_position_size=max_position_size,
                daily_risk_limit=daily_risk_limit,
                fee_bps=fee_bps,
                base_slippage_bps=_DEFAULT_SLIPPAGE_BPS,
                total_fees_paid=0.0,
                execution_latency_ms=execution_latency_ms,
                queue_position_bps=queue_position_bps,
                max_participation_rate=max_participation_rate,
                simulate_queue_position=simulate_queue_position,
                enforce_liquidity_limits=enforce_liquidity_limits,
                reconcile_fees_with_broker=reconcile_fees_with_broker,
            )
            diagnostics["scenario2_report"] = self._build_scenario2_report(
                start_date=start_dt.date(),
                end_date=end_dt.date(),
                initial_capital=initial_capital,
                contribution_amount=contribution_amount,
                contribution_frequency=contribution_frequency,
                contribution_dates=contribution_dates,
                total_contributions=total_contributions,
                final_capital=initial_capital,
                benchmark_final_capital=initial_capital,
                xirr_pct=0.0,
                benchmark_xirr_pct=0.0,
                xirr_excess_pct=0.0,
                equity_curve=[],
                trades=[],
                diagnostics=diagnostics,
                investing_core_dca_pct=investing_core_dca_pct,
                investing_active_sleeve_pct=investing_active_sleeve_pct,
                active_exposure_samples=[],
                total_exposure_samples=[],
                concentration_samples=[],
                no_activity_days=0,
            )
            diagnostics["confidence"] = self._build_backtest_confidence_report(
                diagnostics=diagnostics,
                total_trades=0,
            )
            return BacktestResult(
                strategy_id=request.strategy_id,
                start_date=request.start_date,
                end_date=request.end_date,
                initial_capital=initial_capital,
                final_capital=initial_capital,
                total_return=0.0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                volatility=0.0,
                trades=[],
                equity_curve=[],
                diagnostics=diagnostics,
            )

        open_positions: Dict[str, Dict[str, Any]] = {}
        trades: List[Dict[str, Any]] = []
        equity_curve: List[Dict[str, Any]] = []
        active_exposure_samples: List[float] = []
        total_exposure_samples: List[float] = []
        concentration_samples: List[float] = []
        no_activity_days = 0
        slippage_bps = _DEFAULT_SLIPPAGE_BPS
        optimizer_ctx = (
            request.universe_context.get("optimizer")
            if isinstance(request.universe_context, dict)
            else None
        )
        if isinstance(optimizer_ctx, dict):
            override = optimizer_ctx.get("slippage_bps_override")
            try:
                override_value = float(override)
            except (TypeError, ValueError):
                override_value = None
            if override_value is not None and math.isfinite(override_value):
                slippage_bps = max(0.0, min(250.0, override_value))
        max_hold_days = int(params.get("max_hold_days", 10))
        dca_tranches = max(1, min(3, int(params.get("dca_tranches", 1))))

        def _core_price_for_day(symbol: str, day: date_type) -> Optional[float]:
            series = benchmark_series_by_symbol.get(symbol, [])
            if not series:
                return core_last_price_by_symbol.get(symbol)
            px = self._series_close_on_or_before(series, day)
            if px is not None and px > 0:
                core_last_price_by_symbol[symbol] = float(px)
                return float(px)
            return core_last_price_by_symbol.get(symbol)

        def _core_market_value(day: date_type) -> float:
            total = 0.0
            for benchmark_symbol, qty in core_holdings.items():
                if qty <= 0:
                    continue
                px = _core_price_for_day(benchmark_symbol, day)
                if px is None or px <= 0:
                    continue
                total += float(qty) * float(px)
            return total

        def _allocate_core_sleeve(dollars: float, day: date_type) -> bool:
            if dollars <= 0:
                return False
            prices: Dict[str, float] = {}
            for benchmark_symbol in ETF_DCA_BENCHMARK_WEIGHTS.keys():
                px = _core_price_for_day(benchmark_symbol, day)
                if px is None or px <= 0:
                    continue
                prices[benchmark_symbol] = float(px)
            if not prices:
                diagnostics["blocked_reasons"]["investing_core_unavailable"] += 1
                return False
            usable_weights = {
                symbol: float(ETF_DCA_BENCHMARK_WEIGHTS.get(symbol, 0.0))
                for symbol in prices.keys()
            }
            weight_total = sum(usable_weights.values())
            if weight_total <= 0:
                diagnostics["blocked_reasons"]["investing_core_unavailable"] += 1
                return False
            for benchmark_symbol, px in prices.items():
                alloc = float(dollars) * (usable_weights[benchmark_symbol] / weight_total)
                core_holdings[benchmark_symbol] = float(core_holdings.get(benchmark_symbol, 0.0)) + (alloc / px)
            return True

        for day in sorted(all_dates):
            _check_cancel()
            if day < start_dt.date() or day > end_dt.date():
                continue
            diagnostics["trading_days_evaluated"] += 1
            day_ts = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
            day_realized_pnl = 0.0
            day_had_activity = False
            if investing_policy_active and not core_initial_allocated:
                core_initial_allocation = max(0.0, float(initial_capital) * (investing_core_dca_pct / 100.0))
                if core_initial_allocation > 0 and _allocate_core_sleeve(core_initial_allocation, day):
                    cash -= core_initial_allocation
                    day_had_activity = True
                core_initial_allocated = True
            if self._should_apply_contribution(
                day=day,
                start_day=start_dt.date(),
                frequency=contribution_frequency,
                anchor_weekday=contribution_anchor_weekday,
                anchor_day_of_month=contribution_anchor_day,
            ):
                if investing_policy_active:
                    core_contribution = contribution_amount * (investing_core_dca_pct / 100.0)
                    active_contribution = max(0.0, contribution_amount - core_contribution)
                    cash += active_contribution
                    if not _allocate_core_sleeve(core_contribution, day):
                        # Preserve capital if core sleeve cannot be filled on this day.
                        cash += core_contribution
                    else:
                        day_had_activity = True
                else:
                    cash += contribution_amount
                total_contributions += contribution_amount
                contribution_events += 1
                contribution_dates.append(day)
            core_market_value_today = _core_market_value(day)
            investing_trend_allowed = True
            if investing_policy_active:
                spy_series = benchmark_series_by_symbol.get("SPY", [])
                history: List[float] = []
                for point in spy_series:
                    point_day = point.get("date")
                    if not isinstance(point_day, date_type) or point_day > day:
                        continue
                    close = float(point.get("close", 0.0) or 0.0)
                    if close > 0:
                        history.append(close)
                if len(history) < 200:
                    investing_trend_allowed = False
                else:
                    investing_trend_allowed = history[-1] > (sum(history[-200:]) / 200.0)

            for symbol in sorted(series_by_symbol.keys()):
                _check_cancel()
                point = date_index_by_symbol[symbol].get(day)
                if point is None:
                    continue
                diagnostics["bars_evaluated"] += 1
                close = float(point["close"])
                high = float(point["high"])
                low = float(point["low"])
                open_price = float(point.get("open", close) or close)
                if open_price <= 0:
                    open_price = close
                daily_volume = max(0.0, float(point.get("volume", 0.0) or 0.0))
                # Monte Carlo price noise: apply per-bar multiplicative jitter.
                if _price_noise_rng is not None and price_noise_bps > 0 and close > 0:
                    noise_factor = 1.0 + _price_noise_rng.gauss(0.0, price_noise_bps / 10000.0)
                    close = close * noise_factor
                    high = max(close, high * noise_factor)
                    low = min(close, low * noise_factor)
                    open_price = open_price * noise_factor
                latest_price_by_symbol[symbol] = close
                latest_volume_by_symbol[symbol] = daily_volume

                capability = symbol_capabilities.get(symbol, {})
                broker_tradable = bool(capability.get("tradable", True))
                fractionable = bool(capability.get("fractionable", True))

                position = open_positions.get(symbol)
                if position is not None:
                    # --- DCA: add subsequent tranches on deeper dips ---
                    tranches_filled = int(position.get("dca_tranches_filled", 1))
                    tranches_total = int(position.get("dca_tranches_total", 1))
                    if tranches_filled < tranches_total:
                        avg_entry = float(position["entry_price"])
                        dca_threshold = avg_entry * (1.0 - (tranches_filled * 1.0 / 100.0))
                        if close <= dca_threshold and cash > 0:
                            tranche_notional = compute_risk_based_position_size(
                                equity=cash + core_market_value_today + sum(
                                    float(p["qty"]) * latest_price_by_symbol.get(s, float(p["entry_price"]))
                                    for s, p in open_positions.items()
                                ),
                                risk_per_trade_pct=params["risk_per_trade"],
                                stop_loss_pct=params["stop_loss_pct"],
                                position_size_cap=min(params["position_size"], max_position_size) / tranches_total,
                                cash=cash,
                            )
                            dca_fill = self._simulate_execution_fill(
                                side="buy",
                                order_style="dca_add",
                                open_price=open_price,
                                high=high,
                                low=low,
                                close=close,
                                daily_volume=daily_volume,
                                requested_notional=tranche_notional,
                                requested_qty=None,
                                fee_bps=fee_bps,
                                base_slippage_bps=slippage_bps,
                                emulate_live=emulate_live_trading,
                                latency_ms=execution_latency_ms,
                                queue_position_bps=queue_position_bps,
                                max_participation_rate=max_participation_rate,
                                simulate_queue_position=simulate_queue_position,
                                enforce_liquidity_limits=enforce_liquidity_limits,
                                allow_partial=True,
                                rng=execution_rng,
                                reconcile_fees_with_broker=reconcile_fees_with_broker,
                            )
                            fill_price = float(dca_fill.get("fill_price", close))
                            add_qty = float(dca_fill.get("filled_qty", 0.0))
                            if emulate_live_trading and not fractionable:
                                add_qty = float(math.floor(add_qty))
                            fill_cost = add_qty * fill_price
                            fill_fees = self._estimate_trade_fees(
                                side="buy",
                                notional=fill_cost,
                                quantity=add_qty,
                                fee_bps=fee_bps,
                                emulate_live=emulate_live_trading,
                                reconcile_fees_with_broker=reconcile_fees_with_broker,
                            )
                            if add_qty > 0 and (fill_cost + fill_fees) <= cash:
                                old_qty = float(position["qty"])
                                old_cost = float(position.get("total_cost", old_qty * avg_entry))
                                new_qty = old_qty + add_qty
                                new_cost = old_cost + fill_cost + fill_fees
                                cash -= (fill_cost + fill_fees)
                                position["qty"] = new_qty
                                position["entry_price"] = new_cost / new_qty
                                position["total_cost"] = new_cost
                                position["fees_paid"] = float(position.get("fees_paid", 0.0)) + fill_fees
                                position["dca_tranches_filled"] = tranches_filled + 1
                                new_avg = new_cost / new_qty
                                position["take_profit_price"] = new_avg * (1.0 + params["take_profit_pct"] / 100.0)
                                self._record_execution_fill(
                                    diagnostics=diagnostics,
                                    fill=dict(dca_fill, fees=fill_fees, fill_notional=fill_cost, filled_qty=add_qty),
                                    side="entry",
                                )
                                day_had_activity = True

                    # --- Dynamic ATR stop recalculation ---
                    current_atr_pct = self._compute_atr_pct(series_by_symbol[symbol], day)
                    if current_atr_pct is not None and current_atr_pct > 0:
                        new_atr_stop = close * (1.0 - (params["atr_stop_mult"] * current_atr_pct / 100.0))
                        # Only ratchet upward (never lower the stop).
                        if new_atr_stop > float(position["atr_stop_price"]):
                            position["atr_stop_price"] = new_atr_stop

                    position["peak_price"] = max(float(position["peak_price"]), close)
                    trailing_stop_price = float(position["peak_price"]) * (1.0 - params["trailing_stop_pct"] / 100.0)
                    atr_stop_price = float(position["atr_stop_price"])
                    effective_stop = max(atr_stop_price, trailing_stop_price)
                    take_profit_price = float(position["take_profit_price"])

                    exit_price = None
                    exit_reason = ""

                    # Time-based exit: force close after max_hold_days.
                    entry_date = datetime.fromisoformat(position["entry_date"]).date()
                    days_held = (day - entry_date).days
                    exit_reference_price: Optional[float] = None
                    exit_style = "time_exit"
                    if days_held >= max_hold_days:
                        exit_reference_price = close
                        exit_style = "time_exit"
                        exit_reason = "time_exit"
                    elif low <= effective_stop:
                        # On gap-downs, the fill occurs at or below the low,
                        # not at the stop level.  Use the worse of the two.
                        raw_stop_fill = min(effective_stop, low)
                        exit_reference_price = raw_stop_fill
                        exit_style = "stop_exit"
                        exit_reason = "stop_exit"
                    elif high >= take_profit_price:
                        exit_reference_price = take_profit_price
                        exit_style = "take_profit_exit"
                        exit_reason = "take_profit_exit"

                    if exit_reference_price is not None:
                        diagnostics["exit_reasons"][exit_reason] = diagnostics["exit_reasons"].get(exit_reason, 0) + 1
                        qty = float(position["qty"])
                        entry_price = float(position["entry_price"])
                        exit_fill = self._simulate_execution_fill(
                            side="sell",
                            order_style=exit_style,
                            open_price=open_price,
                            high=high,
                            low=low,
                            close=close,
                            daily_volume=daily_volume,
                            requested_notional=None,
                            requested_qty=qty,
                            fee_bps=fee_bps,
                            base_slippage_bps=slippage_bps,
                            emulate_live=emulate_live_trading,
                            latency_ms=execution_latency_ms,
                            queue_position_bps=queue_position_bps,
                            max_participation_rate=max_participation_rate,
                            simulate_queue_position=simulate_queue_position,
                            enforce_liquidity_limits=enforce_liquidity_limits,
                            allow_partial=False,
                            rng=execution_rng,
                            reconcile_fees_with_broker=reconcile_fees_with_broker,
                            reference_price_override=exit_reference_price,
                        )
                        exit_price = float(exit_fill.get("fill_price", exit_reference_price))
                        exit_notional = float(exit_fill.get("fill_notional", qty * exit_price))
                        exit_fees = float(exit_fill.get("fees", 0.0))
                        cost_basis = float(position.get("total_cost", entry_price * qty))
                        pnl = (exit_notional - exit_fees) - cost_basis
                        cash += (exit_notional - exit_fees)
                        day_realized_pnl += pnl
                        risk_manager.record_trade_result(pnl)
                        self._record_execution_fill(
                            diagnostics=diagnostics,
                            fill=exit_fill,
                            side="exit",
                        )
                        day_had_activity = True
                        trades.append({
                            "id": trade_id,
                            "symbol": symbol,
                            "entry_date": position["entry_date"],
                            "exit_date": day_ts.isoformat(),
                            "entry_price": round(entry_price, 4),
                            "exit_price": round(exit_price, 4),
                            "quantity": round(qty, 6),
                            "pnl": round(pnl, 2),
                            "return_pct": round(((exit_price - entry_price) / entry_price) * 100.0 if entry_price > 0 else 0.0, 2),
                            "reason": exit_reason,
                            "days_held": days_held,
                            "fees": round(float(position.get("fees_paid", 0.0)) + exit_fees, 4),
                        })
                        trade_id += 1
                        del open_positions[symbol]
                        continue

                if symbol in open_positions:
                    diagnostics["blocked_reasons"]["already_in_position"] += 1
                    continue

                if emulate_live_trading:
                    if not broker_tradable:
                        diagnostics["blocked_reasons"]["not_tradable"] += 1
                        continue
                    if require_fractionable and not fractionable:
                        diagnostics["blocked_reasons"]["not_fractionable"] += 1
                        continue
                    if day_realized_pnl <= -daily_risk_limit:
                        diagnostics["blocked_reasons"]["daily_risk_limit"] += 1
                        continue
                    if risk_manager.circuit_breaker_active:
                        diagnostics["blocked_reasons"]["risk_circuit_breaker"] += 1
                        continue

                if investing_policy_active and len(open_positions) >= investing_max_positions:
                    diagnostics["blocked_reasons"]["investing_max_positions"] += 1
                    continue

                diagnostics["entry_checks"] += 1
                metrics = self._compute_signal_metrics(series_by_symbol[symbol], day, params)
                if metrics is None:
                    diagnostics["blocked_reasons"]["insufficient_history"] += 1
                    continue
                if investing_policy_active:
                    if not bool(metrics.get("investing_entry_signal", False)):
                        diagnostics["blocked_reasons"]["no_dip_signal"] += 1
                        continue
                    diagnostics["entry_signals"] += 1
                    if not investing_trend_allowed:
                        diagnostics["blocked_reasons"]["investing_trend_filter"] += 1
                        continue
                else:
                    if not bool(metrics.get("dip_buy_signal", False)):
                        diagnostics["blocked_reasons"]["no_dip_signal"] += 1
                        continue
                    diagnostics["entry_signals"] += 1
                    # Only allow range_bound entries for dip-buy mean-reversion.
                    if metrics["regime"] not in {"range_bound"}:
                        diagnostics["blocked_reasons"]["regime_filtered"] += 1
                        continue

                open_equity = cash + sum(
                    float(pos["qty"]) * latest_price_by_symbol.get(sym, float(pos["entry_price"]))
                    for sym, pos in open_positions.items()
                )
                open_equity += core_market_value_today
                # DCA: first tranche uses position_size / dca_tranches
                tranche_cap = min(params["position_size"], max_position_size) / dca_tranches
                # Use shared risk-based position sizing.
                target_notional = compute_risk_based_position_size(
                    equity=open_equity,
                    risk_per_trade_pct=params["risk_per_trade"],
                    stop_loss_pct=params["stop_loss_pct"],
                    position_size_cap=tranche_cap,
                    cash=cash,
                )
                if micro_policy_active:
                    micro_position_cap = max(
                        25.0,
                        min(
                            max_position_size,
                            max(25.0, open_equity * 0.20),
                            max(25.0, cash * 0.90),
                        ),
                    )
                    target_notional = min(target_notional, micro_position_cap)
                    projected_loss = target_notional * (params["stop_loss_pct"] / 100.0)
                    single_trade_loss_cap = max(1.0, open_equity * (micro_single_trade_loss_pct / 100.0))
                    if projected_loss > single_trade_loss_cap:
                        diagnostics["blocked_reasons"]["micro_single_trade_loss"] += 1
                        continue
                    spread_proxy_bps = self._estimate_micro_spread_proxy_bps(
                        daily_volume=daily_volume,
                        close=close,
                        slippage_bps=slippage_bps,
                        queue_position_bps=queue_position_bps,
                    )
                    if spread_proxy_bps > micro_max_spread_bps:
                        diagnostics["blocked_reasons"]["micro_spread_guardrail"] += 1
                        continue
                if target_notional < 1.0:
                    diagnostics["blocked_reasons"]["risk_cap_too_low"] += 1
                    continue
                entry_fill = self._simulate_execution_fill(
                    side="buy",
                    order_style="entry_market",
                    open_price=open_price,
                    high=high,
                    low=low,
                    close=close,
                    daily_volume=daily_volume,
                    requested_notional=target_notional,
                    requested_qty=None,
                    fee_bps=fee_bps,
                    base_slippage_bps=slippage_bps,
                    emulate_live=emulate_live_trading,
                    latency_ms=execution_latency_ms,
                    queue_position_bps=queue_position_bps,
                    max_participation_rate=max_participation_rate,
                    simulate_queue_position=simulate_queue_position,
                    enforce_liquidity_limits=enforce_liquidity_limits,
                    allow_partial=True,
                    rng=execution_rng,
                    reconcile_fees_with_broker=reconcile_fees_with_broker,
                )
                fill_price = float(entry_fill.get("fill_price", close))
                qty = float(entry_fill.get("filled_qty", 0.0))
                if emulate_live_trading and not fractionable:
                    qty = float(math.floor(qty))
                if qty <= 0:
                    diagnostics["blocked_reasons"]["liquidity_no_fill"] += 1
                    diagnostics["blocked_reasons"]["invalid_position_size"] += 1
                    continue
                fill_notional = qty * fill_price
                fill_fees = self._estimate_trade_fees(
                    side="buy",
                    notional=fill_notional,
                    quantity=qty,
                    fee_bps=fee_bps,
                    emulate_live=emulate_live_trading,
                    reconcile_fees_with_broker=reconcile_fees_with_broker,
                )
                if emulate_live_trading:
                    current_positions_for_risk = {
                        sym: {
                            "symbol": sym,
                            "quantity": float(pos.get("qty", 0.0)),
                            "market_value": float(pos.get("qty", 0.0)) * latest_price_by_symbol.get(sym, float(pos.get("entry_price", 0.0))),
                        }
                        for sym, pos in open_positions.items()
                    }
                    order_valid, _order_reason = risk_manager.validate_order(
                        symbol=symbol,
                        quantity=qty,
                        price=fill_price,
                        current_positions=current_positions_for_risk,
                    )
                    if not order_valid:
                        diagnostics["blocked_reasons"]["risk_validation_failed"] += 1
                        continue
                if (fill_notional + fill_fees) > cash:
                    diagnostics["blocked_reasons"]["cash_insufficient"] += 1
                    continue
                if micro_policy_active:
                    reserve_dollars = max(0.0, open_equity * (micro_cash_reserve_pct / 100.0))
                    if (cash - (fill_notional + fill_fees)) < reserve_dollars:
                        diagnostics["blocked_reasons"]["micro_cash_reserve"] += 1
                        continue

                cash -= (fill_notional + fill_fees)
                atr_pct = float(metrics["atr14_pct"])
                atr_stop_price = fill_price * (1.0 - (params["atr_stop_mult"] * atr_pct / 100.0))
                stop_loss_price = fill_price * (1.0 - params["stop_loss_pct"] / 100.0)
                open_positions[symbol] = {
                    "entry_price": fill_price,
                    "qty": qty,
                    "peak_price": fill_price,
                    "atr_stop_price": min(atr_stop_price, stop_loss_price),
                    "take_profit_price": fill_price * (1.0 + params["take_profit_pct"] / 100.0),
                    "entry_date": day_ts.isoformat(),
                    "dca_tranches_filled": 1,
                    "dca_tranches_total": dca_tranches,
                    "total_cost": fill_notional + fill_fees,
                    "fees_paid": fill_fees,
                }
                requested_qty = float(entry_fill.get("requested_qty", 0.0))
                if requested_qty > 0 and qty + 1e-9 < requested_qty:
                    diagnostics["partial_entry_fills"] = int(diagnostics.get("partial_entry_fills", 0)) + 1
                self._record_execution_fill(
                    diagnostics=diagnostics,
                    fill=dict(entry_fill, fees=fill_fees, fill_notional=fill_notional),
                    side="entry",
                )
                diagnostics["entries_opened"] += 1
                day_had_activity = True

            market_value = sum(
                float(pos["qty"]) * latest_price_by_symbol.get(sym, float(pos["entry_price"]))
                for sym, pos in open_positions.items()
            )
            total_equity = cash + market_value + core_market_value_today
            if total_equity > 0:
                active_exposure_samples.append((market_value / total_equity) * 100.0)
                total_exposure_samples.append(((market_value + core_market_value_today) / total_equity) * 100.0)
                holding_values: List[float] = []
                for sym, pos in open_positions.items():
                    holding_values.append(
                        float(pos["qty"]) * latest_price_by_symbol.get(sym, float(pos["entry_price"]))
                    )
                for core_symbol, core_qty in core_holdings.items():
                    if core_qty <= 0:
                        continue
                    core_px = _core_price_for_day(core_symbol, day)
                    if core_px is None or core_px <= 0:
                        continue
                    holding_values.append(float(core_qty) * float(core_px))
                if holding_values:
                    concentration_samples.append((max(holding_values) / total_equity) * 100.0)
            if not day_had_activity:
                no_activity_days += 1
            risk_manager.update_equity(total_equity)
            equity_curve.append({
                "timestamp": day_ts.isoformat(),
                "equity": round(total_equity, 2),
            })

        # Force-close remaining positions at end of window.
        _check_cancel()
        if open_positions:
            final_ts = datetime.combine(end_dt.date(), datetime.min.time(), tzinfo=timezone.utc)
            for symbol in sorted(list(open_positions.keys())):
                pos = open_positions[symbol]
                close = latest_price_by_symbol.get(symbol, float(pos["entry_price"]))
                qty = float(pos["qty"])
                entry_price = float(pos["entry_price"])
                daily_volume = max(0.0, float(latest_volume_by_symbol.get(symbol, 0.0) or 0.0))
                exit_fill = self._simulate_execution_fill(
                    side="sell",
                    order_style="end_of_backtest",
                    open_price=close,
                    high=close,
                    low=close,
                    close=close,
                    daily_volume=daily_volume,
                    requested_notional=None,
                    requested_qty=qty,
                    fee_bps=fee_bps,
                    base_slippage_bps=slippage_bps,
                    emulate_live=emulate_live_trading,
                    latency_ms=execution_latency_ms,
                    queue_position_bps=queue_position_bps,
                    max_participation_rate=max_participation_rate,
                    simulate_queue_position=simulate_queue_position,
                    enforce_liquidity_limits=enforce_liquidity_limits,
                    allow_partial=False,
                    rng=execution_rng,
                    reconcile_fees_with_broker=reconcile_fees_with_broker,
                    reference_price_override=close,
                )
                exit_price = float(exit_fill.get("fill_price", close))
                exit_notional = float(exit_fill.get("fill_notional", qty * exit_price))
                exit_fees = float(exit_fill.get("fees", 0.0))
                cost_basis = float(pos.get("total_cost", entry_price * qty))
                pnl = (exit_notional - exit_fees) - cost_basis
                cash += (exit_notional - exit_fees)
                risk_manager.record_trade_result(pnl)
                self._record_execution_fill(
                    diagnostics=diagnostics,
                    fill=exit_fill,
                    side="exit",
                )
                entry_date = datetime.fromisoformat(pos["entry_date"]).date()
                days_held = (end_dt.date() - entry_date).days
                diagnostics["exit_reasons"]["end_of_backtest"] += 1
                trades.append({
                    "id": trade_id,
                    "symbol": symbol,
                    "entry_date": pos["entry_date"],
                    "exit_date": final_ts.isoformat(),
                    "entry_price": round(entry_price, 4),
                    "exit_price": round(exit_price, 4),
                    "quantity": round(qty, 6),
                    "pnl": round(pnl, 2),
                    "return_pct": round(((exit_price - entry_price) / entry_price) * 100.0 if entry_price > 0 else 0.0, 2),
                    "reason": "end_of_backtest",
                    "days_held": days_held,
                    "fees": round(float(pos.get("fees_paid", 0.0)) + exit_fees, 4),
                })
                trade_id += 1
                del open_positions[symbol]
            core_value_final_ts = _core_market_value(end_dt.date())
            equity_curve.append({
                "timestamp": final_ts.isoformat(),
                "equity": round(cash + core_value_final_ts, 2),
            })

        equity_curve = self._normalize_equity_curve(equity_curve)

        core_final_market_value = _core_market_value(end_dt.date())
        final_capital = round(cash + core_final_market_value, 2)
        capital_base_for_return = max(1.0, initial_capital + total_contributions)
        total_pnl = final_capital - capital_base_for_return
        total_trades = len(trades)
        winning_trades = len([t for t in trades if t["pnl"] > 0])
        losing_trades = len([t for t in trades if t["pnl"] < 0])
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
        total_return = (total_pnl / capital_base_for_return * 100) if capital_base_for_return > 0 else 0.0

        max_drawdown = self._calculate_max_drawdown_from_equity(equity_curve)
        equity_returns = self._equity_returns(equity_curve)
        volatility = self._calculate_annualized_volatility(equity_returns)
        sharpe_ratio = self._calculate_sharpe_ratio(equity_returns)
        sortino_ratio = self._calculate_sortino_ratio(equity_returns)
        profit_factor = self._calculate_profit_factor(trades)
        expectancy = self._calculate_expectancy(trades)
        avg_win, avg_loss = self._calculate_avg_win_loss(trades)
        max_consecutive_losses = self._calculate_max_consecutive_losses(trades)
        recovery_factor = self._calculate_recovery_factor(total_return, max_drawdown)
        calmar_ratio = self._calculate_calmar_ratio(equity_returns, max_drawdown)
        avg_hold_days = self._calculate_avg_hold_days(trades)
        total_fees_paid = sum(float(t.get("fees", 0.0)) for t in trades)
        payoff_ratio = (avg_win / abs(avg_loss)) if avg_loss < 0 else 0.0
        win_rate_ratio = (winning_trades / total_trades) if total_trades > 0 else 0.0
        expectancy_r = (win_rate_ratio * payoff_ratio) - (1.0 - win_rate_ratio)
        span_days = max(1, (end_dt.date() - start_dt.date()).days + 1)
        twr_annualized_pct = self._annualize_return_pct(total_return, span_days=span_days)
        xirr_pct = self._approximate_xirr(
            start_date=start_dt.date(),
            end_date=end_dt.date(),
            initial_capital=initial_capital,
            contribution_amount=contribution_amount,
            contribution_frequency=contribution_frequency,
            contribution_events=contribution_events,
            final_capital=final_capital,
        )
        benchmark_total_return_pct = self._estimate_benchmark_total_return_pct(
            series_by_symbol=series_by_symbol,
            start_date=start_dt.date(),
            end_date=end_dt.date(),
        )
        benchmark_method = "equal_weight_universe"
        benchmark_contribution_events = contribution_events
        benchmark_final_capital = max(
            0.0,
            capital_base_for_return * (1.0 + (benchmark_total_return_pct / 100.0)),
        )
        benchmark_detail: Dict[str, Any] = {}
        if benchmark_series_by_symbol:
            dca_benchmark = self._simulate_weighted_dca_benchmark(
                series_by_symbol=benchmark_series_by_symbol,
                weights=ETF_DCA_BENCHMARK_WEIGHTS,
                start_date=start_dt.date(),
                end_date=end_dt.date(),
                initial_capital=initial_capital,
                contribution_amount=contribution_amount,
                contribution_dates=contribution_dates,
            )
            if isinstance(dca_benchmark, dict):
                benchmark_method = "dca_weighted_spy_qqq_60_40"
                benchmark_total_return_pct = float(dca_benchmark.get("total_return_pct", benchmark_total_return_pct))
                benchmark_final_capital = float(dca_benchmark.get("final_capital", benchmark_final_capital))
                benchmark_contribution_events = int(
                    dca_benchmark.get("contribution_events_applied", benchmark_contribution_events)
                )
                benchmark_detail = dict(dca_benchmark)
        benchmark_xirr_pct = self._approximate_xirr(
            start_date=start_dt.date(),
            end_date=end_dt.date(),
            initial_capital=initial_capital,
            contribution_amount=contribution_amount,
            contribution_frequency=contribution_frequency,
            contribution_events=benchmark_contribution_events,
            final_capital=max(1.0, benchmark_final_capital),
        )
        xirr_excess_pct = xirr_pct - benchmark_xirr_pct
        stability = self._compute_subperiod_stability(equity_curve)
        max_single_trade_loss_pct_base = 0.0
        if trades:
            worst_trade_loss = abs(min(float(t.get("pnl", 0.0) or 0.0) for t in trades))
            base_capital = max(1.0, float(initial_capital))
            max_single_trade_loss_pct_base = (worst_trade_loss / base_capital) * 100.0

        blocked_nonzero = [
            {"reason": reason, "count": count}
            for reason, count in diagnostics["blocked_reasons"].items()
            if count > 0
        ]
        blocked_nonzero.sort(key=lambda item: item["count"], reverse=True)
        diagnostics["top_blockers"] = blocked_nonzero[:5]
        diagnostics["symbols_without_data"] = sorted(set(diagnostics["symbols_without_data"]))
        diagnostics["risk_metrics_end_state"] = risk_manager.get_risk_metrics()
        diagnostics["contribution_events"] = int(contribution_events)
        diagnostics["capital_contributions_total"] = round(float(total_contributions), 2)
        diagnostics["capital_base_for_return"] = round(float(capital_base_for_return), 2)
        diagnostics["symbol_capabilities_enforced"] = bool(symbol_capabilities)
        if symbol_capabilities:
            diagnostics["symbol_capabilities"] = {
                symbol: {
                    "tradable": bool((caps or {}).get("tradable", True)),
                    "fractionable": bool((caps or {}).get("fractionable", True)),
                }
                for symbol, caps in symbol_capabilities.items()
            }
        execution_summary = diagnostics.get("execution_summary")
        if isinstance(execution_summary, dict):
            fills_count = max(0, int(execution_summary.get("fills", 0)))
            entry_fills = max(0, int(execution_summary.get("entry_fills", 0)))
            exit_fills = max(0, int(execution_summary.get("exit_fills", 0)))
            execution_summary["average_effective_slippage_bps"] = round(
                float(execution_summary.get("effective_slippage_bps_sum", 0.0)) / max(1, fills_count),
                4,
            )
            execution_summary["average_effective_latency_ms"] = round(
                float(execution_summary.get("effective_latency_ms_sum", 0.0)) / max(1, fills_count),
                4,
            )
            execution_summary["average_queue_penalty_bps"] = round(
                float(execution_summary.get("queue_penalty_bps_sum", 0.0)) / max(1, fills_count),
                4,
            )
            execution_summary["average_impact_bps"] = round(
                float(execution_summary.get("impact_bps_sum", 0.0)) / max(1, fills_count),
                4,
            )
            execution_summary["average_spread_bps"] = round(
                float(execution_summary.get("spread_bps_sum", 0.0)) / max(1, fills_count),
                4,
            )
            execution_summary["average_participation_rate"] = round(
                float(execution_summary.get("participation_rate_sum", 0.0)) / max(1, fills_count),
                6,
            )
            execution_summary["average_entry_notional"] = round(
                float(execution_summary.get("entry_notional_total", 0.0)) / max(1, entry_fills),
                4,
            )
            execution_summary["fees_total"] = round(float(execution_summary.get("fees_total", 0.0)), 4)
            execution_summary["fill_split"] = {
                "entry": entry_fills,
                "exit": exit_fills,
            }
        diagnostics["advanced_metrics"] = {
            "profit_factor": round(profit_factor, 3),
            "sortino_ratio": round(sortino_ratio, 3),
            "expectancy_per_trade": round(expectancy, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "avg_win_loss_ratio": round(avg_win / abs(avg_loss), 2) if avg_loss != 0 else 0.0,
            "expectancy_r": round(expectancy_r, 4),
            "payoff_ratio": round(payoff_ratio, 4),
            "max_consecutive_losses": max_consecutive_losses,
            "recovery_factor": round(recovery_factor, 3),
            "calmar_ratio": round(calmar_ratio, 3),
            "avg_hold_days": round(avg_hold_days, 1),
            "slippage_bps_applied": slippage_bps,
            "twr_annualized_pct": round(twr_annualized_pct, 4),
            "xirr_pct": round(xirr_pct, 4),
            "benchmark_xirr_pct": round(benchmark_xirr_pct, 4),
            "xirr_excess_pct": round(xirr_excess_pct, 4),
            "benchmark_method": benchmark_method,
            "benchmark_final_capital": round(float(benchmark_final_capital), 2),
            "benchmark_contribution_events": int(benchmark_contribution_events),
            "subperiod_positive_ratio_pct": round(float(stability.get("positive_ratio_pct", 0.0)), 4),
            "subperiod_quarterly_positive_ratio_pct": round(float(stability.get("quarterly_positive_ratio_pct", 0.0)), 4),
            "subperiod_fold_stability_pct": round(float(stability.get("stability_score_pct", 0.0)), 4),
            "max_single_trade_loss_pct_base": round(float(max_single_trade_loss_pct_base), 4),
            "execution_slippage_bps_effective_avg": round(
                float((diagnostics.get("execution_summary") or {}).get("average_effective_slippage_bps", slippage_bps)),
                4,
            ),
            "fees_paid": round(total_fees_paid, 4),
        }
        diagnostics["benchmark"] = {
            "method": benchmark_method,
            "weights": {symbol: round(weight, 4) for symbol, weight in ETF_DCA_BENCHMARK_WEIGHTS.items()},
            "total_return_pct": round(float(benchmark_total_return_pct), 4),
            "xirr_pct": round(float(benchmark_xirr_pct), 4),
            "final_capital": round(float(benchmark_final_capital), 2),
            "contribution_events": int(benchmark_contribution_events),
            "detail": benchmark_detail,
        }
        diagnostics["scenario2_report"] = self._build_scenario2_report(
            start_date=start_dt.date(),
            end_date=end_dt.date(),
            initial_capital=initial_capital,
            contribution_amount=contribution_amount,
            contribution_frequency=contribution_frequency,
            contribution_dates=contribution_dates,
            total_contributions=total_contributions,
            final_capital=final_capital,
            benchmark_final_capital=benchmark_final_capital,
            xirr_pct=xirr_pct,
            benchmark_xirr_pct=benchmark_xirr_pct,
            xirr_excess_pct=xirr_excess_pct,
            equity_curve=equity_curve,
            trades=trades,
            diagnostics=diagnostics,
            investing_core_dca_pct=investing_core_dca_pct,
            investing_active_sleeve_pct=investing_active_sleeve_pct,
            active_exposure_samples=active_exposure_samples,
            total_exposure_samples=total_exposure_samples,
            concentration_samples=concentration_samples,
            no_activity_days=no_activity_days,
        )
        diagnostics["live_parity"] = self._build_live_parity_report(
            diagnostics=diagnostics,
            emulate_live_trading=emulate_live_trading,
            require_fractionable=require_fractionable,
            symbol_capabilities=symbol_capabilities,
            max_position_size=max_position_size,
            daily_risk_limit=daily_risk_limit,
            fee_bps=fee_bps,
            base_slippage_bps=slippage_bps,
            total_fees_paid=total_fees_paid,
            execution_latency_ms=execution_latency_ms,
            queue_position_bps=queue_position_bps,
            max_participation_rate=max_participation_rate,
            simulate_queue_position=simulate_queue_position,
            enforce_liquidity_limits=enforce_liquidity_limits,
            reconcile_fees_with_broker=reconcile_fees_with_broker,
        )
        diagnostics["micro_scorecard"] = self._build_micro_scorecard(
            diagnostics=diagnostics,
            total_trades=total_trades,
            max_drawdown=max_drawdown,
            expectancy_r=expectancy_r,
            profit_factor=profit_factor,
            payoff_ratio=payoff_ratio,
            twr_annualized_pct=twr_annualized_pct,
            xirr_excess_pct=xirr_excess_pct,
            stability_score_pct=float(stability.get("stability_score_pct", 0.0)),
            max_single_trade_loss_pct_base=max_single_trade_loss_pct_base,
        )
        diagnostics["investing_scorecard"] = self._build_investing_scorecard(
            diagnostics=diagnostics,
            total_trades=total_trades,
            max_drawdown=max_drawdown,
            profit_factor=profit_factor,
            payoff_ratio=payoff_ratio,
            xirr_excess_pct=xirr_excess_pct,
            stability_score_pct=float(stability.get("stability_score_pct", 0.0)),
            max_single_trade_loss_pct_base=max_single_trade_loss_pct_base,
            span_days=span_days,
        )
        diagnostics["confidence"] = self._build_backtest_confidence_report(
            diagnostics=diagnostics,
            total_trades=total_trades,
        )
        micro_scorecard = diagnostics.get("micro_scorecard")
        if isinstance(micro_scorecard, dict) and bool(micro_scorecard.get("active", False)):
            confidence_payload = diagnostics.get("confidence")
            if isinstance(confidence_payload, dict):
                base_conf = float(confidence_payload.get("overall_confidence_score", 0.0) or 0.0)
                micro_conf = float(micro_scorecard.get("confidence_score", 0.0) or 0.0)
                confidence_payload["overall_confidence_score"] = round(
                    max(0.0, min(100.0, (0.70 * base_conf) + (0.30 * micro_conf))),
                    2,
                )
                confidence_payload["micro_confidence_score"] = round(micro_conf, 2)
                confidence_payload["micro_final_score"] = round(float(micro_scorecard.get("final_score", 0.0) or 0.0), 2)
                confidence_payload["micro_pass"] = bool(micro_scorecard.get("pass", False))
        investing_scorecard = diagnostics.get("investing_scorecard")
        if isinstance(investing_scorecard, dict) and bool(investing_scorecard.get("active", False)):
            confidence_payload = diagnostics.get("confidence")
            if isinstance(confidence_payload, dict):
                base_conf = float(confidence_payload.get("overall_confidence_score", 0.0) or 0.0)
                investing_conf = float(investing_scorecard.get("confidence_score", 0.0) or 0.0)
                confidence_payload["overall_confidence_score"] = round(
                    max(0.0, min(100.0, (0.65 * base_conf) + (0.35 * investing_conf))),
                    2,
                )
                confidence_payload["investing_confidence_score"] = round(investing_conf, 2)
                confidence_payload["investing_final_score"] = round(float(investing_scorecard.get("final_score", 0.0) or 0.0), 2)
                confidence_payload["investing_pass"] = bool(investing_scorecard.get("pass", False))

        return BacktestResult(
            strategy_id=request.strategy_id,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            volatility=volatility,
            trades=trades,
            equity_curve=equity_curve,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _should_apply_contribution(
        *,
        day: date_type,
        start_day: date_type,
        frequency: str,
        anchor_weekday: int,
        anchor_day_of_month: int,
    ) -> bool:
        """Determine whether recurring contribution should be applied on this day."""
        if frequency not in {"weekly", "monthly"}:
            return False
        if day <= start_day:
            # Initial capital already represents day-0 funding.
            return False
        if frequency == "weekly":
            return day.weekday() == anchor_weekday
        last_dom = (day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        effective_dom = min(anchor_day_of_month, int(last_dom.day))
        return day.day == effective_dom

    def _build_live_parity_report(
        self,
        diagnostics: Dict[str, Any],
        emulate_live_trading: bool,
        require_fractionable: bool,
        symbol_capabilities: Dict[str, Dict[str, bool]],
        max_position_size: float,
        daily_risk_limit: float,
        fee_bps: float,
        base_slippage_bps: float,
        total_fees_paid: float,
        execution_latency_ms: float,
        queue_position_bps: float,
        max_participation_rate: float,
        simulate_queue_position: bool,
        enforce_liquidity_limits: bool,
        reconcile_fees_with_broker: bool,
    ) -> Dict[str, Any]:
        """Build a compact diagnostics summary of live-equivalent constraints."""
        universe_context = diagnostics.get("universe_context")
        if not isinstance(universe_context, dict):
            universe_context = {}
        live_ctx = universe_context.get("live_parity_context")
        if not isinstance(live_ctx, dict):
            live_ctx = {}
        guardrails = universe_context.get("guardrails")
        if not isinstance(guardrails, dict):
            guardrails = {}
        filtered_out = universe_context.get("symbols_filtered_out")
        filtered_count = len(filtered_out) if isinstance(filtered_out, list) else 0

        symbols_selected_for_entries = live_ctx.get("symbols_selected")
        if not isinstance(symbols_selected_for_entries, int):
            symbols_selected_for_entries = universe_context.get("symbols_selected")
        if not isinstance(symbols_selected_for_entries, int):
            symbols_selected_for_entries = int(diagnostics.get("symbols_requested", 0))

        symbols_requested_total = int(diagnostics.get("symbols_requested", 0))
        raw_requested_from_context = universe_context.get("symbols_requested")
        try:
            parsed_requested = int(raw_requested_from_context)
        except (TypeError, ValueError):
            parsed_requested = None
        if parsed_requested is not None and parsed_requested > 0:
            symbols_requested_total = parsed_requested

        return {
            "emulate_live_trading": bool(emulate_live_trading),
            "strict_real_data_required": bool(
                live_ctx.get("strict_real_data_required", self._require_real_data)
            ),
            "data_provider": "alpaca" if self._alpaca_creds else "fallback",
            "broker": str(live_ctx.get("broker", "unknown")),
            "broker_mode": str(live_ctx.get("broker_mode", "paper")),
            "credentials_available": bool(
                live_ctx.get("credentials_available", bool(self._alpaca_creds))
            ),
            "workspace_universe_enabled": bool(
                live_ctx.get(
                    "workspace_universe_requested",
                    universe_context.get("symbols_source") == "workspace_universe",
                )
            ),
            "universe_source": str(universe_context.get("symbols_source", "strategy_symbols")),
            "parameter_source": str(universe_context.get("parameter_source", "strategy_saved_hardened")),
            "asset_type": universe_context.get("asset_type"),
            "screener_mode": universe_context.get("screener_mode"),
            "preset": universe_context.get("preset"),
            "preset_universe_mode": universe_context.get("preset_universe_mode"),
            "guardrails": guardrails,
            "require_broker_tradable": bool(
                universe_context.get("require_broker_tradable", emulate_live_trading)
            ),
            "require_fractionable": bool(require_fractionable),
            "symbol_capabilities_enforced": bool(symbol_capabilities),
            "symbols_requested": int(symbols_requested_total),
            "symbols_selected_for_entries": int(symbols_selected_for_entries),
            "symbols_with_data": int(diagnostics.get("symbols_with_data", 0)),
            "symbols_filtered_out_count": int(
                live_ctx.get("symbols_filtered_out_count", filtered_count)
            ),
            "max_position_size_applied": round(float(max_position_size), 4),
            "risk_limit_daily_applied": round(float(daily_risk_limit), 4),
            "slippage_model": "dynamic_bar_range" if emulate_live_trading else "fixed_bps",
            "slippage_bps_base": round(float(base_slippage_bps), 4),
            "fee_model": (
                "fee_bps_plus_sec_taf_on_sells" if emulate_live_trading else "fee_bps_only"
            ),
            "fee_bps_applied": round(float(fee_bps), 4),
            "fees_paid_total": round(float(total_fees_paid), 4),
            "execution_fill_model": (
                "intrabar_latency_queue_participation"
                if emulate_live_trading
                else "close_price_basic"
            ),
            "execution_latency_ms_applied": round(float(execution_latency_ms), 4),
            "queue_position_bps_applied": round(float(queue_position_bps), 4),
            "max_participation_rate_applied": round(float(max_participation_rate), 6),
            "simulate_queue_position": bool(simulate_queue_position),
            "enforce_liquidity_limits": bool(enforce_liquidity_limits),
            "fee_reconciliation_mode": (
                "broker_schedule_rounded"
                if reconcile_fees_with_broker
                else "approximate"
            ),
            "micro_policy_active": bool(live_ctx.get("micro_policy_active", diagnostics.get("micro_policy_active", False))),
            "micro_policy_mode": str(live_ctx.get("micro_policy_mode", diagnostics.get("micro_strategy_mode", "auto"))),
            "micro_policy_reason": str(live_ctx.get("micro_policy_reason", diagnostics.get("micro_policy_reason", ""))),
            "investing_policy_active": bool(live_ctx.get("investing_policy_active", False)),
            "investing_policy_reason": str(live_ctx.get("investing_policy_reason", "")),
        }

    def _build_backtest_confidence_report(
        self,
        *,
        diagnostics: Dict[str, Any],
        total_trades: int,
    ) -> Dict[str, Any]:
        """Estimate confidence that this run reflects live-executable conditions."""
        live_parity = diagnostics.get("live_parity")
        if not isinstance(live_parity, dict):
            live_parity = {}
        symbols_requested = max(
            0,
            int(live_parity.get("symbols_requested", diagnostics.get("symbols_requested", 0))),
        )
        symbols_with_data = max(0, int(diagnostics.get("symbols_with_data", 0)))
        symbols_selected = max(0, int(live_parity.get("symbols_selected_for_entries", symbols_requested)))
        symbols_filtered_out_count = max(0, int(live_parity.get("symbols_filtered_out_count", 0)))
        coverage_denom = max(1, symbols_requested)
        data_coverage_pct = (symbols_with_data / coverage_denom) * 100.0
        executable_universe_pct = (symbols_selected / coverage_denom) * 100.0

        blocked_reasons = diagnostics.get("blocked_reasons")
        blocked_total = 0
        if isinstance(blocked_reasons, dict):
            blocked_total = int(sum(max(0, int(v or 0)) for v in blocked_reasons.values()))
        entry_checks = max(0, int(diagnostics.get("entry_checks", 0)))
        entry_signals = max(0, int(diagnostics.get("entry_signals", 0)))
        entries_opened = max(0, int(diagnostics.get("entries_opened", 0)))
        partial_entry_fills = max(0, int(diagnostics.get("partial_entry_fills", 0)))
        signal_realization_pct = (entries_opened / max(1, entry_signals)) * 100.0 if entry_signals > 0 else 0.0
        partial_fill_ratio = (partial_entry_fills / max(1, entries_opened)) if entries_opened > 0 else 0.0

        strict_data_score = 1.0 if bool(live_parity.get("strict_real_data_required")) else 0.35
        provider = str(live_parity.get("data_provider", "")).strip().lower()
        provider_score = 1.0 if provider == "alpaca" else 0.1
        capability_score = 1.0 if bool(live_parity.get("symbol_capabilities_enforced")) else 0.4
        execution_model_name = str(live_parity.get("execution_fill_model", "")).strip().lower()
        queue_sim_enabled = bool(live_parity.get("simulate_queue_position"))
        liquidity_limits_enabled = bool(live_parity.get("enforce_liquidity_limits"))
        fee_reconcile_mode = str(live_parity.get("fee_reconciliation_mode", "")).strip().lower()
        execution_model_score = 1.0 if (
            execution_model_name == "intrabar_latency_queue_participation"
            and queue_sim_enabled
            and liquidity_limits_enabled
            and fee_reconcile_mode == "broker_schedule_rounded"
        ) else 0.35
        trades_score = min(1.0, max(0.0, float(total_trades) / 80.0))
        blocker_penalty = min(1.0, float(blocked_total) / max(50.0, float(entry_checks) + 1.0))

        overall_score = (
            0.21 * strict_data_score
            + 0.18 * provider_score
            + 0.16 * capability_score
            + 0.12 * execution_model_score
            + 0.13 * min(1.0, data_coverage_pct / 100.0)
            + 0.11 * min(1.0, executable_universe_pct / 100.0)
            + 0.09 * trades_score
        )
        overall_score *= (1.0 - (0.18 * blocker_penalty))
        overall_score *= (1.0 - (0.10 * min(1.0, partial_fill_ratio)))
        overall_score_pct = max(0.0, min(100.0, overall_score * 100.0))
        if overall_score_pct >= 80.0:
            confidence_band = "high"
        elif overall_score_pct >= 60.0:
            confidence_band = "medium"
        else:
            confidence_band = "low"

        notes: List[str] = []
        if provider != "alpaca":
            notes.append("Data provider fallback detected; live confidence reduced.")
        if data_coverage_pct < 95.0:
            notes.append("Some requested symbols lacked usable history in the selected window.")
        if executable_universe_pct < 80.0:
            notes.append("A material share of requested symbols was filtered out by live execution constraints.")
        if bool(live_parity.get("emulate_live_trading")) and not bool(live_parity.get("symbol_capabilities_enforced")):
            notes.append("Broker tradable/fractionable capability checks were not fully enforced.")
        if bool(live_parity.get("emulate_live_trading")) and execution_model_name != "intrabar_latency_queue_participation":
            notes.append("Execution simulator is not using intrabar latency/queue-participation model.")
        if partial_entry_fills > 0:
            notes.append("Entry liquidity caps caused partial fills; live execution sizing may be harder than requested.")
        if total_trades < 20:
            notes.append("Low executed trade count can make optimization rankings unstable.")
        if bool(live_parity.get("micro_policy_active")):
            notes.append("Micro strategy workflow is active; scorecard pass/fail gates are applied for deployment readiness.")
        if bool(live_parity.get("investing_policy_active")):
            notes.append("ETF investing workflow is active; low-frequency discipline and exposure guardrails are applied.")

        return {
            "overall_confidence_score": round(overall_score_pct, 2),
            "confidence_band": confidence_band,
            "data_coverage_pct": round(data_coverage_pct, 2),
            "executable_universe_pct": round(executable_universe_pct, 2),
            "symbols_filtered_out_count": int(symbols_filtered_out_count),
            "signal_realization_pct": round(signal_realization_pct, 2),
            "entry_checks": int(entry_checks),
            "entry_signals": int(entry_signals),
            "entries_opened": int(entries_opened),
            "partial_entry_fills": int(partial_entry_fills),
            "total_trades": int(total_trades),
            "blocked_events_total": int(blocked_total),
            "investing_policy_active": bool(live_parity.get("investing_policy_active", False)),
            "investing_policy_reason": str(live_parity.get("investing_policy_reason", "")),
            "notes": notes,
        }

    @staticmethod
    def _estimate_micro_spread_proxy_bps(
        *,
        daily_volume: float,
        close: float,
        slippage_bps: float,
        queue_position_bps: float,
    ) -> float:
        """Heuristic spread proxy for bar-based simulations without L1 quote history."""
        volume = max(0.0, float(daily_volume or 0.0))
        px = max(0.01, float(close or 0.0))
        slippage = max(0.0, float(slippage_bps or 0.0))
        queue = max(0.0, float(queue_position_bps or 0.0))
        if volume <= 0:
            liquidity_penalty = 45.0
        else:
            liquidity_penalty = min(45.0, 3_000_000.0 / volume)
        microcap_penalty = 0.0
        if px < 2.0:
            microcap_penalty = 20.0
        elif px < 5.0:
            microcap_penalty = 10.0
        return max(1.0, slippage + (queue * 0.7) + liquidity_penalty + microcap_penalty)

    @staticmethod
    def _normalize_up(value: float, low: float, high: float) -> float:
        if high <= low:
            return 0.0
        scaled = (float(value) - float(low)) / (float(high) - float(low))
        return max(0.0, min(1.0, scaled))

    @staticmethod
    def _normalize_down(value: float, low: float, high: float) -> float:
        if high <= low:
            return 0.0
        scaled = (float(high) - float(value)) / (float(high) - float(low))
        return max(0.0, min(1.0, scaled))

    def _annualize_return_pct(self, total_return_pct: float, *, span_days: int) -> float:
        days = max(1, int(span_days))
        gross = 1.0 + (float(total_return_pct) / 100.0)
        if gross <= 0:
            return -100.0
        annualized = (gross ** (365.0 / days)) - 1.0
        return max(-100.0, min(1_000.0, annualized * 100.0))

    def _approximate_xirr(
        self,
        *,
        start_date: date_type,
        end_date: date_type,
        initial_capital: float,
        contribution_amount: float,
        contribution_frequency: str,
        contribution_events: int,
        final_capital: float,
    ) -> float:
        """Cashflow-aware annualized return approximation for recurring-funding workflows."""
        span_days = max(1, int((end_date - start_date).days) + 1)
        contribution_frequency_normalized = str(contribution_frequency or "none").strip().lower()
        if contribution_frequency_normalized not in {"weekly", "monthly"}:
            contribution_events = 0
        event_count = max(0, int(contribution_events))
        avg_invested = float(initial_capital) + (float(contribution_amount) * event_count * 0.5)
        avg_invested = max(1.0, avg_invested)
        gross = max(0.0001, float(final_capital) / avg_invested)
        annualized = (gross ** (365.0 / span_days)) - 1.0
        return max(-100.0, min(1_000.0, annualized * 100.0))

    def _normalize_benchmark_weights(self, raw_weights: Dict[str, float]) -> Dict[str, float]:
        normalized: Dict[str, float] = {}
        total = 0.0
        for raw_symbol, raw_weight in (raw_weights or {}).items():
            symbol = str(raw_symbol or "").strip().upper()
            if not symbol:
                continue
            try:
                weight = float(raw_weight or 0.0)
            except (TypeError, ValueError):
                continue
            if weight <= 0:
                continue
            normalized[symbol] = weight
            total += weight
        if total <= 0:
            return {}
        return {symbol: (weight / total) for symbol, weight in normalized.items()}

    def _series_close_on_or_after(
        self,
        series: List[Dict[str, Any]],
        target: date_type,
    ) -> Optional[float]:
        for point in series:
            point_day = point.get("date")
            if not isinstance(point_day, date_type):
                continue
            if point_day < target:
                continue
            close = float(point.get("close", 0.0) or 0.0)
            if close > 0:
                return close
        return None

    def _series_close_on_or_before(
        self,
        series: List[Dict[str, Any]],
        target: date_type,
    ) -> Optional[float]:
        for point in reversed(series):
            point_day = point.get("date")
            if not isinstance(point_day, date_type):
                continue
            if point_day > target:
                continue
            close = float(point.get("close", 0.0) or 0.0)
            if close > 0:
                return close
        return None

    def _estimate_benchmark_total_return_pct(
        self,
        *,
        series_by_symbol: Dict[str, List[Dict[str, Any]]],
        start_date: date_type,
        end_date: date_type,
        weights: Optional[Dict[str, float]] = None,
    ) -> float:
        """
        Estimate benchmark return over the same window.

        When weights are provided, computes a weighted benchmark on those symbols.
        Otherwise falls back to equal-weight over available series_by_symbol.
        """
        if isinstance(weights, dict) and weights:
            weight_map = self._normalize_benchmark_weights(weights)
            weighted_return = 0.0
            usable_weight = 0.0
            for symbol, weight in weight_map.items():
                series = series_by_symbol.get(symbol, [])
                if not series:
                    continue
                first_close = self._series_close_on_or_after(series, start_date)
                last_close = self._series_close_on_or_before(series, end_date)
                if first_close is None or last_close is None or first_close <= 0:
                    continue
                symbol_return = ((last_close - first_close) / first_close) * 100.0
                weighted_return += symbol_return * weight
                usable_weight += weight
            if usable_weight > 0:
                return float(weighted_return / usable_weight)
            return 0.0

        returns: List[float] = []
        for _, series in series_by_symbol.items():
            if not series:
                continue
            first_close = self._series_close_on_or_after(series, start_date)
            last_close = self._series_close_on_or_before(series, end_date)
            if first_close is None or last_close is None or first_close <= 0:
                continue
            returns.append(((last_close - first_close) / first_close) * 100.0)
        if not returns:
            return 0.0
        return float(sum(returns) / len(returns))

    def _simulate_weighted_dca_benchmark(
        self,
        *,
        series_by_symbol: Dict[str, List[Dict[str, Any]]],
        weights: Dict[str, float],
        start_date: date_type,
        end_date: date_type,
        initial_capital: float,
        contribution_amount: float,
        contribution_dates: List[date_type],
    ) -> Optional[Dict[str, Any]]:
        """Simulate a weighted DCA benchmark sleeve with recurring contributions."""
        weight_map = self._normalize_benchmark_weights(weights)
        if not weight_map:
            return None

        shares: Dict[str, float] = {symbol: 0.0 for symbol in weight_map.keys()}

        def _allocate(dollars: float, day: date_type) -> bool:
            if dollars <= 0:
                return False
            prices: Dict[str, float] = {}
            for symbol in weight_map.keys():
                series = series_by_symbol.get(symbol, [])
                if not series:
                    continue
                px = self._series_close_on_or_after(series, day)
                if px is None or px <= 0:
                    continue
                prices[symbol] = px
            if not prices:
                return False
            usable_weights = {
                symbol: weight_map[symbol]
                for symbol in prices.keys()
            }
            total_weight = sum(usable_weights.values())
            if total_weight <= 0:
                return False
            for symbol, price in prices.items():
                alloc_weight = usable_weights[symbol] / total_weight
                alloc_dollars = dollars * alloc_weight
                shares[symbol] += alloc_dollars / price
            return True

        _allocate(max(0.0, float(initial_capital)), start_date)
        applied_contrib_events = 0
        for day in contribution_dates:
            if _allocate(max(0.0, float(contribution_amount)), day):
                applied_contrib_events += 1

        final_value = 0.0
        for symbol, qty in shares.items():
            if qty <= 0:
                continue
            series = series_by_symbol.get(symbol, [])
            if not series:
                continue
            px = self._series_close_on_or_before(series, end_date)
            if px is None or px <= 0:
                continue
            final_value += qty * px
        invested = float(initial_capital) + (float(contribution_amount) * applied_contrib_events)
        if invested <= 0:
            return None
        total_return_pct = ((final_value - invested) / invested) * 100.0
        return {
            "final_capital": float(final_value),
            "invested_capital": float(invested),
            "total_return_pct": float(total_return_pct),
            "contribution_events_applied": int(applied_contrib_events),
            "weights": {symbol: round(weight, 4) for symbol, weight in weight_map.items()},
        }

    def _compute_subperiod_stability(self, equity_curve: List[Dict[str, Any]]) -> Dict[str, float]:
        """Compute monthly/quarterly positive-period ratios for stability scoring."""
        monthly_values: Dict[tuple[int, int], List[float]] = {}
        quarterly_values: Dict[tuple[int, int], List[float]] = {}
        for row in equity_curve:
            ts_raw = str(row.get("timestamp", "") or "").strip()
            if not ts_raw:
                continue
            candidate = f"{ts_raw[:-1]}+00:00" if ts_raw.endswith("Z") else ts_raw
            try:
                ts = datetime.fromisoformat(candidate)
            except ValueError:
                continue
            equity = float(row.get("equity", 0.0) or 0.0)
            if equity <= 0:
                continue
            m_key = (ts.year, ts.month)
            q_key = (ts.year, ((ts.month - 1) // 3) + 1)
            monthly_values.setdefault(m_key, []).append(equity)
            quarterly_values.setdefault(q_key, []).append(equity)

        def _period_returns(period_map: Dict[tuple[int, int], List[float]]) -> List[float]:
            rows: List[float] = []
            for _, values in sorted(period_map.items()):
                if len(values) < 2 or values[0] <= 0:
                    continue
                rows.append(((values[-1] - values[0]) / values[0]) * 100.0)
            return rows

        month_returns = _period_returns(monthly_values)
        quarter_returns = _period_returns(quarterly_values)
        month_positive_ratio = (
            (sum(1 for row in month_returns if row > 0) / len(month_returns)) * 100.0
            if month_returns
            else 0.0
        )
        quarter_positive_ratio = (
            (sum(1 for row in quarter_returns if row > 0) / len(quarter_returns)) * 100.0
            if quarter_returns
            else 0.0
        )
        month_vol = statistics.pstdev(month_returns) if len(month_returns) > 1 else 0.0
        quarter_vol = statistics.pstdev(quarter_returns) if len(quarter_returns) > 1 else 0.0
        stability_score = (
            (0.60 * month_positive_ratio)
            + (0.40 * quarter_positive_ratio)
            - min(35.0, (month_vol * 1.2) + (quarter_vol * 1.0))
        )
        stability_score = max(0.0, min(100.0, stability_score))
        return {
            "positive_ratio_pct": float(month_positive_ratio),
            "quarterly_positive_ratio_pct": float(quarter_positive_ratio),
            "stability_score_pct": float(stability_score),
        }

    @staticmethod
    def _parse_row_date(row: Dict[str, Any]) -> Optional[date_type]:
        ts_raw = str(row.get("timestamp", "") or "").strip()
        if not ts_raw:
            return None
        candidate = f"{ts_raw[:-1]}+00:00" if ts_raw.endswith("Z") else ts_raw
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        return parsed.date()

    def _build_adjusted_equity_series(
        self,
        *,
        equity_curve: List[Dict[str, Any]],
        contribution_dates: List[date_type],
        contribution_amount: float,
    ) -> List[Dict[str, Any]]:
        contribution_map: Dict[date_type, int] = {}
        for day in contribution_dates:
            contribution_map[day] = int(contribution_map.get(day, 0)) + 1
        running_contributions = 0.0
        rows: List[Dict[str, Any]] = []
        for row in equity_curve:
            row_day = self._parse_row_date(row)
            if row_day is None:
                continue
            if contribution_amount > 0:
                running_contributions += float(contribution_map.get(row_day, 0)) * float(contribution_amount)
            equity = float(row.get("equity", 0.0) or 0.0)
            rows.append(
                {
                    "timestamp": str(row.get("timestamp", "")),
                    "date": row_day,
                    "equity": equity,
                    "contributions_to_date": running_contributions,
                    "adjusted_equity": equity - running_contributions,
                }
            )
        return rows

    def _calculate_adjusted_drawdown_and_tuw(
        self,
        adjusted_equity_curve: List[Dict[str, Any]],
    ) -> Tuple[float, int]:
        if not adjusted_equity_curve:
            return (0.0, 0)
        peak = float(adjusted_equity_curve[0].get("adjusted_equity", 0.0) or 0.0)
        max_drawdown = 0.0
        max_tuw_days = 0
        underwater_since: Optional[date_type] = None
        last_day = adjusted_equity_curve[0].get("date")
        if not isinstance(last_day, date_type):
            last_day = None
        for row in adjusted_equity_curve:
            row_day = row.get("date")
            if isinstance(row_day, date_type):
                last_day = row_day
            value = float(row.get("adjusted_equity", 0.0) or 0.0)
            if value > peak:
                peak = value
                if underwater_since is not None and isinstance(row_day, date_type):
                    max_tuw_days = max(max_tuw_days, (row_day - underwater_since).days)
                underwater_since = None
                continue
            if peak > 0:
                drawdown = ((peak - value) / peak) * 100.0
                max_drawdown = max(max_drawdown, drawdown)
            if value < peak and underwater_since is None and isinstance(row_day, date_type):
                underwater_since = row_day
            if value >= peak and underwater_since is not None and isinstance(row_day, date_type):
                max_tuw_days = max(max_tuw_days, (row_day - underwater_since).days)
                underwater_since = None
        if underwater_since is not None and isinstance(last_day, date_type):
            max_tuw_days = max(max_tuw_days, (last_day - underwater_since).days)
        return (float(max_drawdown), int(max_tuw_days))

    def _calculate_xirr_from_cashflows(
        self,
        *,
        start_date: date_type,
        end_date: date_type,
        initial_capital: float,
        contribution_amount: float,
        contribution_dates: List[date_type],
        final_capital: float,
    ) -> float:
        cashflows: List[Tuple[date_type, float]] = [(start_date, -abs(float(initial_capital)))]
        contrib = max(0.0, float(contribution_amount))
        if contrib > 0:
            for day in contribution_dates:
                cashflows.append((day, -contrib))
        cashflows.append((end_date, max(0.0, float(final_capital))))
        has_positive = any(float(amount) > 0 for _, amount in cashflows)
        has_negative = any(float(amount) < 0 for _, amount in cashflows)
        if not (has_positive and has_negative):
            return 0.0

        base_day = cashflows[0][0]
        timed_flows = [
            ((day - base_day).days / 365.0, float(amount))
            for day, amount in cashflows
        ]

        def _xnpv(rate: float) -> float:
            total = 0.0
            for years, amount in timed_flows:
                total += amount / ((1.0 + rate) ** years)
            return total

        def _dxnpv(rate: float) -> float:
            total = 0.0
            for years, amount in timed_flows:
                if years == 0:
                    continue
                total -= (years * amount) / ((1.0 + rate) ** (years + 1.0))
            return total

        rate = 0.10
        for _ in range(40):
            try:
                f = _xnpv(rate)
                df = _dxnpv(rate)
            except (OverflowError, ZeroDivisionError):
                break
            if abs(df) < 1e-10:
                break
            next_rate = rate - (f / df)
            if not math.isfinite(next_rate) or next_rate <= -0.9999 or next_rate > 20.0:
                break
            if abs(next_rate - rate) < 1e-8:
                rate = next_rate
                return max(-100.0, min(1_000.0, rate * 100.0))
            rate = next_rate

        low = -0.9999
        high = 20.0
        low_val = _xnpv(low)
        high_val = _xnpv(high)
        if low_val == 0:
            return max(-100.0, min(1_000.0, low * 100.0))
        if high_val == 0:
            return max(-100.0, min(1_000.0, high * 100.0))
        if low_val * high_val > 0:
            return self._approximate_xirr(
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                contribution_amount=contribution_amount,
                contribution_frequency="none",
                contribution_events=0,
                final_capital=final_capital,
            )
        for _ in range(80):
            mid = (low + high) / 2.0
            mid_val = _xnpv(mid)
            if abs(mid_val) < 1e-8:
                return max(-100.0, min(1_000.0, mid * 100.0))
            if low_val * mid_val < 0:
                high = mid
                high_val = mid_val
            else:
                low = mid
                low_val = mid_val
        rate = (low + high) / 2.0
        return max(-100.0, min(1_000.0, rate * 100.0))

    def _compute_three_subperiod_profitability(
        self,
        adjusted_equity_curve: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if len(adjusted_equity_curve) < 6:
            return {
                "segment_returns_pct": [0.0, 0.0, 0.0],
                "positive_segments": 0,
                "segments_total": 3,
            }
        chunk = max(2, len(adjusted_equity_curve) // 3)
        ranges = [
            adjusted_equity_curve[0:chunk],
            adjusted_equity_curve[chunk:(chunk * 2)],
            adjusted_equity_curve[(chunk * 2):],
        ]
        returns: List[float] = []
        positives = 0
        for rows in ranges:
            if len(rows) < 2:
                returns.append(0.0)
                continue
            start_val = float(rows[0].get("adjusted_equity", 0.0) or 0.0)
            end_val = float(rows[-1].get("adjusted_equity", 0.0) or 0.0)
            if start_val <= 0:
                ret = 0.0
            else:
                ret = ((end_val - start_val) / start_val) * 100.0
            returns.append(float(ret))
            if ret > 0:
                positives += 1
        while len(returns) < 3:
            returns.append(0.0)
        return {
            "segment_returns_pct": [round(float(value), 4) for value in returns[:3]],
            "positive_segments": int(positives),
            "segments_total": 3,
        }

    def _build_scenario2_report(
        self,
        *,
        start_date: date_type,
        end_date: date_type,
        initial_capital: float,
        contribution_amount: float,
        contribution_frequency: str,
        contribution_dates: List[date_type],
        total_contributions: float,
        final_capital: float,
        benchmark_final_capital: float,
        xirr_pct: float,
        benchmark_xirr_pct: float,
        xirr_excess_pct: float,
        equity_curve: List[Dict[str, Any]],
        trades: List[Dict[str, Any]],
        diagnostics: Dict[str, Any],
        investing_core_dca_pct: float,
        investing_active_sleeve_pct: float,
        active_exposure_samples: List[float],
        total_exposure_samples: List[float],
        concentration_samples: List[float],
        no_activity_days: int,
    ) -> Dict[str, Any]:
        span_days = max(1, int((end_date - start_date).days) + 1)
        span_months = float(span_days) / 30.4375
        adjusted_curve = self._build_adjusted_equity_series(
            equity_curve=equity_curve,
            contribution_dates=contribution_dates,
            contribution_amount=contribution_amount,
        )
        adjusted_drawdown_pct, time_under_water_days = self._calculate_adjusted_drawdown_and_tuw(adjusted_curve)
        adjusted_equity_final = float(final_capital) - float(total_contributions)

        strategy_xirr_pct = self._calculate_xirr_from_cashflows(
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            contribution_amount=contribution_amount,
            contribution_dates=contribution_dates,
            final_capital=final_capital,
        )
        benchmark_xirr_calc_pct = self._calculate_xirr_from_cashflows(
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            contribution_amount=contribution_amount,
            contribution_dates=contribution_dates,
            final_capital=benchmark_final_capital,
        )
        alpha_xirr_pct = float(strategy_xirr_pct - benchmark_xirr_calc_pct)
        if not math.isfinite(alpha_xirr_pct):
            alpha_xirr_pct = float(xirr_excess_pct)

        completed_round_trips = len(trades)
        win_count = sum(1 for trade in trades if float(trade.get("pnl", 0.0) or 0.0) > 0.0)
        loss_count = sum(1 for trade in trades if float(trade.get("pnl", 0.0) or 0.0) < 0.0)
        win_rate_pct = (win_count / completed_round_trips * 100.0) if completed_round_trips > 0 else 0.0
        avg_win, avg_loss = self._calculate_avg_win_loss(trades)
        payoff_ratio = (avg_win / abs(avg_loss)) if avg_loss < 0 else 0.0
        expectancy = self._calculate_expectancy(trades)
        execution_summary = diagnostics.get("execution_summary")
        if not isinstance(execution_summary, dict):
            execution_summary = {}
        buy_count = int(execution_summary.get("entry_fills", completed_round_trips) or completed_round_trips)
        sell_count = int(execution_summary.get("exit_fills", completed_round_trips) or completed_round_trips)

        sells_by_month: Dict[str, int] = {}
        short_term_sells = 0
        realized_st_gains = 0.0
        realized_st_losses = 0.0
        realized_lt_gains = 0.0
        realized_lt_losses = 0.0
        for trade in trades:
            pnl = float(trade.get("pnl", 0.0) or 0.0)
            days_held = int(trade.get("days_held", 0) or 0)
            exit_raw = str(trade.get("exit_date", "") or "")
            exit_key = exit_raw[:7] if len(exit_raw) >= 7 else ""
            if exit_key:
                sells_by_month[exit_key] = int(sells_by_month.get(exit_key, 0)) + 1
            if days_held < 365:
                short_term_sells += 1
                if pnl >= 0:
                    realized_st_gains += pnl
                else:
                    realized_st_losses += pnl
            else:
                if pnl >= 0:
                    realized_lt_gains += pnl
                else:
                    realized_lt_losses += pnl
        sells_per_month = float(sell_count) / max(1.0, span_months)
        short_term_sell_ratio = (float(short_term_sells) / float(max(1, sell_count))) if sell_count > 0 else 0.0

        universe_context = diagnostics.get("universe_context")
        if not isinstance(universe_context, dict):
            universe_context = {}
        short_term_tax_rate = float(universe_context.get("short_term_tax_rate", 0.30) or 0.30)
        long_term_tax_rate = float(universe_context.get("long_term_tax_rate", 0.15) or 0.15)
        short_term_tax_rate = max(0.0, min(0.50, short_term_tax_rate))
        long_term_tax_rate = max(0.0, min(0.40, long_term_tax_rate))
        net_st = realized_st_gains + realized_st_losses
        net_lt = realized_lt_gains + realized_lt_losses
        estimated_tax_drag = (max(0.0, net_st) * short_term_tax_rate) + (max(0.0, net_lt) * long_term_tax_rate)
        after_tax_final_capital = max(0.0, float(final_capital) - estimated_tax_drag)
        after_tax_xirr_pct = self._calculate_xirr_from_cashflows(
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            contribution_amount=contribution_amount,
            contribution_dates=contribution_dates,
            final_capital=after_tax_final_capital,
        )

        subperiod = self._compute_three_subperiod_profitability(adjusted_curve)
        subperiod_positive_segments = int(subperiod.get("positive_segments", 0) or 0)
        thresholds = get_scenario2_thresholds()
        minimum_trades_required = max(0, int(thresholds.get("min_trades", ETF_INVESTING_EVAL_MIN_TRADES) or ETF_INVESTING_EVAL_MIN_TRADES))
        minimum_months_required = max(0.0, float(thresholds.get("min_months", ETF_INVESTING_EVAL_MIN_MONTHS) or ETF_INVESTING_EVAL_MIN_MONTHS))
        alpha_min_pct = float(thresholds.get("alpha_min_pct", 2.0) or 2.0)
        max_drawdown_gate_pct = float(thresholds.get("max_drawdown_pct", 25.0) or 25.0)
        max_sells_per_month = float(thresholds.get("max_sells_per_month", 6.0) or 6.0)
        max_short_term_sell_ratio = float(thresholds.get("max_short_term_sell_ratio", 0.60) or 0.60)
        sufficient_trades = bool(completed_round_trips >= minimum_trades_required)
        sufficient_months = bool(span_months >= minimum_months_required)
        inconclusive = not (sufficient_trades and sufficient_months)
        turnover_safe = bool(sells_per_month <= max_sells_per_month and short_term_sell_ratio <= max_short_term_sell_ratio)
        gate_results = {
            "minimum_trades": sufficient_trades,
            "minimum_months": sufficient_months,
            "xirr_edge_vs_benchmark": bool(alpha_xirr_pct >= alpha_min_pct),
            "max_adjusted_drawdown_within_limit": bool(adjusted_drawdown_pct <= max_drawdown_gate_pct),
            "subperiod_profitability_2_of_3": bool(subperiod_positive_segments >= 2),
            "taxable_turnover_safe": turnover_safe,
        }
        pass_flag = bool((not inconclusive) and all(gate_results.values()))
        status = "inconclusive" if inconclusive else ("pass" if pass_flag else "fail")
        reasons: List[str] = []
        if inconclusive:
            if not sufficient_trades:
                reasons.append(
                    f"Needs at least {minimum_trades_required} completed trades (have {completed_round_trips})."
                )
            if not sufficient_months:
                reasons.append(
                    f"Needs at least {minimum_months_required:.0f} months of history (have {span_months:.1f})."
                )
        if not gate_results["xirr_edge_vs_benchmark"]:
            reasons.append(f"XIRR edge vs benchmark is below +{alpha_min_pct:.1f}%.")
        if not gate_results["max_adjusted_drawdown_within_limit"]:
            reasons.append(f"Adjusted-equity drawdown exceeds {max_drawdown_gate_pct:.1f}%.")
        if not gate_results["subperiod_profitability_2_of_3"]:
            reasons.append("Fewer than 2 of 3 subperiods are profitable.")
        if not gate_results["taxable_turnover_safe"]:
            reasons.append(
                f"Turnover/short-term sell rate is too high for taxable profile "
                f"(limits: {max_sells_per_month:.2f} sells/month, {max_short_term_sell_ratio * 100:.1f}% short-term)."
            )

        alpha_component = self._normalize_up(alpha_xirr_pct, -2.0, 6.0)
        drawdown_component = self._normalize_down(adjusted_drawdown_pct, 8.0, 35.0)
        stability_component = max(0.0, min(1.0, float(subperiod_positive_segments) / 3.0))
        turnover_component = (
            0.65 * self._normalize_down(sells_per_month, 1.0, 8.0)
            + 0.35 * self._normalize_down(short_term_sell_ratio, 0.15, 0.90)
        )
        tax_drag_pct_of_final = (estimated_tax_drag / max(1.0, final_capital)) * 100.0
        tax_component = self._normalize_down(tax_drag_pct_of_final, 0.5, 8.0)
        score = 100.0 * (
            0.30 * alpha_component
            + 0.26 * drawdown_component
            + 0.16 * stability_component
            + 0.16 * turnover_component
            + 0.12 * tax_component
        )
        trades_conf = min(1.0, float(completed_round_trips) / 100.0)
        months_conf = min(1.0, span_months / 24.0)
        slippage_bps = float(execution_summary.get("average_effective_slippage_bps", 0.0) or 0.0)
        execution_conf = self._normalize_down(slippage_bps, 5.0, 80.0)
        confidence_score = 100.0 * (
            0.34 * trades_conf
            + 0.30 * months_conf
            + 0.20 * stability_component
            + 0.16 * execution_conf
        )
        if inconclusive:
            confidence_score = min(confidence_score, 59.0)
        score = max(0.0, min(100.0, score))
        confidence_score = max(0.0, min(100.0, confidence_score))

        trading_days = max(1, int(diagnostics.get("trading_days_evaluated", 0) or 0))
        active_exposure_avg = float(statistics.mean(active_exposure_samples)) if active_exposure_samples else 0.0
        total_exposure_avg = float(statistics.mean(total_exposure_samples)) if total_exposure_samples else 0.0
        max_single_symbol_exposure_pct = max(concentration_samples) if concentration_samples else 0.0

        return {
            "active": True,
            "inputs": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "initial_capital": round(float(initial_capital), 2),
                "contribution_amount": round(float(contribution_amount), 2),
                "contribution_frequency": str(contribution_frequency),
                "contribution_events": int(len(contribution_dates)),
                "bucket_split": {
                    "core_dca_pct": round(float(investing_core_dca_pct), 4),
                    "active_sleeve_pct": round(float(investing_active_sleeve_pct), 4),
                },
            },
            "core_results": {
                "final_equity": round(float(final_capital), 2),
                "total_contributions": round(float(total_contributions), 2),
                "adjusted_equity_final": round(float(adjusted_equity_final), 2),
                "xirr_strategy_pct": round(float(strategy_xirr_pct), 4),
                "xirr_strategy_pct_legacy": round(float(xirr_pct), 4),
                "xirr_benchmark_pct": round(float(benchmark_xirr_calc_pct), 4),
                "xirr_benchmark_pct_legacy": round(float(benchmark_xirr_pct), 4),
                "alpha_xirr_pct": round(float(alpha_xirr_pct), 4),
                "benchmark_final_equity": round(float(benchmark_final_capital), 2),
            },
            "risk": {
                "max_drawdown_adjusted_pct": round(float(adjusted_drawdown_pct), 4),
                "time_under_water_days": int(time_under_water_days),
                "active_exposure_avg_pct": round(float(active_exposure_avg), 4),
                "total_exposure_avg_pct": round(float(total_exposure_avg), 4),
                "max_single_symbol_exposure_pct": round(float(max_single_symbol_exposure_pct), 4),
                "no_activity_days": int(no_activity_days),
                "no_activity_ratio_pct": round((float(no_activity_days) / float(trading_days)) * 100.0, 4),
            },
            "trading": {
                "buy_count": int(max(0, buy_count)),
                "sell_count": int(max(0, sell_count)),
                "completed_round_trips": int(completed_round_trips),
                "win_rate_pct": round(float(win_rate_pct), 4),
                "average_win": round(float(avg_win), 4),
                "average_loss": round(float(avg_loss), 4),
                "payoff_ratio": round(float(payoff_ratio), 6),
                "expectancy": round(float(expectancy), 6),
                "trades_per_month": round(float(completed_round_trips) / max(1.0, span_months), 4),
                "sells_per_month": round(float(sells_per_month), 4),
                "short_term_sells": int(short_term_sells),
                "short_term_sell_ratio": round(float(short_term_sell_ratio), 6),
                "sells_by_month": dict(sorted(sells_by_month.items())),
            },
            "tax_estimate": {
                "short_term_rate": round(float(short_term_tax_rate), 6),
                "long_term_rate": round(float(long_term_tax_rate), 6),
                "realized_short_term_gains": round(float(realized_st_gains), 4),
                "realized_short_term_losses": round(float(realized_st_losses), 4),
                "realized_long_term_gains": round(float(realized_lt_gains), 4),
                "realized_long_term_losses": round(float(realized_lt_losses), 4),
                "estimated_tax_drag": round(float(estimated_tax_drag), 4),
                "after_tax_final_equity": round(float(after_tax_final_capital), 2),
                "after_tax_xirr_pct": round(float(after_tax_xirr_pct), 4),
            },
            "stability": {
                "subperiod_positive_segments": int(subperiod_positive_segments),
                "subperiod_total_segments": int(subperiod.get("segments_total", 3) or 3),
                "subperiod_segment_returns_pct": list(subperiod.get("segment_returns_pct", [0.0, 0.0, 0.0])),
            },
            "readiness": {
                "status": status,
                "inconclusive": bool(inconclusive),
                "pass": bool(pass_flag),
                "minimum_trades_required": int(minimum_trades_required),
                "minimum_months_required": float(minimum_months_required),
                "thresholds": {
                    "alpha_min_pct": round(float(alpha_min_pct), 4),
                    "max_drawdown_pct": round(float(max_drawdown_gate_pct), 4),
                    "min_trades": int(minimum_trades_required),
                    "min_months": round(float(minimum_months_required), 4),
                    "max_sells_per_month": round(float(max_sells_per_month), 4),
                    "max_short_term_sell_ratio": round(float(max_short_term_sell_ratio), 6),
                },
                "gate_results": gate_results,
                "reasons": reasons,
            },
            "scorecard": {
                "score": round(float(score), 2),
                "confidence_score": round(float(confidence_score), 2),
                "status": status,
                "pass": bool(pass_flag),
                "inconclusive": bool(inconclusive),
            },
        }

    def _build_micro_scorecard(
        self,
        *,
        diagnostics: Dict[str, Any],
        total_trades: int,
        max_drawdown: float,
        expectancy_r: float,
        profit_factor: float,
        payoff_ratio: float,
        twr_annualized_pct: float,
        xirr_excess_pct: float,
        stability_score_pct: float,
        max_single_trade_loss_pct_base: float,
    ) -> Dict[str, Any]:
        live_parity = diagnostics.get("live_parity")
        if not isinstance(live_parity, dict):
            live_parity = {}
        active = bool(diagnostics.get("micro_policy_active", False) or live_parity.get("micro_policy_active", False))
        mode = str(diagnostics.get("micro_strategy_mode", "auto"))
        reason = str(diagnostics.get("micro_policy_reason", ""))
        universe_context = diagnostics.get("universe_context")
        if not isinstance(universe_context, dict):
            universe_context = {}
        asset_type = str(
            live_parity.get("asset_type", universe_context.get("asset_type", "stock"))
        ).strip().lower()
        if asset_type not in {"stock", "etf"}:
            asset_type = "stock"

        min_trades_gate = 25 if asset_type == "etf" else 40
        max_drawdown_gate = 14.0 if asset_type == "etf" else 22.0
        profit_factor_gate = 1.10 if asset_type == "etf" else 1.15
        configured_single_trade_loss_cap = float(diagnostics.get("micro_single_trade_loss_pct", 1.5) or 1.5)

        blocked = diagnostics.get("blocked_reasons")
        blocked_dict = blocked if isinstance(blocked, dict) else {}
        entry_checks = max(1, int(diagnostics.get("entry_checks", 0) or 0))
        rejection_events = int(blocked_dict.get("risk_validation_failed", 0) or 0) + int(blocked_dict.get("invalid_position_size", 0) or 0)
        rejection_rate_pct = (rejection_events / entry_checks) * 100.0
        slippage_effective = float((diagnostics.get("execution_summary") or {}).get("average_effective_slippage_bps", 0.0) or 0.0)
        micro_blockers = (
            int(blocked_dict.get("micro_single_trade_loss", 0) or 0)
            + int(blocked_dict.get("micro_cash_reserve", 0) or 0)
            + int(blocked_dict.get("micro_spread_guardrail", 0) or 0)
        )
        capital_fit_ratio = 1.0 - min(1.0, float(micro_blockers) / max(1.0, float(entry_checks)))

        hard_gates = {
            "min_trades": bool(total_trades >= min_trades_gate),
            "max_drawdown": bool(float(max_drawdown) <= max_drawdown_gate),
            "expectancy_r": bool(float(expectancy_r) > 0.03),
            "profit_factor": bool(float(profit_factor) >= profit_factor_gate),
            "rejection_rate": bool(float(rejection_rate_pct) <= 3.0),
            "single_trade_loss": bool(float(max_single_trade_loss_pct_base) <= configured_single_trade_loss_cap),
        }
        hard_pass = all(hard_gates.values())

        risk_component = (
            0.65 * self._normalize_down(float(max_drawdown), 5.0, 25.0)
            + 0.35 * self._normalize_down(float(max_single_trade_loss_pct_base), 0.5, 3.0)
        )
        edge_component = (
            0.45 * self._normalize_up(float(expectancy_r), 0.02, 0.20)
            + 0.30 * self._normalize_up(float(profit_factor), 1.0, 2.0)
            + 0.25 * self._normalize_up(float(payoff_ratio), 0.8, 2.5)
        )
        flow_component = (
            0.60 * self._normalize_up(float(twr_annualized_pct), -10.0, 25.0)
            + 0.40 * self._normalize_up(float(xirr_excess_pct), -5.0, 12.0)
        )
        stability_component = self._normalize_up(float(stability_score_pct), 40.0, 90.0)
        execution_component = (
            0.65 * self._normalize_down(float(rejection_rate_pct), 0.0, 5.0)
            + 0.35 * self._normalize_down(float(slippage_effective), 5.0, 80.0)
        )
        capital_fit_component = max(0.0, min(1.0, float(capital_fit_ratio)))

        final_score = 100.0 * (
            0.24 * risk_component
            + 0.22 * edge_component
            + 0.18 * flow_component
            + 0.14 * stability_component
            + 0.12 * execution_component
            + 0.10 * capital_fit_component
        )

        statistical_confidence = 100.0 * min(1.0, float(total_trades) / float(max(1, min_trades_gate * 2)))
        regime_stability = max(0.0, min(100.0, float(stability_score_pct)))
        execution_confidence = execution_component * 100.0
        capital_realism = capital_fit_component * 100.0
        confidence_score = (
            0.35 * statistical_confidence
            + 0.25 * regime_stability
            + 0.20 * execution_confidence
            + 0.20 * capital_realism
        )

        pass_flag = bool(hard_pass and final_score >= 70.0 and confidence_score >= 65.0)
        if pass_flag:
            verdict = "pass"
        elif hard_pass and final_score >= 60.0 and confidence_score >= 55.0:
            verdict = "watchlist"
        else:
            verdict = "fail"

        return {
            "active": bool(active),
            "mode": mode,
            "reason": reason,
            "asset_type": asset_type,
            "pass": pass_flag,
            "verdict": verdict,
            "hard_gates_pass": bool(hard_pass),
            "hard_gates": hard_gates,
            "final_score": round(float(final_score), 2),
            "confidence_score": round(float(confidence_score), 2),
            "metrics": {
                "total_trades": int(total_trades),
                "max_drawdown": round(float(max_drawdown), 4),
                "expectancy_r": round(float(expectancy_r), 6),
                "profit_factor": round(float(profit_factor), 6),
                "payoff_ratio": round(float(payoff_ratio), 6),
                "twr_annualized_pct": round(float(twr_annualized_pct), 4),
                "xirr_excess_pct": round(float(xirr_excess_pct), 4),
                "stability_score_pct": round(float(stability_score_pct), 4),
                "rejection_rate_pct": round(float(rejection_rate_pct), 4),
                "max_single_trade_loss_pct_base": round(float(max_single_trade_loss_pct_base), 4),
            },
            "components": {
                "risk": round(float(risk_component * 100.0), 2),
                "edge": round(float(edge_component * 100.0), 2),
                "flow_adjusted_performance": round(float(flow_component * 100.0), 2),
                "subperiod_stability": round(float(stability_component * 100.0), 2),
                "execution_quality": round(float(execution_component * 100.0), 2),
                "capital_fit": round(float(capital_fit_component * 100.0), 2),
            },
        }

    def _build_investing_scorecard(
        self,
        *,
        diagnostics: Dict[str, Any],
        total_trades: int,
        max_drawdown: float,
        profit_factor: float,
        payoff_ratio: float,
        xirr_excess_pct: float,
        stability_score_pct: float,
        max_single_trade_loss_pct_base: float,
        span_days: int,
    ) -> Dict[str, Any]:
        """ETF-investing scorecard emphasizing discipline, risk control, and consistency."""
        live_parity = diagnostics.get("live_parity")
        if not isinstance(live_parity, dict):
            live_parity = {}
        universe_context = diagnostics.get("universe_context")
        if not isinstance(universe_context, dict):
            universe_context = {}
        asset_type = str(
            live_parity.get("asset_type", universe_context.get("asset_type", "stock"))
        ).strip().lower()
        if asset_type not in {"stock", "etf"}:
            asset_type = "stock"

        contribution_amount = float(diagnostics.get("contribution_amount", 0.0) or 0.0)
        contribution_frequency = str(diagnostics.get("contribution_frequency", "none") or "none").strip().lower()
        recurring = contribution_amount > 0 and contribution_frequency in {"weekly", "monthly"}
        active = bool(live_parity.get("investing_policy_active", False) or (asset_type == "etf" and recurring))
        reason = str(live_parity.get("investing_policy_reason", ""))

        span_days_safe = max(1, int(span_days))
        trades_per_month = float(total_trades) / max(1.0, span_days_safe / 30.0)
        blocked_dict = diagnostics.get("blocked_reasons")
        if not isinstance(blocked_dict, dict):
            blocked_dict = {}
        entry_checks = max(1, int(diagnostics.get("entry_checks", 0) or 0))
        rejection_events = int(blocked_dict.get("risk_validation_failed", 0) or 0) + int(blocked_dict.get("invalid_position_size", 0) or 0)
        rejection_rate_pct = (rejection_events / entry_checks) * 100.0
        advanced_metrics = diagnostics.get("advanced_metrics")
        if not isinstance(advanced_metrics, dict):
            advanced_metrics = {}
        quarterly_positive_ratio_pct = float(
            advanced_metrics.get(
                "subperiod_quarterly_positive_ratio_pct",
                diagnostics.get("subperiod_quarterly_positive_ratio_pct", 0.0),
            )
            or 0.0
        )

        max_drawdown_gate = 18.0 if asset_type == "etf" else 24.0
        single_trade_loss_gate = 4.0 if asset_type == "etf" else 7.0
        trades_per_month_gate = 10.0 if asset_type == "etf" else 12.0
        span_months = float(span_days_safe) / 30.4375

        hard_gates = {
            "minimum_trades_window": bool(int(total_trades) >= int(ETF_INVESTING_EVAL_MIN_TRADES)),
            "minimum_time_window": bool(span_months >= float(ETF_INVESTING_EVAL_MIN_MONTHS)),
            "max_drawdown": bool(float(max_drawdown) <= max_drawdown_gate),
            "single_trade_loss": bool(float(max_single_trade_loss_pct_base) <= single_trade_loss_gate),
            "payoff_ratio": bool(float(payoff_ratio) >= 1.2),
            "profit_factor": bool(float(profit_factor) >= 1.05),
            "xirr_edge_vs_benchmark": bool(float(xirr_excess_pct) >= 2.0),
            "subperiod_stability": bool(float(quarterly_positive_ratio_pct) >= 66.0),
            "trade_frequency": bool(float(trades_per_month) <= trades_per_month_gate),
            "rejection_rate": bool(float(rejection_rate_pct) <= 5.0),
        }
        hard_pass = all(hard_gates.values())

        risk_component = (
            0.55 * self._normalize_down(float(max_drawdown), 6.0, 25.0)
            + 0.45 * self._normalize_down(float(max_single_trade_loss_pct_base), 0.5, 6.0)
        )
        discipline_component = (
            0.65 * self._normalize_down(float(trades_per_month), 1.0, 14.0)
            + 0.35 * self._normalize_down(float(rejection_rate_pct), 0.0, 8.0)
        )
        edge_component = (
            0.45 * self._normalize_up(float(payoff_ratio), 1.0, 2.5)
            + 0.35 * self._normalize_up(float(profit_factor), 1.0, 1.8)
            + 0.20 * self._normalize_up(float(xirr_excess_pct), -5.0, 12.0)
        )
        stability_component = self._normalize_up(float(stability_score_pct), 45.0, 90.0)

        final_score = 100.0 * (
            0.34 * risk_component
            + 0.28 * discipline_component
            + 0.24 * edge_component
            + 0.14 * stability_component
        )
        trades_target = 24 if asset_type == "etf" else 36
        confidence_score = (
            0.35 * min(100.0, (float(total_trades) / max(1.0, float(trades_target))) * 100.0)
            + 0.25 * (stability_component * 100.0)
            + 0.22 * (discipline_component * 100.0)
            + 0.18 * (risk_component * 100.0)
        )
        pass_flag = bool(hard_pass and final_score >= 68.0 and confidence_score >= 60.0)
        verdict = "pass" if pass_flag else ("watchlist" if hard_pass and final_score >= 60.0 else "fail")

        return {
            "active": bool(active),
            "reason": reason,
            "asset_type": asset_type,
            "pass": pass_flag,
            "verdict": verdict,
            "hard_gates_pass": bool(hard_pass),
            "hard_gates": hard_gates,
            "final_score": round(float(final_score), 2),
            "confidence_score": round(float(confidence_score), 2),
            "metrics": {
                "total_trades": int(total_trades),
                "minimum_trades_required": int(ETF_INVESTING_EVAL_MIN_TRADES),
                "minimum_months_required": int(ETF_INVESTING_EVAL_MIN_MONTHS),
                "span_months": round(float(span_months), 3),
                "trades_per_month": round(float(trades_per_month), 4),
                "max_drawdown": round(float(max_drawdown), 4),
                "payoff_ratio": round(float(payoff_ratio), 6),
                "profit_factor": round(float(profit_factor), 6),
                "xirr_excess_pct": round(float(xirr_excess_pct), 4),
                "quarterly_positive_ratio_pct": round(float(quarterly_positive_ratio_pct), 4),
                "stability_score_pct": round(float(stability_score_pct), 4),
                "max_single_trade_loss_pct_base": round(float(max_single_trade_loss_pct_base), 4),
                "rejection_rate_pct": round(float(rejection_rate_pct), 4),
            },
            "components": {
                "risk_control": round(float(risk_component * 100.0), 2),
                "discipline": round(float(discipline_component * 100.0), 2),
                "edge_quality": round(float(edge_component * 100.0), 2),
                "stability": round(float(stability_component * 100.0), 2),
            },
        }

    def _apply_investing_parameter_overrides(
        self,
        params: Dict[str, float],
    ) -> tuple[Dict[str, float], Dict[str, Any]]:
        """
        Clamp parameters to ETF-investing discipline bands when policy is active.
        """
        calibrated = dict(params)
        adjusted: List[str] = []

        def _set(name: str, value: float) -> None:
            old = float(calibrated.get(name, value) or value)
            if abs(old - value) > 1e-9:
                adjusted.append(name)
            calibrated[name] = float(value)

        risk = min(0.5, max(0.1, float(calibrated.get("risk_per_trade", 0.5) or 0.5)))
        _set("risk_per_trade", risk)

        stop = float(calibrated.get("stop_loss_pct", 3.0) or 3.0)
        if stop < 2.0 or stop > 4.0:
            stop = 3.0
        _set("stop_loss_pct", stop)

        take_profit = float(calibrated.get("take_profit_pct", 6.0) or 6.0)
        if take_profit < 6.0 or take_profit > 8.0:
            take_profit = 6.0
        _set("take_profit_pct", take_profit)

        # Keep trade cadence deliberate in investing workflow.
        _set("dca_tranches", 1.0)
        _set("max_hold_days", max(10.0, float(calibrated.get("max_hold_days", 20.0) or 20.0)))
        _set(
            "pullback_rsi_threshold",
            max(35.0, min(50.0, float(calibrated.get("pullback_rsi_threshold", 45.0) or 45.0))),
        )
        _set(
            "pullback_sma_tolerance",
            max(1.0, min(1.02, float(calibrated.get("pullback_sma_tolerance", 1.01) or 1.01))),
        )
        _set(
            "max_consecutive_losses",
            max(1.0, min(3.0, float(calibrated.get("max_consecutive_losses", 2.0) or 2.0))),
        )
        _set(
            "max_drawdown_pct",
            max(5.0, min(20.0, float(calibrated.get("max_drawdown_pct", 12.0) or 12.0))),
        )

        return calibrated, {
            "active": True,
            "adjusted_fields": adjusted,
            "risk_per_trade_cap": 0.5,
            "stop_loss_band": [2.0, 4.0],
            "take_profit_band": [6.0, 8.0],
            "pullback_rsi_band": [35.0, 50.0],
            "pullback_sma_tolerance_band": [1.0, 1.02],
        }

    # ------------------------------------------------------------------
    # Parameter resolution
    # ------------------------------------------------------------------

    def _resolve_backtest_parameters(self, overrides: Dict[str, float]) -> Dict[str, float]:
        """Resolve supported strategy parameters with safe defaults.

        Defaults enforce TP:SL >= 2.5:1, trailing_stop >= stop_loss,
        and include max_hold_days for timely exits.
        """
        defaults: Dict[str, float] = {
            "position_size": 1000.0,
            "risk_per_trade": 1.0,
            "stop_loss_pct": 2.0,
            "take_profit_pct": 5.0,
            "trailing_stop_pct": 2.5,
            "atr_stop_mult": 2.0,
            "zscore_entry_threshold": -1.2,
            "dip_buy_threshold_pct": 1.5,
            "pullback_rsi_threshold": 45.0,
            "pullback_sma_tolerance": 1.01,
            "max_hold_days": 10.0,
            "dca_tranches": 1.0,
            "max_consecutive_losses": 3.0,
            "max_drawdown_pct": 15.0,
        }
        resolved = dict(defaults)
        for key, value in overrides.items():
            if key not in resolved:
                continue
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
            if parsed != parsed:  # NaN guard
                continue
            resolved[key] = parsed
        return resolved

    def _equity_curve_bucket_seconds_for_span(self, span_seconds: float) -> int:
        """Choose adaptive equity-curve bucket size for downsampling."""
        if span_seconds <= 2 * 86400:
            return 5 * 60
        if span_seconds <= 14 * 86400:
            return 15 * 60
        if span_seconds <= 90 * 86400:
            return 60 * 60
        if span_seconds <= 730 * 86400:
            return 24 * 60 * 60
        return 7 * 24 * 60 * 60

    def _normalize_equity_curve(
        self,
        points: List[Dict[str, Any]],
        *,
        max_points: int = 1500,
    ) -> List[Dict[str, Any]]:
        """
        Normalize equity curve for chart stability:
        1) sort and sanitize values,
        2) dedupe identical timestamps (keep latest),
        3) adaptive time-bucket resample for very large ranges.
        """
        if not points:
            return []

        normalized: List[Dict[str, Any]] = []
        for row in points:
            ts = self._parse_point_timestamp(row.get("timestamp"))
            if ts is None:
                continue
            try:
                equity = float(row.get("equity", 0.0))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(equity):
                continue
            normalized.append(
                {
                    "ts": ts.astimezone(timezone.utc),
                    "equity": round(equity, 2),
                }
            )
        if not normalized:
            return []

        normalized.sort(key=lambda item: item["ts"])

        # Collapse exact duplicate timestamps to the latest value.
        deduped: List[Dict[str, Any]] = []
        for item in normalized:
            if deduped and deduped[-1]["ts"] == item["ts"]:
                deduped[-1] = item
            else:
                deduped.append(item)
        if len(deduped) <= 2:
            return [
                {"timestamp": row["ts"].isoformat(), "equity": row["equity"]}
                for row in deduped
            ]

        span_seconds = (deduped[-1]["ts"] - deduped[0]["ts"]).total_seconds()
        bucket_seconds = self._equity_curve_bucket_seconds_for_span(span_seconds)
        if len(deduped) <= max_points:
            return [
                {"timestamp": row["ts"].isoformat(), "equity": row["equity"]}
                for row in deduped
            ]

        # Increase bucket width for very dense curves to keep payload bounded.
        if span_seconds > 0 and max_points > 0:
            adaptive_bucket = int(math.ceil(span_seconds / float(max_points)))
            bucket_seconds = max(bucket_seconds, adaptive_bucket)

        bucketed: List[Dict[str, Any]] = []
        for row in deduped:
            bucket_key = int(row["ts"].timestamp()) // max(1, int(bucket_seconds))
            if bucketed and bucketed[-1]["bucket_key"] == bucket_key:
                bucketed[-1]["timestamp"] = row["ts"].isoformat()
                bucketed[-1]["equity"] = row["equity"]
            else:
                bucketed.append(
                    {
                        "bucket_key": bucket_key,
                        "timestamp": row["ts"].isoformat(),
                        "equity": row["equity"],
                    }
                )

        return [
            {
                "timestamp": row["timestamp"],
                "equity": row["equity"],
            }
            for row in bucketed
        ]

    # ------------------------------------------------------------------
    # Series helpers
    # ------------------------------------------------------------------

    def _normalize_symbols(self, symbols: List[str]) -> List[str]:
        normalized: List[str] = []
        seen: set[str] = set()
        for raw in symbols:
            symbol = str(raw or "").strip().upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            normalized.append(symbol)
        return normalized

    def _prepare_series(
        self,
        points: List[Dict[str, Any]],
        start_dt: datetime,
        end_dt: datetime,
    ) -> List[Dict[str, Any]]:
        """Normalize chart points and include warmup bars before start."""
        series: List[Dict[str, Any]] = []
        warmup_start = start_dt.date() - timedelta(days=320)
        for point in points:
            ts = self._parse_point_timestamp(point.get("timestamp"))
            if ts is None:
                continue
            date_key = ts.date()
            if date_key < warmup_start or date_key > end_dt.date():
                continue
            try:
                close = float(point.get("close", 0.0))
                high = float(point.get("high", close))
                low = float(point.get("low", close))
                open_price = float(point.get("open", close))
                volume = float(point.get("volume", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if close <= 0:
                continue
            if high < low:
                high, low = low, high
            if open_price <= 0:
                open_price = close
            if not math.isfinite(volume) or volume < 0:
                volume = 0.0
            series.append({
                "date": date_key,
                "timestamp": ts,
                "open": open_price,
                "close": close,
                "high": high,
                "low": low,
                "volume": max(0.0, volume),
                "sma50": point.get("sma50"),
            })
        series.sort(key=lambda item: item["timestamp"])
        return series

    def _parse_point_timestamp(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        text = str(value).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    # ------------------------------------------------------------------
    # Signal / indicator computation
    # ------------------------------------------------------------------

    def _compute_atr_pct(self, series: List[Dict[str, Any]], day: date_type) -> Optional[float]:
        """Compute ATR(14) as a percentage of close for a given day."""
        idx = -1
        for i, point in enumerate(series):
            if point["date"] == day:
                idx = i
                break
        if idx < 14:
            return None
        close = float(series[idx]["close"])
        if close <= 0:
            return None
        tr_values: List[float] = []
        for j in range(max(1, idx - 13), idx + 1):
            high = float(series[j]["high"])
            low = float(series[j]["low"])
            prev_close = float(series[j - 1]["close"])
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_values.append(max(0.0, tr))
        atr_abs = sum(tr_values) / len(tr_values) if tr_values else 0.0
        return (atr_abs / close * 100.0)

    def _compute_signal_metrics(
        self,
        series: List[Dict[str, Any]],
        day: date_type,
        params: Dict[str, float],
    ) -> Optional[Dict[str, Any]]:
        idx = -1
        for i, point in enumerate(series):
            if point["date"] == day:
                idx = i
                break
        # Require enough bars for SMA50 and RSI(14).
        if idx < 50:
            return None

        closes = [float(p["close"]) for p in series[:idx + 1]]
        latest = series[idx]
        latest_close = float(latest["close"])
        latest_sma50 = latest.get("sma50")
        if latest_sma50 is None and idx >= 49:
            latest_sma50 = sum(closes[idx - 49:idx + 1]) / 50.0
        if latest_sma50 is None:
            return None
        latest_sma200 = None
        if idx >= 199:
            latest_sma200 = sum(closes[idx - 199:idx + 1]) / 200.0

        # ATR(14) from true ranges.
        tr_values: List[float] = []
        atr_start = max(1, idx - 13)
        for j in range(atr_start, idx + 1):
            high = float(series[j]["high"])
            low = float(series[j]["low"])
            prev_close = float(series[j - 1]["close"])
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_values.append(max(0.0, tr))
        atr_abs = sum(tr_values) / len(tr_values) if tr_values else 0.0
        atr_pct = (atr_abs / latest_close * 100.0) if latest_close > 0 else 0.0

        # Z-score over 50-period window for statistical stability.
        z_window = 50
        z_slice = closes[max(0, idx - z_window + 1):idx + 1]
        z_mean = sum(z_slice) / len(z_slice)
        variance = sum((v - z_mean) ** 2 for v in z_slice) / len(z_slice)
        z_std = variance ** 0.5
        zscore = (latest_close - z_mean) / z_std if z_std > 0 else 0.0

        # RSI(14), Wilder-style smoothed approximation.
        rsi14 = None
        if idx >= 14:
            gains = 0.0
            losses = 0.0
            for j in range(idx - 13, idx + 1):
                delta = closes[j] - closes[j - 1]
                if delta >= 0:
                    gains += delta
                else:
                    losses += abs(delta)
            avg_gain = gains / 14.0
            avg_loss = losses / 14.0
            if avg_loss <= 1e-12:
                rsi14 = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi14 = 100.0 - (100.0 / (1.0 + rs))

        # Composite entry signal: either condition can trigger, weighted.
        dip_trigger_price = float(latest_sma50) * (1.0 - (params["dip_buy_threshold_pct"] / 100.0))
        dip_condition = latest_close <= dip_trigger_price
        zscore_condition = zscore <= params["zscore_entry_threshold"]
        # Signal fires if either condition is met (relaxed from requiring both).
        dip_buy_signal = dip_condition or zscore_condition
        pullback_sma_tolerance = max(1.0, min(1.05, float(params.get("pullback_sma_tolerance", 1.01))))
        pullback_rsi_threshold = max(10.0, min(70.0, float(params.get("pullback_rsi_threshold", 45.0))))
        pullback_near_sma50 = latest_close <= (float(latest_sma50) * pullback_sma_tolerance)
        rsi_pullback = (rsi14 is not None) and (float(rsi14) < pullback_rsi_threshold)
        investing_trend_ok = (
            latest_sma200 is not None
            and latest_close > float(latest_sma200)
        )
        investing_entry_signal = investing_trend_ok and (pullback_near_sma50 or rsi_pullback)

        regime = self._detect_regime(closes)
        return {
            "atr14_pct": atr_pct,
            "zscore": zscore,
            "rsi14": rsi14,
            "sma50": latest_sma50,
            "sma200": latest_sma200,
            "dip_buy_signal": dip_buy_signal,
            "investing_trend_ok": investing_trend_ok,
            "investing_entry_signal": investing_entry_signal,
            "pullback_sma_tolerance": pullback_sma_tolerance,
            "pullback_rsi_threshold": pullback_rsi_threshold,
            "regime": regime,
        }

    def _detect_regime(self, closes: List[float]) -> str:
        """Multi-timeframe regime detection.

        Checks both 20-day and 60-day windows. If they disagree, returns
        a cautious regime to avoid entering during transitions.
        """
        regime_60 = self._detect_regime_window(closes, 60)
        regime_20 = self._detect_regime_window(closes, 20)

        if regime_60 == regime_20:
            return regime_60
        # Regime disagreement signals transition — be cautious.
        if "trending_down" in (regime_60, regime_20):
            return "trending_down"
        if "high_volatility_range" in (regime_60, regime_20):
            return "high_volatility_range"
        return regime_60

    def _detect_regime_window(self, closes: List[float], window: int) -> str:
        """Detect regime for a given lookback window."""
        data = closes[-window:] if len(closes) >= window else closes
        if len(data) < 15:
            return "unknown"
        start = data[0]
        end = data[-1]
        trend = ((end - start) / start) if start > 0 else 0.0
        returns: List[float] = []
        for i in range(1, len(data)):
            prev = data[i - 1]
            if prev <= 0:
                continue
            returns.append((data[i] - prev) / prev)
        # Daily volatility (sample stdev of daily returns).
        if len(returns) >= 2:
            mean_r = sum(returns) / len(returns)
            vol = (sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5
        else:
            vol = 0.0
        # Tighter threshold (0.015 daily ~ 23.8% annualized) for better separation.
        if trend > 0.04 and vol < 0.015:
            return "trending_up"
        if trend < -0.04 and vol < 0.015:
            return "trending_down"
        if vol >= 0.015:
            return "high_volatility_range"
        return "range_bound"

    def _resolve_execution_seed(
        self,
        *,
        request: BacktestRequest,
        symbols: List[str],
        params: Dict[str, float],
    ) -> int:
        """Resolve deterministic seed for execution-model randomness."""
        explicit_seed = getattr(request, "execution_seed", None)
        if explicit_seed is not None:
            try:
                parsed = int(explicit_seed)
                if parsed >= 0:
                    return parsed
            except (TypeError, ValueError):
                pass
        digest_parts = [
            str(request.strategy_id),
            str(request.start_date),
            str(request.end_date),
            f"{float(request.initial_capital):.6f}",
            ",".join(sorted(str(sym).upper() for sym in symbols)),
            "|".join(f"{key}:{float(params[key]):.6f}" for key in sorted(params.keys())),
            str(bool(request.emulate_live_trading)),
        ]
        digest = hashlib.sha256("::".join(digest_parts).encode("utf-8")).hexdigest()
        return int(digest[:16], 16)

    def _intrabar_reference_price(
        self,
        *,
        side: str,
        open_price: float,
        high: float,
        low: float,
        close: float,
        latency_ms: float,
        emulate_live: bool,
    ) -> float:
        """
        Approximate arrival price inside bar based on latency and side.

        Uses a simple directional path approximation for OHLC bars:
        - green bar: open -> low -> high -> close
        - red/flat bar: open -> high -> low -> close
        """
        if close <= 0:
            return max(0.01, close)
        if not emulate_live:
            return close
        session_ms = 6.5 * 60.0 * 60.0 * 1000.0
        progress = max(0.0, min(1.0, float(latency_ms) / max(1.0, session_ms)))
        if close >= open_price:
            path = [open_price, low, high, close]
        else:
            path = [open_price, high, low, close]
        segments = max(1, len(path) - 1)
        scaled = progress * segments
        idx = min(segments - 1, int(math.floor(scaled)))
        frac = scaled - float(idx)
        start_price = float(path[idx])
        end_price = float(path[idx + 1])
        reference = start_price + ((end_price - start_price) * frac)
        return max(0.01, min(high, max(low, reference)))

    def _simulate_execution_fill(
        self,
        *,
        side: str,
        order_style: str,
        open_price: float,
        high: float,
        low: float,
        close: float,
        daily_volume: float,
        requested_notional: Optional[float],
        requested_qty: Optional[float],
        fee_bps: float,
        base_slippage_bps: float,
        emulate_live: bool,
        latency_ms: float,
        queue_position_bps: float,
        max_participation_rate: float,
        simulate_queue_position: bool,
        enforce_liquidity_limits: bool,
        allow_partial: bool,
        rng: Optional[_random_mod.Random],
        reconcile_fees_with_broker: bool,
        reference_price_override: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Simulate fill price/size with latency, queue, spread, and liquidity caps."""
        safe_close = max(0.01, float(close))
        safe_high = max(safe_close, float(high))
        safe_low = min(safe_close, float(low))
        safe_open = max(0.01, float(open_price) if open_price > 0 else safe_close)
        reference_price = (
            max(0.01, float(reference_price_override))
            if reference_price_override is not None
            else self._intrabar_reference_price(
                side=side,
                open_price=safe_open,
                high=safe_high,
                low=safe_low,
                close=safe_close,
                latency_ms=latency_ms,
                emulate_live=emulate_live,
            )
        )
        requested_quantity = float(requested_qty) if requested_qty is not None else 0.0
        if requested_quantity <= 0 and requested_notional is not None and reference_price > 0:
            requested_quantity = float(requested_notional) / reference_price
        requested_quantity = max(0.0, requested_quantity)
        filled_quantity = requested_quantity
        liquidity_limited = False
        effective_latency_ms = float(latency_ms if emulate_live else 0.0)

        max_rate = max(0.001, min(0.5, float(max_participation_rate)))
        traded_volume = max(0.0, float(daily_volume))
        participation_capacity = traded_volume * max_rate
        overflow_participation = 0.0
        if (
            emulate_live
            and enforce_liquidity_limits
            and traded_volume > 0
            and requested_quantity > participation_capacity
        ):
            liquidity_limited = True
            if allow_partial:
                filled_quantity = max(0.0, participation_capacity)
            else:
                filled_quantity = requested_quantity
                overflow_participation = max(
                    0.0,
                    (requested_quantity - participation_capacity) / max(1.0, traded_volume),
                )
        participation_rate = (
            min(1.0, filled_quantity / traded_volume)
            if traded_volume > 0 and filled_quantity > 0
            else 0.0
        )

        bar_range_bps = max(0.0, ((safe_high - safe_low) / safe_close) * 10000.0)
        spread_bps = max(0.6, min(120.0, (bar_range_bps * 0.08) + 0.4))
        impact_bps = max(
            float(base_slippage_bps),
            min(220.0, (bar_range_bps * 0.22) + (math.sqrt(max(0.0, participation_rate)) * 85.0)),
        ) if emulate_live else max(0.0, float(base_slippage_bps))
        style_penalty_bps = 0.0
        style = str(order_style).strip().lower()
        if emulate_live and style == "stop_exit":
            style_penalty_bps = min(220.0, bar_range_bps * 0.30)
        elif emulate_live and style == "take_profit_exit":
            style_penalty_bps = min(80.0, bar_range_bps * 0.08)
        if emulate_live and overflow_participation > 0:
            style_penalty_bps += min(260.0, math.sqrt(overflow_participation) * 120.0)

        queue_penalty_bps = 0.0
        if emulate_live and simulate_queue_position:
            latency_ratio = min(1.0, effective_latency_ms / (6.5 * 60.0 * 60.0 * 1000.0))
            queue_scale = 0.5 + (2.5 * latency_ratio) + min(1.5, participation_rate * 100.0)
            queue_penalty_bps = max(0.0, float(queue_position_bps)) * queue_scale

        stochastic_bps = 0.0
        if emulate_live and rng is not None:
            stochastic_bps = rng.gauss(0.0, max(0.2, spread_bps * 0.15))

        total_adverse_bps = max(
            0.0,
            (spread_bps * 0.5) + impact_bps + style_penalty_bps + queue_penalty_bps + max(0.0, stochastic_bps),
        )
        if not emulate_live:
            total_adverse_bps = max(0.0, float(base_slippage_bps))

        if filled_quantity <= 0:
            return {
                "requested_qty": requested_quantity,
                "filled_qty": 0.0,
                "fill_price": reference_price,
                "fill_notional": 0.0,
                "fees": 0.0,
                "effective_slippage_bps": 0.0,
                "spread_bps": spread_bps,
                "impact_bps": impact_bps,
                "queue_penalty_bps": queue_penalty_bps,
                "latency_ms": effective_latency_ms,
                "participation_rate": participation_rate,
                "liquidity_limited": liquidity_limited,
                "order_style": style,
            }

        side_key = side.strip().lower()
        if side_key == "sell":
            fill_price = reference_price * (1.0 - (total_adverse_bps / 10000.0))
        else:
            fill_price = reference_price * (1.0 + (total_adverse_bps / 10000.0))
        fill_price = max(0.01, fill_price)
        fill_notional = filled_quantity * fill_price
        fees = self._estimate_trade_fees(
            side=side_key,
            notional=fill_notional,
            quantity=filled_quantity,
            fee_bps=fee_bps,
            emulate_live=emulate_live,
            reconcile_fees_with_broker=reconcile_fees_with_broker,
        )
        return {
            "requested_qty": requested_quantity,
            "filled_qty": filled_quantity,
            "fill_price": fill_price,
            "fill_notional": fill_notional,
            "fees": fees,
            "effective_slippage_bps": total_adverse_bps,
            "spread_bps": spread_bps,
            "impact_bps": impact_bps + style_penalty_bps,
            "queue_penalty_bps": queue_penalty_bps,
            "latency_ms": effective_latency_ms,
            "participation_rate": participation_rate,
            "liquidity_limited": liquidity_limited,
            "order_style": style,
        }

    def _record_execution_fill(
        self,
        *,
        diagnostics: Dict[str, Any],
        fill: Dict[str, Any],
        side: str,
    ) -> None:
        """Accumulate execution-model diagnostics from one fill."""
        summary = diagnostics.get("execution_summary")
        if not isinstance(summary, dict):
            return
        summary["fills"] = int(summary.get("fills", 0)) + 1
        if side == "entry":
            summary["entry_fills"] = int(summary.get("entry_fills", 0)) + 1
        else:
            summary["exit_fills"] = int(summary.get("exit_fills", 0)) + 1
        if bool(fill.get("liquidity_limited")):
            summary["liquidity_capped_fills"] = int(summary.get("liquidity_capped_fills", 0)) + 1
        summary["effective_slippage_bps_sum"] = float(summary.get("effective_slippage_bps_sum", 0.0)) + float(fill.get("effective_slippage_bps", 0.0) or 0.0)
        summary["effective_latency_ms_sum"] = float(summary.get("effective_latency_ms_sum", 0.0)) + float(fill.get("latency_ms", 0.0) or 0.0)
        summary["queue_penalty_bps_sum"] = float(summary.get("queue_penalty_bps_sum", 0.0)) + float(fill.get("queue_penalty_bps", 0.0) or 0.0)
        summary["impact_bps_sum"] = float(summary.get("impact_bps_sum", 0.0)) + float(fill.get("impact_bps", 0.0) or 0.0)
        summary["spread_bps_sum"] = float(summary.get("spread_bps_sum", 0.0)) + float(fill.get("spread_bps", 0.0) or 0.0)
        summary["filled_notional_total"] = float(summary.get("filled_notional_total", 0.0)) + float(fill.get("fill_notional", 0.0) or 0.0)
        if side == "entry":
            summary["entry_notional_total"] = float(summary.get("entry_notional_total", 0.0)) + float(fill.get("fill_notional", 0.0) or 0.0)
        summary["fees_total"] = float(summary.get("fees_total", 0.0)) + float(fill.get("fees", 0.0) or 0.0)
        summary["participation_rate_sum"] = float(summary.get("participation_rate_sum", 0.0)) + float(fill.get("participation_rate", 0.0) or 0.0)

    def _effective_slippage_bps(
        self,
        base_bps: float,
        close: float,
        high: float,
        low: float,
        emulate_live: bool,
    ) -> float:
        """
        Compute per-fill slippage in bps.

        In live-emulation mode, widen slippage using half of the bar range to
        better approximate execution uncertainty on historical bars.
        """
        base = max(0.0, float(base_bps))
        if not emulate_live or close <= 0:
            return base
        bar_range_bps = max(0.0, ((high - low) / close) * 10000.0)
        modeled = max(base, min(200.0, bar_range_bps * 0.5))
        return modeled

    def _estimate_trade_fees(
        self,
        side: str,
        notional: float,
        quantity: float,
        fee_bps: float,
        emulate_live: bool,
        reconcile_fees_with_broker: bool = True,
    ) -> float:
        """
        Estimate execution costs.

        - Optional generic fee bps on notional.
        - In live emulation mode, apply sell-side SEC/TAF style regulatory fees.
        - When reconcile_fees_with_broker is enabled, apply broker-style cent rounding.
        """
        gross = max(0.0, float(notional))
        qty = max(0.0, float(quantity))
        total_fees = gross * (max(0.0, float(fee_bps)) / 10000.0)
        if emulate_live and side.lower() == "sell" and gross > 0 and qty > 0:
            # SEC fee approximation (sell-side only): ~$8 per $1M notional.
            sec_fee = gross * 0.000008
            # FINRA TAF approximation (sell-side only): $0.000166/share, capped.
            taf_fee = min(8.30, max(0.01, qty * 0.000166))
            if reconcile_fees_with_broker:
                sec_fee = round(sec_fee + 1e-12, 2)
                taf_fee = round(taf_fee + 1e-12, 2)
            total_fees += sec_fee + taf_fee
        if reconcile_fees_with_broker:
            total_fees = round(total_fees + 1e-12, 4)
        return max(0.0, total_fees)

    # ------------------------------------------------------------------
    # Core statistical calculations
    # ------------------------------------------------------------------

    def _equity_returns(self, equity_curve: List[Dict[str, Any]]) -> List[float]:
        returns: List[float] = []
        if len(equity_curve) < 2:
            return returns
        for i in range(1, len(equity_curve)):
            prev = float(equity_curve[i - 1].get("equity", 0.0))
            curr = float(equity_curve[i].get("equity", 0.0))
            if prev > 0:
                returns.append((curr - prev) / prev)
        return returns

    def _calculate_annualized_volatility(self, returns: List[float]) -> float:
        """Calculate annualized volatility (daily stdev * sqrt(252))."""
        if len(returns) < 2:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        daily_vol = variance ** 0.5
        return round(daily_vol * (252 ** 0.5), 6)

    def _calculate_drawdown_from_trades(self, trades: List[Any]) -> float:
        """Calculate maximum drawdown from trades using cumulative P&L."""
        if not trades:
            return 0.0
        # Build cumulative P&L series and measure drawdown from peak.
        cumulative = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for trade in trades:
            cumulative += trade.realized_pnl or 0.0
            peak = max(peak, cumulative)
            if peak > 0:
                dd = ((peak - cumulative) / peak * 100)
                max_drawdown = max(max_drawdown, dd)
        return round(max_drawdown, 2)

    def _calculate_sharpe_ratio(self, returns: List[float], risk_free_rate: float = 0.02) -> float:
        """Calculate annualized Sharpe ratio using sample variance (Bessel-corrected)."""
        n = len(returns)
        if n < 2:
            return 0.0
        mean_return = sum(returns) / n
        variance = sum((r - mean_return) ** 2 for r in returns) / (n - 1)
        daily_vol = variance ** 0.5
        if daily_vol == 0:
            return 0.0
        annualized_return = mean_return * 252
        annualized_vol = daily_vol * (252 ** 0.5)
        return round((annualized_return - risk_free_rate) / annualized_vol, 4)

    def _calculate_sortino_ratio(self, returns: List[float], risk_free_rate: float = 0.02) -> float:
        """Calculate annualized Sortino ratio (penalizes only downside vol).

        Standard Sortino denominator divides sum-of-squared-downside-deviations
        by the *total* observation count, not just the count of negative returns.
        """
        n = len(returns)
        if n < 2:
            return 0.0
        mean_return = sum(returns) / n
        downside_sq_sum = sum(r * r for r in returns if r < 0)
        if downside_sq_sum == 0:
            return 0.0
        downside_vol = (downside_sq_sum / n) ** 0.5
        if downside_vol == 0:
            return 0.0
        annualized_return = mean_return * 252
        annualized_downside = downside_vol * (252 ** 0.5)
        return round((annualized_return - risk_free_rate) / annualized_downside, 4)

    def _calculate_profit_factor(self, trades: List[Dict[str, Any]]) -> float:
        """Profit factor = gross profits / gross losses. Target: > 1.5."""
        gross_profits = sum(t["pnl"] for t in trades if t["pnl"] > 0)
        gross_losses = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
        if gross_losses == 0:
            return gross_profits if gross_profits > 0 else 0.0
        return gross_profits / gross_losses

    def _calculate_expectancy(self, trades: List[Dict[str, Any]]) -> float:
        """Per-trade expected profit: avg_win * win_rate - avg_loss * loss_rate."""
        if not trades:
            return 0.0
        winners = [t["pnl"] for t in trades if t["pnl"] > 0]
        losers = [t["pnl"] for t in trades if t["pnl"] < 0]
        total = len(trades)
        win_rate = len(winners) / total if total > 0 else 0.0
        loss_rate = len(losers) / total if total > 0 else 0.0
        avg_win = sum(winners) / len(winners) if winners else 0.0
        avg_loss = sum(losers) / len(losers) if losers else 0.0
        return avg_win * win_rate + avg_loss * loss_rate

    def _calculate_avg_win_loss(self, trades: List[Dict[str, Any]]) -> tuple[float, float]:
        """Return (average_win, average_loss) dollar amounts."""
        winners = [t["pnl"] for t in trades if t["pnl"] > 0]
        losers = [t["pnl"] for t in trades if t["pnl"] < 0]
        avg_win = sum(winners) / len(winners) if winners else 0.0
        avg_loss = sum(losers) / len(losers) if losers else 0.0
        return avg_win, avg_loss

    def _calculate_max_consecutive_losses(self, trades: List[Dict[str, Any]]) -> int:
        """Maximum consecutive losing trades."""
        max_streak = 0
        current_streak = 0
        for t in trades:
            if t["pnl"] < 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        return max_streak

    def _calculate_recovery_factor(self, total_return: float, max_drawdown: float) -> float:
        """Recovery factor = total_return / max_drawdown."""
        if max_drawdown == 0:
            return total_return if total_return > 0 else 0.0
        return total_return / max_drawdown

    def _calculate_calmar_ratio(self, returns: List[float], max_drawdown: float) -> float:
        """Calmar ratio = annualized_return / max_drawdown."""
        if len(returns) < 2 or max_drawdown == 0:
            return 0.0
        mean_return = sum(returns) / len(returns)
        annualized = mean_return * 252 * 100  # convert to percent
        return annualized / max_drawdown

    def _calculate_avg_hold_days(self, trades: List[Dict[str, Any]]) -> float:
        """Average holding period in calendar days."""
        hold_days = [t.get("days_held", 0) for t in trades if t.get("days_held") is not None]
        if not hold_days:
            return 0.0
        return sum(hold_days) / len(hold_days)

    def _calculate_max_drawdown_from_equity(self, equity_curve: List[Dict[str, Any]]) -> float:
        """Calculate maximum drawdown from equity curve."""
        if len(equity_curve) < 2:
            return 0.0
        peak_equity = equity_curve[0]['equity']
        max_drawdown = 0.0
        for point in equity_curve:
            equity = point['equity']
            peak_equity = max(peak_equity, equity)
            drawdown = ((peak_equity - equity) / peak_equity * 100) if peak_equity > 0 else 0.0
            max_drawdown = max(max_drawdown, drawdown)
        return round(max_drawdown, 2)
