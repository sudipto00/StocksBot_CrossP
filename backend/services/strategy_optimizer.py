"""
Strategy optimization service.

Runs bounded parameter + symbol-universe search by repeatedly invoking the
existing backtest engine, then returns the best configuration for a selected
objective with optional out-of-sample walk-forward validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import math
import random
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from config.strategy_config import BacktestRequest, BacktestResult, get_default_parameters
from services.strategy_analytics import StrategyAnalyticsService


@dataclass
class OptimizationContext:
    """Immutable context shared by all optimization candidate runs."""

    strategy_id: str
    start_date: str
    end_date: str
    initial_capital: float
    contribution_amount: float
    contribution_frequency: str
    emulate_live_trading: bool
    require_fractionable: bool
    max_position_size: float
    risk_limit_daily: float
    fee_bps: float
    universe_context: Dict[str, Any]
    symbol_capabilities: Dict[str, Dict[str, bool]]


@dataclass
class OptimizationOutcome:
    """Single candidate run outcome."""

    score: float
    meets_min_trades: bool
    parameters: Dict[str, float]
    symbols: List[str]
    result: BacktestResult


class OptimizationCancelledError(RuntimeError):
    """Raised when optimization is canceled by the caller."""


class StrategyOptimizerService:
    """Parameter/symbol optimizer over the existing deterministic backtester."""

    # Keep this list intentionally focused; widening it rapidly increases runtime.
    _TUNABLE_PARAMETER_NAMES = [
        "position_size",
        "risk_per_trade",
        "stop_loss_pct",
        "take_profit_pct",
        "trailing_stop_pct",
        "atr_stop_mult",
        "zscore_entry_threshold",
        "dip_buy_threshold_pct",
        "max_hold_days",
        "dca_tranches",
        "max_consecutive_losses",
        "max_drawdown_pct",
    ]
    _INTEGER_PARAMETERS = {
        "max_hold_days",
        "dca_tranches",
        "max_consecutive_losses",
        "max_drawdown_pct",
    }
    _VALID_OBJECTIVES = {"balanced", "sharpe", "return"}

    def __init__(self, analytics: StrategyAnalyticsService):
        self.analytics = analytics
        defs = get_default_parameters()
        self._bounds: Dict[str, Tuple[float, float, float]] = {
            item.name: (float(item.min_value), float(item.max_value), float(item.step))
            for item in defs
        }

    def optimize(
        self,
        *,
        context: OptimizationContext,
        base_symbols: Sequence[str],
        base_parameters: Dict[str, float],
        iterations: int,
        min_trades: int,
        objective: str = "balanced",
        strict_min_trades: bool = False,
        walk_forward_enabled: bool = True,
        walk_forward_folds: int = 3,
        random_seed: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        symbols = self._normalize_symbols(base_symbols)
        if not symbols:
            raise ValueError("Optimizer requires at least one candidate symbol")
        if iterations < 1:
            raise ValueError("iterations must be >= 1")

        base_params = self._normalize_parameters(base_parameters)
        objective_key = self._normalize_objective(objective)
        rng = random.Random(random_seed)
        candidates = self._build_parameter_candidates(
            base=base_params,
            iterations=iterations,
            rng=rng,
        )
        trim_steps = max(0, len(self._candidate_symbol_counts(total=len(symbols))) - 1)
        walk_forward_steps = int(walk_forward_folds) if walk_forward_enabled else 0
        total_steps = max(1, len(candidates) + trim_steps + max(0, walk_forward_steps))
        completed_steps = 0

        def _emit(stage: str) -> None:
            if progress_callback is None:
                return
            progress_callback(completed_steps, total_steps, stage)

        _emit("initializing")
        outcomes: List[OptimizationOutcome] = []
        for params in candidates:
            if should_cancel and should_cancel():
                raise OptimizationCancelledError("Optimization canceled")
            result = self._run_backtest(
                context=context,
                symbols=symbols,
                parameters=params,
            )
            score, meets_min_trades = self._objective_score(
                result=result,
                min_trades=min_trades,
                objective=objective_key,
                strict_min_trades=strict_min_trades,
            )
            outcomes.append(
                OptimizationOutcome(
                    score=score,
                    meets_min_trades=meets_min_trades,
                    parameters=params,
                    symbols=list(symbols),
                    result=result,
                )
            )
            completed_steps += 1
            _emit("parameter_search")

        if not outcomes:
            raise RuntimeError("Optimizer did not produce any candidate outcome")

        outcomes.sort(key=lambda item: item.score, reverse=True)
        best = outcomes[0]

        ranked_symbols = self._rank_symbols_by_best_result(symbols=symbols, result=best.result)
        symbol_counts = self._candidate_symbol_counts(total=len(ranked_symbols))
        for count in symbol_counts:
            if count >= len(ranked_symbols):
                continue
            if should_cancel and should_cancel():
                raise OptimizationCancelledError("Optimization canceled")
            subset = ranked_symbols[:count]
            subset_result = self._run_backtest(
                context=context,
                symbols=subset,
                parameters=best.parameters,
            )
            subset_score, subset_meets = self._objective_score(
                result=subset_result,
                min_trades=min_trades,
                objective=objective_key,
                strict_min_trades=strict_min_trades,
            )
            if subset_score > best.score:
                best = OptimizationOutcome(
                    score=subset_score,
                    meets_min_trades=subset_meets,
                    parameters=dict(best.parameters),
                    symbols=list(subset),
                    result=subset_result,
                )
            completed_steps += 1
            _emit("symbol_trim")

        walk_forward_report: Optional[Dict[str, Any]] = None
        if walk_forward_enabled:
            walk_forward_report = self._compute_walk_forward_report(
                context=context,
                symbols=best.symbols,
                parameters=best.parameters,
                objective=objective_key,
                min_trades=min_trades,
                strict_min_trades=strict_min_trades,
                folds=walk_forward_folds,
                should_cancel=should_cancel,
            )
            completed_steps += int(walk_forward_report.get("folds_completed", 0))
            _emit("walk_forward")
        completed_steps = total_steps
        _emit("finalizing")

        top_candidates = outcomes[:5]
        payload_candidates: List[Dict[str, Any]] = []
        for index, item in enumerate(top_candidates, start=1):
            payload_candidates.append(
                {
                    "rank": index,
                    "score": round(item.score, 6),
                    "meets_min_trades": bool(item.meets_min_trades),
                    "symbol_count": len(item.symbols),
                    "sharpe_ratio": round(float(item.result.sharpe_ratio), 6),
                    "total_return": round(float(item.result.total_return), 6),
                    "max_drawdown": round(float(item.result.max_drawdown), 6),
                    "win_rate": round(float(item.result.win_rate), 6),
                    "total_trades": int(item.result.total_trades),
                    "parameters": {key: float(value) for key, value in item.parameters.items()},
                }
            )

        return {
            "requested_iterations": int(iterations),
            "evaluated_iterations": int(len(outcomes)),
            "objective": self._objective_label(objective_key),
            "recommended_parameters": {key: float(value) for key, value in best.parameters.items()},
            "recommended_symbols": list(best.symbols),
            "top_candidates": payload_candidates,
            "best_result": best.result,
            "score": round(best.score, 6),
            "min_trades_target": int(min_trades),
            "strict_min_trades": bool(strict_min_trades),
            "best_candidate_meets_min_trades": bool(best.meets_min_trades),
            "walk_forward": walk_forward_report,
            "notes": [
                (
                    f"Optimization objective: {self._objective_label(objective_key)} "
                    "with drawdown/risk penalties."
                ),
                (
                    f"Minimum trades target: {int(min_trades)} "
                    f"({'strict gate' if strict_min_trades else 'soft penalty'})."
                ),
                "Final symbol set may be trimmed from the candidate universe when trim variants improve objective score.",
                (
                    "No candidate met strict min-trades target; best available candidate was returned."
                    if strict_min_trades and not any(item.meets_min_trades for item in outcomes)
                    else (
                        "Selected candidate met trade-count target."
                        if best.meets_min_trades
                        else "Selected candidate is below trade-count target (soft-penalty mode)."
                    )
                ),
                "Apply recommended parameters/symbols to strategy config before running live or paper sessions.",
            ],
        }

    def _run_backtest(
        self,
        *,
        context: OptimizationContext,
        symbols: List[str],
        parameters: Dict[str, float],
    ) -> BacktestResult:
        ctx = dict(context.universe_context or {})
        ctx["optimizer"] = {
            "enabled": True,
            "symbols_candidate_count": len(symbols),
        }
        capabilities = {
            symbol: dict(context.symbol_capabilities.get(symbol, {"tradable": True, "fractionable": True}))
            for symbol in symbols
        }
        request = BacktestRequest(
            strategy_id=context.strategy_id,
            start_date=context.start_date,
            end_date=context.end_date,
            initial_capital=context.initial_capital,
            contribution_amount=context.contribution_amount,
            contribution_frequency=context.contribution_frequency,
            symbols=symbols,
            parameters=parameters,
            emulate_live_trading=context.emulate_live_trading,
            symbol_capabilities=capabilities or None,
            require_fractionable=context.require_fractionable,
            max_position_size=context.max_position_size,
            risk_limit_daily=context.risk_limit_daily,
            fee_bps=context.fee_bps,
            universe_context=ctx,
        )
        return self.analytics.run_backtest(request)

    def _candidate_symbol_counts(self, total: int) -> List[int]:
        if total <= 8:
            return [total]
        # Evaluate progressively tighter universes from best-symbol ranking.
        candidates = {
            total,
            max(8, int(total * 0.85)),
            max(8, int(total * 0.70)),
            max(8, int(total * 0.55)),
            max(8, int(total * 0.40)),
        }
        return sorted(candidates, reverse=True)

    def _rank_symbols_by_best_result(self, *, symbols: Sequence[str], result: BacktestResult) -> List[str]:
        stats: Dict[str, Dict[str, float]] = {}
        for trade in result.trades:
            symbol = str(trade.get("symbol", "")).strip().upper()
            if not symbol:
                continue
            row = stats.setdefault(symbol, {"pnl": 0.0, "trades": 0.0, "wins": 0.0})
            pnl = float(trade.get("pnl", 0.0) or 0.0)
            row["pnl"] += pnl
            row["trades"] += 1.0
            if pnl > 0:
                row["wins"] += 1.0

        def _symbol_score(symbol: str) -> Tuple[float, float, float]:
            row = stats.get(symbol)
            if not row:
                # Keep untouched symbols near the back but preserve deterministic ordering.
                return (-1e12, 0.0, 0.0)
            trades = row["trades"]
            win_rate = (row["wins"] / trades * 100.0) if trades > 0 else 0.0
            return (row["pnl"], win_rate, trades)

        ordered = list(symbols)
        ordered.sort(key=_symbol_score, reverse=True)
        return ordered

    def _build_parameter_candidates(
        self,
        *,
        base: Dict[str, float],
        iterations: int,
        rng: random.Random,
    ) -> List[Dict[str, float]]:
        candidates: List[Dict[str, float]] = [dict(base)]
        while len(candidates) < iterations:
            candidates.append(self._mutate_parameters(base=base, rng=rng))
        return candidates

    def _mutate_parameters(self, *, base: Dict[str, float], rng: random.Random) -> Dict[str, float]:
        candidate = dict(base)
        for name in self._TUNABLE_PARAMETER_NAMES:
            bounds = self._bounds.get(name)
            if bounds is None:
                continue
            low, high, step = bounds
            base_value = float(candidate.get(name, (low + high) / 2.0))
            span = high - low
            if span <= 0:
                continue
            # Biased local search: mostly near base with occasional broad jumps.
            if rng.random() < 0.2:
                raw = rng.uniform(low, high)
            else:
                raw = base_value + rng.gauss(0.0, span * 0.12)
            raw = max(low, min(high, raw))
            snapped = self._snap(raw, step)
            if name in self._INTEGER_PARAMETERS:
                snapped = float(int(round(snapped)))
            candidate[name] = max(low, min(high, snapped))

        # Maintain defensible relationship between key risk parameters.
        stop_loss = float(candidate.get("stop_loss_pct", base.get("stop_loss_pct", 2.0)))
        min_take_profit = stop_loss * 1.8
        take_profit_bounds = self._bounds.get("take_profit_pct", (1.0, 20.0, 0.5))
        candidate["take_profit_pct"] = max(
            min_take_profit,
            float(candidate.get("take_profit_pct", base.get("take_profit_pct", 5.0))),
        )
        candidate["take_profit_pct"] = min(float(take_profit_bounds[1]), candidate["take_profit_pct"])
        candidate["take_profit_pct"] = self._snap(candidate["take_profit_pct"], take_profit_bounds[2])

        trailing_bounds = self._bounds.get("trailing_stop_pct", (0.5, 15.0, 0.25))
        candidate["trailing_stop_pct"] = max(
            float(candidate.get("trailing_stop_pct", base.get("trailing_stop_pct", 2.5))),
            stop_loss * 0.9,
        )
        candidate["trailing_stop_pct"] = min(float(trailing_bounds[1]), candidate["trailing_stop_pct"])
        candidate["trailing_stop_pct"] = self._snap(candidate["trailing_stop_pct"], trailing_bounds[2])

        return self._normalize_parameters(candidate)

    def _normalize_parameters(self, parameters: Dict[str, float]) -> Dict[str, float]:
        normalized = dict(parameters)
        for name, (low, high, step) in self._bounds.items():
            if name not in normalized:
                continue
            raw = normalized[name]
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value):
                continue
            value = max(low, min(high, value))
            value = self._snap(value, step)
            if name in self._INTEGER_PARAMETERS:
                value = float(int(round(value)))
            normalized[name] = value
        return normalized

    def _objective_score(
        self,
        *,
        result: BacktestResult,
        min_trades: int,
        objective: str,
        strict_min_trades: bool,
    ) -> Tuple[float, bool]:
        sharpe = float(result.sharpe_ratio or 0.0)
        total_return = float(result.total_return or 0.0)
        drawdown = abs(float(result.max_drawdown or 0.0))
        win_rate = float(result.win_rate or 0.0)
        trades = int(result.total_trades or 0)
        meets_min_trades = trades >= max(0, int(min_trades))
        trade_penalty = float(max(0, min_trades - trades)) * 0.35
        blocker_penalty = 0.0
        diagnostics = result.diagnostics if isinstance(result.diagnostics, dict) else {}
        blocked = diagnostics.get("blocked_reasons", {}) if isinstance(diagnostics, dict) else {}
        if isinstance(blocked, dict):
            blocker_penalty += float(blocked.get("risk_circuit_breaker", 0) or 0) * 0.001
            blocker_penalty += float(blocked.get("daily_risk_limit", 0) or 0) * 0.0005
        if objective == "sharpe":
            base_score = (
                (sharpe * 110.0)
                + (total_return * 1.1)
                + (win_rate * 0.12)
                - (drawdown * 1.0)
            )
        elif objective == "return":
            base_score = (
                (total_return * 3.1)
                + (sharpe * 30.0)
                + (win_rate * 0.08)
                - (drawdown * 0.7)
            )
        else:
            base_score = (
                (sharpe * 80.0)
                + (total_return * 1.8)
                + (win_rate * 0.14)
                - (drawdown * 0.9)
            )
        if strict_min_trades and not meets_min_trades:
            shortfall = float(max(1, min_trades - trades))
            gated_score = -1_000_000.0 - (shortfall * 1000.0) - drawdown
            return (gated_score, False)
        return (base_score - trade_penalty - blocker_penalty, meets_min_trades)

    def _compute_walk_forward_report(
        self,
        *,
        context: OptimizationContext,
        symbols: List[str],
        parameters: Dict[str, float],
        objective: str,
        min_trades: int,
        strict_min_trades: bool,
        folds: int,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        safe_folds = max(2, int(folds))
        start_date = self._parse_iso_date(context.start_date)
        end_date = self._parse_iso_date(context.end_date)
        total_days = (end_date - start_date).days + 1
        report: Dict[str, Any] = {
            "enabled": True,
            "objective": self._objective_label(objective),
            "strict_min_trades": bool(strict_min_trades),
            "min_trades_target": int(min_trades),
            "folds_requested": safe_folds,
            "folds_completed": 0,
            "pass_rate_pct": 0.0,
            "average_score": 0.0,
            "average_return": 0.0,
            "average_sharpe": 0.0,
            "worst_fold_return": 0.0,
            "folds": [],
            "notes": [],
        }
        if total_days < 120:
            report["notes"] = [
                "Walk-forward skipped: date range too short for meaningful out-of-sample folds (need at least ~120 days)."
            ]
            return report

        # Use expanding train windows with fixed-size sequential test windows.
        test_span_days = max(30, total_days // (safe_folds + 1))
        fold_rows: List[Dict[str, Any]] = []
        for idx in range(1, safe_folds + 1):
            if should_cancel and should_cancel():
                raise OptimizationCancelledError("Optimization canceled")

            train_start = start_date
            train_end = start_date + timedelta(days=(idx * test_span_days) - 1)
            test_start = train_end + timedelta(days=1)
            test_end = min(end_date, test_start + timedelta(days=test_span_days - 1))

            if train_end <= train_start or test_start > end_date:
                break
            if (test_end - test_start).days + 1 < 20:
                break

            fold_context = OptimizationContext(
                strategy_id=context.strategy_id,
                start_date=test_start.isoformat(),
                end_date=test_end.isoformat(),
                initial_capital=context.initial_capital,
                contribution_amount=context.contribution_amount,
                contribution_frequency=context.contribution_frequency,
                emulate_live_trading=context.emulate_live_trading,
                require_fractionable=context.require_fractionable,
                max_position_size=context.max_position_size,
                risk_limit_daily=context.risk_limit_daily,
                fee_bps=context.fee_bps,
                universe_context=dict(context.universe_context or {}),
                symbol_capabilities=dict(context.symbol_capabilities or {}),
            )
            fold_result = self._run_backtest(
                context=fold_context,
                symbols=symbols,
                parameters=parameters,
            )
            fold_score, fold_meets = self._objective_score(
                result=fold_result,
                min_trades=min_trades,
                objective=objective,
                strict_min_trades=strict_min_trades,
            )
            fold_rows.append(
                {
                    "fold_index": idx,
                    "train_start": train_start.isoformat(),
                    "train_end": train_end.isoformat(),
                    "test_start": test_start.isoformat(),
                    "test_end": test_end.isoformat(),
                    "score": round(float(fold_score), 6),
                    "total_return": round(float(fold_result.total_return or 0.0), 6),
                    "sharpe_ratio": round(float(fold_result.sharpe_ratio or 0.0), 6),
                    "max_drawdown": round(float(fold_result.max_drawdown or 0.0), 6),
                    "win_rate": round(float(fold_result.win_rate or 0.0), 6),
                    "total_trades": int(fold_result.total_trades or 0),
                    "meets_min_trades": bool(fold_meets),
                }
            )

        completed = len(fold_rows)
        report["folds_completed"] = completed
        report["folds"] = fold_rows
        if completed <= 0:
            report["notes"] = [
                "Walk-forward completed with zero folds. Increase date range or reduce fold count."
            ]
            return report

        pass_count = sum(1 for row in fold_rows if bool(row.get("meets_min_trades")))
        report["pass_rate_pct"] = round((pass_count / completed) * 100.0, 2)
        report["average_score"] = round(sum(float(row["score"]) for row in fold_rows) / completed, 6)
        report["average_return"] = round(sum(float(row["total_return"]) for row in fold_rows) / completed, 6)
        report["average_sharpe"] = round(sum(float(row["sharpe_ratio"]) for row in fold_rows) / completed, 6)
        report["worst_fold_return"] = round(min(float(row["total_return"]) for row in fold_rows), 6)
        report["notes"] = [
            "Walk-forward uses expanding train windows with sequential out-of-sample test windows.",
            "Folds are scored with the same objective and trade-count gating as the optimizer run.",
        ]
        return report

    def _normalize_symbols(self, symbols: Sequence[str]) -> List[str]:
        normalized: List[str] = []
        seen: set[str] = set()
        for raw in symbols:
            symbol = str(raw or "").strip().upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            normalized.append(symbol)
        return normalized

    def _normalize_objective(self, objective: str) -> str:
        value = str(objective or "balanced").strip().lower()
        if value not in self._VALID_OBJECTIVES:
            raise ValueError(f"Unsupported optimizer objective '{objective}'")
        return value

    def _objective_label(self, objective: str) -> str:
        if objective == "sharpe":
            return "sharpe_priority"
        if objective == "return":
            return "return_priority"
        return "balanced_risk_adjusted"

    @staticmethod
    def _parse_iso_date(raw: str) -> date:
        text = str(raw or "").strip()
        if "T" in text:
            text = text.split("T", 1)[0]
        return datetime.fromisoformat(text).date()

    @staticmethod
    def _snap(value: float, step: float) -> float:
        if step <= 0:
            return float(value)
        return round(round(value / step) * step, 6)
