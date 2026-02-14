"""
Strategy Analytics Service.
Provides functionality for calculating strategy metrics, backtesting,
and performance analysis.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone, date as date_type
from sqlalchemy.orm import Session

from storage.service import StorageService
from config.strategy_config import (
    StrategyMetrics,
    BacktestRequest,
    BacktestResult,
)
from services.market_screener import MarketScreener

# Default slippage applied to each fill (basis points).
_DEFAULT_SLIPPAGE_BPS = 5.0


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

    def run_backtest(self, request: BacktestRequest) -> BacktestResult:
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
        cash = initial_capital
        trade_id = 1
        diagnostics: Dict[str, Any] = {
            "symbols_requested": len(symbols),
            "symbols_with_data": 0,
            "symbols_without_data": [],
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
            },
            "exit_reasons": {
                "stop_exit": 0,
                "take_profit_exit": 0,
                "time_exit": 0,
                "end_of_backtest": 0,
            },
            "parameters_used": {k: float(v) for k, v in params.items()},
        }

        lookback_days = max(320, (end_dt.date() - start_dt.date()).days + 320)
        screener = MarketScreener(
            alpaca_client=self._alpaca_creds,
            require_real_data=self._require_real_data,
        )

        series_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        # Build date-keyed index per symbol for O(1) lookups.
        date_index_by_symbol: Dict[str, Dict[date_type, Dict[str, Any]]] = {}
        latest_price_by_symbol: Dict[str, float] = {}
        all_dates: set[date_type] = set()
        for symbol in symbols:
            points = screener.get_symbol_chart(symbol, days=lookback_days)
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
        slippage_bps = _DEFAULT_SLIPPAGE_BPS
        max_hold_days = int(params.get("max_hold_days", 10))

        for day in sorted(all_dates):
            if day < start_dt.date() or day > end_dt.date():
                continue
            diagnostics["trading_days_evaluated"] += 1
            day_ts = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)

            for symbol in sorted(series_by_symbol.keys()):
                point = date_index_by_symbol[symbol].get(day)
                if point is None:
                    continue
                diagnostics["bars_evaluated"] += 1
                close = float(point["close"])
                high = float(point["high"])
                low = float(point["low"])
                latest_price_by_symbol[symbol] = close

                position = open_positions.get(symbol)
                if position is not None:
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
                    if days_held >= max_hold_days:
                        exit_price = close * (1.0 - slippage_bps / 10000.0)
                        exit_reason = "time_exit"
                    elif low <= effective_stop:
                        # Apply slippage to stop fills (fills slightly worse).
                        exit_price = effective_stop * (1.0 - slippage_bps / 10000.0)
                        exit_reason = "stop_exit"
                    elif high >= take_profit_price:
                        # TP fills can also experience minor slippage.
                        exit_price = take_profit_price * (1.0 - slippage_bps / 10000.0)
                        exit_reason = "take_profit_exit"

                    if exit_price is not None:
                        diagnostics["exit_reasons"][exit_reason] = diagnostics["exit_reasons"].get(exit_reason, 0) + 1
                        qty = float(position["qty"])
                        entry_price = float(position["entry_price"])
                        pnl = (exit_price - entry_price) * qty
                        cash += qty * exit_price
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
                        })
                        trade_id += 1
                        del open_positions[symbol]
                        continue

                if symbol in open_positions:
                    diagnostics["blocked_reasons"]["already_in_position"] += 1
                    continue

                diagnostics["entry_checks"] += 1
                metrics = self._compute_signal_metrics(series_by_symbol[symbol], day, params)
                if metrics is None:
                    diagnostics["blocked_reasons"]["insufficient_history"] += 1
                    continue
                if not metrics["dip_buy_signal"]:
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
                # Use shared risk-based position sizing.
                target_notional = compute_risk_based_position_size(
                    equity=open_equity,
                    risk_per_trade_pct=params["risk_per_trade"],
                    stop_loss_pct=params["stop_loss_pct"],
                    position_size_cap=params["position_size"],
                    cash=cash,
                )
                if target_notional < 1.0:
                    diagnostics["blocked_reasons"]["risk_cap_too_low"] += 1
                    continue
                # Apply entry slippage (buy slightly higher).
                fill_price = close * (1.0 + slippage_bps / 10000.0)
                qty = target_notional / fill_price if fill_price > 0 else 0.0
                if qty <= 0:
                    diagnostics["blocked_reasons"]["invalid_position_size"] += 1
                    continue
                fill_notional = qty * fill_price
                if fill_notional > cash:
                    diagnostics["blocked_reasons"]["cash_insufficient"] += 1
                    continue

                cash -= fill_notional
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
                }
                diagnostics["entries_opened"] += 1

            market_value = sum(
                float(pos["qty"]) * latest_price_by_symbol.get(sym, float(pos["entry_price"]))
                for sym, pos in open_positions.items()
            )
            equity_curve.append({
                "timestamp": day_ts.isoformat(),
                "equity": round(cash + market_value, 2),
            })

        # Force-close remaining positions at end of window.
        if open_positions:
            final_ts = datetime.combine(end_dt.date(), datetime.min.time(), tzinfo=timezone.utc)
            for symbol in sorted(list(open_positions.keys())):
                pos = open_positions[symbol]
                close = latest_price_by_symbol.get(symbol, float(pos["entry_price"]))
                exit_price = close * (1.0 - slippage_bps / 10000.0)
                qty = float(pos["qty"])
                entry_price = float(pos["entry_price"])
                pnl = (exit_price - entry_price) * qty
                cash += qty * exit_price
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
                })
                trade_id += 1
                del open_positions[symbol]
            equity_curve.append({"timestamp": final_ts.isoformat(), "equity": round(cash, 2)})

        final_capital = round(cash, 2)
        total_pnl = final_capital - initial_capital
        total_trades = len(trades)
        winning_trades = len([t for t in trades if t["pnl"] > 0])
        losing_trades = len([t for t in trades if t["pnl"] < 0])
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
        total_return = (total_pnl / initial_capital * 100) if initial_capital > 0 else 0.0

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

        blocked_nonzero = [
            {"reason": reason, "count": count}
            for reason, count in diagnostics["blocked_reasons"].items()
            if count > 0
        ]
        blocked_nonzero.sort(key=lambda item: item["count"], reverse=True)
        diagnostics["top_blockers"] = blocked_nonzero[:5]
        diagnostics["symbols_without_data"] = sorted(set(diagnostics["symbols_without_data"]))
        diagnostics["advanced_metrics"] = {
            "profit_factor": round(profit_factor, 3),
            "sortino_ratio": round(sortino_ratio, 3),
            "expectancy_per_trade": round(expectancy, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "avg_win_loss_ratio": round(avg_win / abs(avg_loss), 2) if avg_loss != 0 else 0.0,
            "max_consecutive_losses": max_consecutive_losses,
            "recovery_factor": round(recovery_factor, 3),
            "calmar_ratio": round(calmar_ratio, 3),
            "avg_hold_days": round(avg_hold_days, 1),
            "slippage_bps_applied": slippage_bps,
        }

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
            "max_hold_days": 10.0,
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
            except (TypeError, ValueError):
                continue
            if close <= 0:
                continue
            if high < low:
                high, low = low, high
            series.append({
                "date": date_key,
                "timestamp": ts,
                "close": close,
                "high": high,
                "low": low,
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
        # Require 50 bars of history for the 50-period z-score window.
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

        # Composite entry signal: either condition can trigger, weighted.
        dip_trigger_price = float(latest_sma50) * (1.0 - (params["dip_buy_threshold_pct"] / 100.0))
        dip_condition = latest_close <= dip_trigger_price
        zscore_condition = zscore <= params["zscore_entry_threshold"]
        # Signal fires if either condition is met (relaxed from requiring both).
        dip_buy_signal = dip_condition or zscore_condition

        regime = self._detect_regime(closes)
        return {
            "atr14_pct": atr_pct,
            "zscore": zscore,
            "dip_buy_signal": dip_buy_signal,
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
        # Daily volatility (stdev of daily returns).
        vol = (sum(r * r for r in returns) / len(returns)) ** 0.5 if returns else 0.0
        # Tighter threshold (0.015 daily ~ 23.8% annualized) for better separation.
        if trend > 0.04 and vol < 0.015:
            return "trending_up"
        if trend < -0.04 and vol < 0.015:
            return "trending_down"
        if vol >= 0.015:
            return "high_volatility_range"
        return "range_bound"

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
        """Calculate annualized Sharpe ratio."""
        if len(returns) < 2:
            return 0.0
        mean_return = sum(returns) / len(returns)
        mean_sq = sum(r * r for r in returns) / len(returns)
        variance = mean_sq - mean_return * mean_return
        daily_vol = max(0.0, variance) ** 0.5
        if daily_vol == 0:
            return 0.0
        annualized_return = mean_return * 252
        annualized_vol = daily_vol * (252 ** 0.5)
        return round((annualized_return - risk_free_rate) / annualized_vol, 4)

    def _calculate_sortino_ratio(self, returns: List[float], risk_free_rate: float = 0.02) -> float:
        """Calculate annualized Sortino ratio (penalizes only downside vol)."""
        if len(returns) < 2:
            return 0.0
        mean_return = sum(returns) / len(returns)
        downside = [r for r in returns if r < 0]
        if not downside:
            return 0.0
        downside_var = sum(r * r for r in downside) / len(downside)
        downside_vol = downside_var ** 0.5
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
