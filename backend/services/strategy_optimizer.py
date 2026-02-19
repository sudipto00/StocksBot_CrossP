"""
Strategy optimization service.

Runs bounded parameter + symbol-universe search by repeatedly invoking the
existing backtest engine, then returns the best configuration for a selected
objective with optional out-of-sample walk-forward validation.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import math
import os
import random
import statistics
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from config.strategy_config import BacktestRequest, BacktestResult, get_default_parameters
from services.strategy_analytics import StrategyAnalyticsService, BacktestCancelledError


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
    alpaca_creds: Optional[Dict[str, str]]
    require_real_data: bool
    cancel_token_path: Optional[str] = None


@dataclass
class OptimizationOutcome:
    """Single candidate run outcome."""

    score: float
    meets_min_trades: bool
    parameters: Dict[str, float]
    symbols: List[str]
    result: BacktestResult
    robustness: Optional[Dict[str, float]] = None


class OptimizationCancelledError(RuntimeError):
    """Raised when optimization is canceled by the caller."""


def _objective_score_for_result(
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


def _safe_percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = max(0.0, min(1.0, float(pct) / 100.0)) * (len(ordered) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return float(ordered[lower])
    weight = rank - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * weight)


def _perturb_symbol_subset(symbols: Sequence[str], rng: random.Random) -> List[str]:
    base = [str(s).strip().upper() for s in symbols if str(s).strip()]
    if len(base) <= 8:
        return base
    keep_ratio = rng.uniform(0.7, 1.0)
    keep_count = max(8, min(len(base), int(round(len(base) * keep_ratio))))
    if keep_count >= len(base):
        return list(base)
    sampled = set(rng.sample(base, keep_count))
    return [symbol for symbol in base if symbol in sampled]


def _jitter_window(start_iso: str, end_iso: str, rng: random.Random) -> Tuple[str, str]:
    start = datetime.fromisoformat(start_iso.split("T", 1)[0]).date()
    end = datetime.fromisoformat(end_iso.split("T", 1)[0]).date()
    if end <= start:
        return (start.isoformat(), end.isoformat())
    span_days = max(1, (end - start).days)
    jitter = max(0, min(3, span_days // 120))
    if jitter <= 0:
        return (start.isoformat(), end.isoformat())
    shifted_start = start + timedelta(days=rng.randint(-jitter, jitter))
    shifted_end = end + timedelta(days=rng.randint(-jitter, jitter))
    if shifted_end <= shifted_start:
        shifted_end = shifted_start + timedelta(days=max(30, span_days // 2))
    return (shifted_start.isoformat(), shifted_end.isoformat())


def _robust_score_from_scenarios(
    *,
    scenario_metrics: Sequence[Dict[str, float]],
    min_trades: int,
    objective: str,
    strict_min_trades: bool,
) -> Dict[str, float]:
    if not scenario_metrics:
        return {
            "score": -1_000_000.0,
            "median_sharpe": 0.0,
            "median_return": 0.0,
            "p95_drawdown": 100.0,
            "loss_probability": 1.0,
            "median_trades": 0.0,
            "min_trade_pass_rate": 0.0,
            "meets_min_trades": 0.0,
        }
    sharpe_values = [float(item.get("sharpe_ratio", 0.0) or 0.0) for item in scenario_metrics]
    return_values = [float(item.get("total_return", 0.0) or 0.0) for item in scenario_metrics]
    drawdown_values = [abs(float(item.get("max_drawdown", 0.0) or 0.0)) for item in scenario_metrics]
    trade_values = [max(0.0, float(item.get("total_trades", 0.0) or 0.0)) for item in scenario_metrics]
    median_sharpe = float(statistics.median(sharpe_values))
    median_return = float(statistics.median(return_values))
    p95_drawdown = float(_safe_percentile(drawdown_values, 95.0))
    median_trades = float(statistics.median(trade_values))
    min_trade_hits = sum(1 for trades in trade_values if trades >= max(0, int(min_trades)))
    pass_rate = float(min_trade_hits / max(1, len(trade_values)))
    loss_probability = float(
        sum(1 for ret in return_values if ret < 0.0) / max(1, len(return_values))
    )
    trade_shortfall = max(0.0, float(min_trades) - median_trades)
    if objective == "sharpe":
        score = (
            (median_sharpe * 120.0)
            + (median_return * 0.8)
            - (p95_drawdown * 1.4)
            - (loss_probability * 40.0)
        )
    elif objective == "return":
        score = (
            (median_return * 3.0)
            + (median_sharpe * 35.0)
            - (p95_drawdown * 1.1)
            - (loss_probability * 35.0)
        )
    else:
        score = (
            (median_sharpe * 90.0)
            + (median_return * 1.7)
            - (p95_drawdown * 1.2)
            - (loss_probability * 38.0)
        )
    if strict_min_trades and median_trades < float(min_trades):
        score = -1_000_000.0 - (trade_shortfall * 1000.0) - p95_drawdown
    else:
        score -= trade_shortfall * 0.9
    meets_min = 1.0 if median_trades >= float(min_trades) else 0.0
    return {
        "score": float(score),
        "median_sharpe": median_sharpe,
        "median_return": median_return,
        "p95_drawdown": p95_drawdown,
        "loss_probability": loss_probability,
        "median_trades": median_trades,
        "min_trade_pass_rate": pass_rate,
        "meets_min_trades": meets_min,
    }


def _evaluate_ensemble_candidate_worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    context = payload.get("context") or {}
    parameters = {
        str(key): float(value)
        for key, value in (payload.get("parameters") or {}).items()
    }
    base_symbols = [
        str(symbol).strip().upper()
        for symbol in (payload.get("base_symbols") or [])
        if str(symbol).strip()
    ]
    ensemble_runs = max(1, int(payload.get("ensemble_runs") or 1))
    min_trades = int(payload.get("min_trades") or 0)
    objective = str(payload.get("objective") or "balanced")
    strict_min_trades = bool(payload.get("strict_min_trades"))
    random_seed = int(payload.get("seed") or 0)
    rng = random.Random(random_seed)
    analytics = StrategyAnalyticsService(
        db=None,  # type: ignore[arg-type]
        alpaca_creds=(
            dict(context.get("alpaca_creds"))
            if isinstance(context.get("alpaca_creds"), dict)
            else None
        ),
        require_real_data=bool(context.get("require_real_data", False)),
    )
    symbol_capabilities = context.get("symbol_capabilities")
    capability_map = symbol_capabilities if isinstance(symbol_capabilities, dict) else {}
    base_universe_context = (
        dict(context.get("universe_context"))
        if isinstance(context.get("universe_context"), dict)
        else {}
    )
    base_fee_bps = max(0.0, float(context.get("fee_bps", 0.0) or 0.0))
    cancel_token_path = str(context.get("cancel_token_path") or "").strip() or None

    def _worker_should_cancel() -> bool:
        return bool(cancel_token_path and os.path.exists(cancel_token_path))

    scenario_metrics: List[Dict[str, float]] = []
    for run_index in range(ensemble_runs):
        if _worker_should_cancel():
            raise RuntimeError("Optimization canceled")
        scenario_symbols = _perturb_symbol_subset(base_symbols, rng)
        start_date, end_date = _jitter_window(
            str(context.get("start_date", "")),
            str(context.get("end_date", "")),
            rng,
        )
        scenario_fee_bps = max(0.0, base_fee_bps + rng.uniform(-1.5, 4.0))
        scenario_slippage_bps = max(1.0, min(75.0, 5.0 + rng.uniform(-2.0, 12.0)))
        scenario_universe_context = dict(base_universe_context)
        optimizer_ctx = (
            dict(scenario_universe_context.get("optimizer"))
            if isinstance(scenario_universe_context.get("optimizer"), dict)
            else {}
        )
        optimizer_ctx.update(
            {
                "enabled": True,
                "ensemble_mode": True,
                "ensemble_run_index": run_index + 1,
                "ensemble_runs": ensemble_runs,
                "slippage_bps_override": round(float(scenario_slippage_bps), 6),
                "timing_jitter_enabled": True,
            }
        )
        scenario_universe_context["optimizer"] = optimizer_ctx
        capabilities = {
            symbol: dict(capability_map.get(symbol, {"tradable": True, "fractionable": True}))
            for symbol in scenario_symbols
        }
        request = BacktestRequest(
            strategy_id=str(context.get("strategy_id") or ""),
            start_date=start_date,
            end_date=end_date,
            initial_capital=float(context.get("initial_capital") or 100000.0),
            contribution_amount=float(context.get("contribution_amount") or 0.0),
            contribution_frequency=str(context.get("contribution_frequency") or "none"),
            symbols=scenario_symbols,
            parameters=parameters,
            emulate_live_trading=bool(context.get("emulate_live_trading")),
            symbol_capabilities=capabilities or None,
            require_fractionable=bool(context.get("require_fractionable")),
            max_position_size=float(context.get("max_position_size") or 0.0) or None,
            risk_limit_daily=float(context.get("risk_limit_daily") or 0.0) or None,
            fee_bps=float(scenario_fee_bps),
            universe_context=scenario_universe_context,
        )
        try:
            result = analytics.run_backtest(request, should_cancel=_worker_should_cancel)
        except BacktestCancelledError as exc:
            raise RuntimeError("Optimization canceled") from exc
        scenario_metrics.append(
            {
                "sharpe_ratio": float(result.sharpe_ratio or 0.0),
                "total_return": float(result.total_return or 0.0),
                "max_drawdown": abs(float(result.max_drawdown or 0.0)),
                "total_trades": float(result.total_trades or 0),
                "win_rate": float(result.win_rate or 0.0),
            }
        )
    robust = _robust_score_from_scenarios(
        scenario_metrics=scenario_metrics,
        min_trades=min_trades,
        objective=objective,
        strict_min_trades=strict_min_trades,
    )
    return {
        "score": float(robust["score"]),
        "meets_min_trades": bool(robust["meets_min_trades"] >= 1.0),
        "robustness": robust,
    }


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
        ensemble_mode: bool = False,
        ensemble_runs: int = 8,
        max_workers: Optional[int] = None,
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
        ensemble_enabled = bool(ensemble_mode)
        safe_ensemble_runs = max(1, int(ensemble_runs))
        resolved_max_workers = self._resolve_max_workers(max_workers)
        candidates = self._build_parameter_candidates(
            base=base_params,
            iterations=iterations,
            rng=rng,
        )
        trim_steps = max(0, len(self._candidate_symbol_counts(total=len(symbols))) - 1)
        walk_forward_steps = int(walk_forward_folds) if walk_forward_enabled else 0
        candidate_steps = (
            len(candidates) * safe_ensemble_runs
            if ensemble_enabled
            else len(candidates)
        )
        total_steps = max(1, candidate_steps + trim_steps + max(0, walk_forward_steps))
        completed_steps = 0

        def _emit(stage: str) -> None:
            if progress_callback is None:
                return
            progress_callback(completed_steps, total_steps, stage)

        _emit("initializing")
        outcomes: List[OptimizationOutcome] = []
        if ensemble_enabled:
            base_seed = random_seed if isinstance(random_seed, int) else 0
            worker_context = self._build_ensemble_worker_context(context=context)
            try:
                future_to_payload: Dict[Future, Tuple[int, Dict[str, float]]] = {}
                next_candidate_idx = 0
                last_heartbeat_at = time.monotonic()
                with ProcessPoolExecutor(max_workers=resolved_max_workers) as executor:
                    _emit("ensemble_search")
                    while next_candidate_idx < len(candidates) and len(future_to_payload) < resolved_max_workers:
                        if should_cancel and should_cancel():
                            executor.shutdown(wait=False, cancel_futures=True)
                            raise OptimizationCancelledError("Optimization canceled")
                        now = time.monotonic()
                        if (now - last_heartbeat_at) >= 1.0:
                            _emit("ensemble_search")
                            last_heartbeat_at = now
                        params = candidates[next_candidate_idx]
                        candidate_seed = base_seed + (next_candidate_idx * 1009) + 17
                        payload = {
                            "context": worker_context,
                            "parameters": params,
                            "base_symbols": list(symbols),
                            "ensemble_runs": safe_ensemble_runs,
                            "min_trades": int(min_trades),
                            "objective": objective_key,
                            "strict_min_trades": bool(strict_min_trades),
                            "seed": int(candidate_seed),
                        }
                        future = executor.submit(_evaluate_ensemble_candidate_worker, payload)
                        future_to_payload[future] = (next_candidate_idx, params)
                        next_candidate_idx += 1
                        _emit("ensemble_search")
                    while future_to_payload:
                        if should_cancel and should_cancel():
                            executor.shutdown(wait=False, cancel_futures=True)
                            raise OptimizationCancelledError("Optimization canceled")
                        done, _ = wait(
                            list(future_to_payload.keys()),
                            timeout=0.2,
                            return_when=FIRST_COMPLETED,
                        )
                        if not done:
                            now = time.monotonic()
                            if (now - last_heartbeat_at) >= 1.0:
                                _emit("ensemble_search")
                                last_heartbeat_at = now
                            continue
                        for future in done:
                            _, params = future_to_payload.pop(future)
                            try:
                                payload = future.result()
                            except Exception as exc:
                                if should_cancel and should_cancel():
                                    executor.shutdown(wait=False, cancel_futures=True)
                                    raise OptimizationCancelledError("Optimization canceled") from exc
                                if "canceled" in str(exc).lower() or "cancelled" in str(exc).lower():
                                    executor.shutdown(wait=False, cancel_futures=True)
                                    raise OptimizationCancelledError("Optimization canceled") from exc
                                raise
                            robustness = (
                                dict(payload.get("robustness"))
                                if isinstance(payload.get("robustness"), dict)
                                else None
                            )
                            representative = self._build_summary_backtest_result(
                                context=context,
                                parameters=params,
                                robustness=robustness,
                            )
                            outcomes.append(
                                OptimizationOutcome(
                                    score=float(payload.get("score", -1_000_000.0)),
                                    meets_min_trades=bool(payload.get("meets_min_trades", False)),
                                    parameters=dict(params),
                                    symbols=list(symbols),
                                    result=representative,
                                    robustness=robustness,
                                )
                            )
                            completed_steps += safe_ensemble_runs
                            _emit("ensemble_search")
                            last_heartbeat_at = time.monotonic()
                            if should_cancel and should_cancel():
                                executor.shutdown(wait=False, cancel_futures=True)
                                raise OptimizationCancelledError("Optimization canceled")
                            if next_candidate_idx < len(candidates):
                                next_params = candidates[next_candidate_idx]
                                candidate_seed = base_seed + (next_candidate_idx * 1009) + 17
                                next_payload = {
                                    "context": worker_context,
                                    "parameters": next_params,
                                    "base_symbols": list(symbols),
                                    "ensemble_runs": safe_ensemble_runs,
                                    "min_trades": int(min_trades),
                                    "objective": objective_key,
                                    "strict_min_trades": bool(strict_min_trades),
                                    "seed": int(candidate_seed),
                                }
                                next_future = executor.submit(
                                    _evaluate_ensemble_candidate_worker,
                                    next_payload,
                                )
                                future_to_payload[next_future] = (next_candidate_idx, next_params)
                                next_candidate_idx += 1
            except OptimizationCancelledError:
                raise
            except Exception:
                if should_cancel and should_cancel():
                    raise OptimizationCancelledError("Optimization canceled")
                # Fallback to baseline path if multiprocessing is unavailable in runtime.
                outcomes = []
                completed_steps = 0
                total_steps = max(1, len(candidates) + trim_steps + max(0, walk_forward_steps))
                for params in candidates:
                    if should_cancel and should_cancel():
                        raise OptimizationCancelledError("Optimization canceled")
                    result = self._run_backtest(
                        context=context,
                        symbols=symbols,
                        parameters=params,
                        should_cancel=should_cancel,
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
                ensemble_enabled = False
                safe_ensemble_runs = 1
                resolved_max_workers = 1
        else:
            for params in candidates:
                if should_cancel and should_cancel():
                    raise OptimizationCancelledError("Optimization canceled")
                result = self._run_backtest(
                    context=context,
                    symbols=symbols,
                    parameters=params,
                    should_cancel=should_cancel,
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
        if ensemble_enabled:
            detailed_best = self._run_backtest(
                context=context,
                symbols=symbols,
                parameters=best.parameters,
                should_cancel=should_cancel,
            )
            best = OptimizationOutcome(
                score=best.score,
                meets_min_trades=best.meets_min_trades,
                parameters=dict(best.parameters),
                symbols=list(symbols),
                result=detailed_best,
                robustness=dict(best.robustness) if isinstance(best.robustness, dict) else None,
            )

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
                should_cancel=should_cancel,
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
            "ensemble_mode": bool(ensemble_enabled),
            "ensemble_runs": int(safe_ensemble_runs if ensemble_enabled else 1),
            "max_workers_used": int(resolved_max_workers if ensemble_enabled else 1),
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
                (
                    f"Evaluation mode: {'monte_carlo_ensemble' if ensemble_enabled else 'baseline_single_path'}; "
                    f"ensemble_runs={safe_ensemble_runs if ensemble_enabled else 1}; workers={resolved_max_workers if ensemble_enabled else 1}."
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
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> BacktestResult:
        ctx = dict(context.universe_context or {})
        optimizer_ctx = (
            dict(ctx.get("optimizer"))
            if isinstance(ctx.get("optimizer"), dict)
            else {}
        )
        optimizer_ctx.update(
            {
                "enabled": True,
                "symbols_candidate_count": len(symbols),
            }
        )
        ctx["optimizer"] = optimizer_ctx
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
        try:
            return self.analytics.run_backtest(request, should_cancel=should_cancel)
        except BacktestCancelledError as exc:
            raise OptimizationCancelledError("Optimization canceled") from exc

    def _build_ensemble_worker_context(self, *, context: OptimizationContext) -> Dict[str, Any]:
        return {
            "strategy_id": str(context.strategy_id),
            "start_date": str(context.start_date),
            "end_date": str(context.end_date),
            "initial_capital": float(context.initial_capital),
            "contribution_amount": float(context.contribution_amount),
            "contribution_frequency": str(context.contribution_frequency),
            "emulate_live_trading": bool(context.emulate_live_trading),
            "require_fractionable": bool(context.require_fractionable),
            "max_position_size": float(context.max_position_size),
            "risk_limit_daily": float(context.risk_limit_daily),
            "fee_bps": float(context.fee_bps),
            "universe_context": dict(context.universe_context or {}),
            "symbol_capabilities": {
                str(symbol): {
                    "tradable": bool((caps or {}).get("tradable", True)),
                    "fractionable": bool((caps or {}).get("fractionable", True)),
                }
                for symbol, caps in (context.symbol_capabilities or {}).items()
            },
            "alpaca_creds": dict(context.alpaca_creds) if isinstance(context.alpaca_creds, dict) else None,
            "require_real_data": bool(context.require_real_data),
            "cancel_token_path": (
                str(context.cancel_token_path).strip()
                if context.cancel_token_path
                else None
            ),
        }

    def _build_summary_backtest_result(
        self,
        *,
        context: OptimizationContext,
        parameters: Dict[str, float],
        robustness: Optional[Dict[str, float]],
    ) -> BacktestResult:
        robust = robustness if isinstance(robustness, dict) else {}
        total_return = float(robust.get("median_return", 0.0) or 0.0)
        sharpe = float(robust.get("median_sharpe", 0.0) or 0.0)
        drawdown = float(robust.get("p95_drawdown", 0.0) or 0.0)
        trades = int(max(0.0, float(robust.get("median_trades", 0.0) or 0.0)))
        final_capital = max(0.0, float(context.initial_capital) * (1.0 + total_return / 100.0))
        return BacktestResult(
            strategy_id=context.strategy_id,
            start_date=context.start_date,
            end_date=context.end_date,
            initial_capital=float(context.initial_capital),
            final_capital=round(final_capital, 2),
            total_return=round(total_return, 6),
            total_trades=trades,
            winning_trades=0,
            losing_trades=0,
            win_rate=0.0,
            max_drawdown=round(drawdown, 6),
            sharpe_ratio=round(sharpe, 6),
            volatility=0.0,
            trades=[],
            equity_curve=[],
            diagnostics={
                "optimizer": {
                    "ensemble_mode": True,
                    "summary_only": True,
                    "robustness": robust,
                    "parameters": {key: float(value) for key, value in parameters.items()},
                }
            },
        )

    @staticmethod
    def _resolve_max_workers(requested: Optional[int]) -> int:
        cpu_total = max(1, int(os.cpu_count() or 1))
        default_workers = min(4, max(1, cpu_total - 1))
        if requested is None:
            return max(1, min(6, default_workers))
        try:
            parsed = int(requested)
        except (TypeError, ValueError):
            return max(1, min(6, default_workers))
        return max(1, min(6, parsed, cpu_total))

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
        return _objective_score_for_result(
            result=result,
            min_trades=min_trades,
            objective=objective,
            strict_min_trades=strict_min_trades,
        )

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
                alpaca_creds=dict(context.alpaca_creds) if isinstance(context.alpaca_creds, dict) else None,
                require_real_data=bool(context.require_real_data),
                cancel_token_path=context.cancel_token_path,
            )
            fold_result = self._run_backtest(
                context=fold_context,
                symbols=symbols,
                parameters=parameters,
                should_cancel=should_cancel,
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
