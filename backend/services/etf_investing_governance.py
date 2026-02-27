"""
ETF investing governance and taxable-account universe controls.

Applies Scenario-2 style controls:
- Allow-list metadata (role/max weight/min trade size/enabled)
- Monthly screening cadence
- Quarterly replacement throttle
- Conservative replacement rules
- Tax-aware rebalance and optional TLH opportunity hints
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import json
import math

from config.investing_defaults import (
    ETF_INVESTING_ALLOW_LIST_DEFAULT,
    ETF_INVESTING_GOVERNANCE_BUY_ONLY_REBALANCE_DEFAULT,
    ETF_INVESTING_GOVERNANCE_MAX_REPLACEMENTS_PER_QUARTER_DEFAULT,
    ETF_INVESTING_GOVERNANCE_MIN_DOLLAR_VOLUME_DEFAULT,
    ETF_INVESTING_GOVERNANCE_MIN_HOLD_DAYS_DEFAULT,
    ETF_INVESTING_GOVERNANCE_MIN_HISTORY_DAYS_PREFERRED,
    ETF_INVESTING_GOVERNANCE_MIN_SCORE_DELTA_PCT_DEFAULT,
    ETF_INVESTING_GOVERNANCE_REBALANCE_DRIFT_THRESHOLD_PCT_DEFAULT,
    ETF_INVESTING_GOVERNANCE_REPLACEMENT_INTERVAL_DAYS_DEFAULT,
    ETF_INVESTING_GOVERNANCE_SCREEN_INTERVAL_DAYS_DEFAULT,
    ETF_INVESTING_TLH_ENABLED_DEFAULT,
    ETF_INVESTING_TLH_MIN_HOLD_DAYS_DEFAULT,
    ETF_INVESTING_TLH_MIN_LOSS_DOLLARS_DEFAULT,
    ETF_INVESTING_TLH_MIN_LOSS_PCT_DEFAULT,
    ETF_INVESTING_TLH_REPLACEMENT_MAP,
)
from storage.service import StorageService

_POLICY_KEY = "etf_investing_policy_v1"
_STATE_KEY = "etf_investing_policy_state_v1"


@dataclass
class GovernanceResult:
    assets: List[Dict[str, Any]]
    symbols: List[str]
    report: Dict[str, Any]


class ETFInvestingGovernanceService:
    """Persisted governance layer for ETF universe selection."""

    def __init__(self, storage: StorageService):
        self.storage = storage

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(parsed):
            return default
        return parsed

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed

    @staticmethod
    def _parse_iso(value: Any) -> Optional[datetime]:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _default_policy(self) -> Dict[str, Any]:
        return {
            "enabled": True,
            "dynamic_candidates_enabled": True,
            "screen_interval_days": ETF_INVESTING_GOVERNANCE_SCREEN_INTERVAL_DAYS_DEFAULT,
            "replacement_interval_days": ETF_INVESTING_GOVERNANCE_REPLACEMENT_INTERVAL_DAYS_DEFAULT,
            "max_replacements_per_quarter": ETF_INVESTING_GOVERNANCE_MAX_REPLACEMENTS_PER_QUARTER_DEFAULT,
            "min_hold_days_for_replacement": ETF_INVESTING_GOVERNANCE_MIN_HOLD_DAYS_DEFAULT,
            "min_replacement_score_delta_pct": ETF_INVESTING_GOVERNANCE_MIN_SCORE_DELTA_PCT_DEFAULT,
            "min_dollar_volume": ETF_INVESTING_GOVERNANCE_MIN_DOLLAR_VOLUME_DEFAULT,
            "min_history_days_preferred": ETF_INVESTING_GOVERNANCE_MIN_HISTORY_DAYS_PREFERRED,
            "rebalance_drift_threshold_pct": ETF_INVESTING_GOVERNANCE_REBALANCE_DRIFT_THRESHOLD_PCT_DEFAULT,
            "buy_only_rebalance": ETF_INVESTING_GOVERNANCE_BUY_ONLY_REBALANCE_DEFAULT,
            "tlh_enabled": ETF_INVESTING_TLH_ENABLED_DEFAULT,
            "tlh_min_loss_dollars": ETF_INVESTING_TLH_MIN_LOSS_DOLLARS_DEFAULT,
            "tlh_min_loss_pct": ETF_INVESTING_TLH_MIN_LOSS_PCT_DEFAULT,
            "tlh_min_hold_days": ETF_INVESTING_TLH_MIN_HOLD_DAYS_DEFAULT,
            "allow_list": [dict(row) for row in ETF_INVESTING_ALLOW_LIST_DEFAULT],
        }

    def _sanitize_allow_list(self, raw: Any) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        seen: set[str] = set()
        source = raw if isinstance(raw, list) else list(ETF_INVESTING_ALLOW_LIST_DEFAULT)
        for entry in source:
            if not isinstance(entry, dict):
                continue
            symbol = str(entry.get("symbol", "")).strip().upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            role = str(entry.get("role", "both")).strip().lower()
            if role not in {"dca", "active", "both"}:
                role = "both"
            max_weight_pct = max(1.0, min(100.0, self._safe_float(entry.get("max_weight_pct"), 10.0)))
            min_trade_size = max(1.0, self._safe_float(entry.get("min_trade_size"), 1.0))
            rows.append(
                {
                    "symbol": symbol,
                    "role": role,
                    "max_weight_pct": round(float(max_weight_pct), 4),
                    "min_trade_size": round(float(min_trade_size), 4),
                    "enabled": bool(entry.get("enabled", True)),
                }
            )
        if not rows:
            return [dict(row) for row in ETF_INVESTING_ALLOW_LIST_DEFAULT]
        return rows

    def load_policy(self) -> Dict[str, Any]:
        baseline = self._default_policy()
        raw = self.storage.get_config_value(_POLICY_KEY, default="")
        if raw:
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    baseline.update(payload)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        baseline["screen_interval_days"] = max(7, min(180, self._safe_int(baseline.get("screen_interval_days"), 30)))
        baseline["replacement_interval_days"] = max(
            30,
            min(365, self._safe_int(baseline.get("replacement_interval_days"), 90)),
        )
        baseline["max_replacements_per_quarter"] = max(
            0,
            min(5, self._safe_int(baseline.get("max_replacements_per_quarter"), 1)),
        )
        baseline["min_hold_days_for_replacement"] = max(
            30,
            min(730, self._safe_int(baseline.get("min_hold_days_for_replacement"), 180)),
        )
        baseline["min_replacement_score_delta_pct"] = max(
            0.0,
            min(200.0, self._safe_float(baseline.get("min_replacement_score_delta_pct"), 20.0)),
        )
        baseline["min_dollar_volume"] = max(
            1_000_000.0,
            min(1_000_000_000.0, self._safe_float(baseline.get("min_dollar_volume"), 50_000_000.0)),
        )
        baseline["min_history_days_preferred"] = max(
            60,
            min(2_500, self._safe_int(baseline.get("min_history_days_preferred"), 252 * 3)),
        )
        baseline["rebalance_drift_threshold_pct"] = max(
            1.0,
            min(25.0, self._safe_float(baseline.get("rebalance_drift_threshold_pct"), 5.0)),
        )
        baseline["buy_only_rebalance"] = bool(baseline.get("buy_only_rebalance", True))
        baseline["tlh_enabled"] = bool(baseline.get("tlh_enabled", False))
        baseline["tlh_min_loss_dollars"] = max(
            50.0,
            min(50_000.0, self._safe_float(baseline.get("tlh_min_loss_dollars"), 250.0)),
        )
        baseline["tlh_min_loss_pct"] = max(
            1.0,
            min(50.0, self._safe_float(baseline.get("tlh_min_loss_pct"), 5.0)),
        )
        baseline["tlh_min_hold_days"] = max(
            7,
            min(365, self._safe_int(baseline.get("tlh_min_hold_days"), 30)),
        )
        baseline["allow_list"] = self._sanitize_allow_list(baseline.get("allow_list"))
        baseline["enabled"] = bool(baseline.get("enabled", True))
        baseline["dynamic_candidates_enabled"] = bool(baseline.get("dynamic_candidates_enabled", True))
        return baseline

    def save_policy(self, policy: Dict[str, Any]) -> None:
        normalized = self.load_policy()
        if isinstance(policy, dict):
            normalized.update(policy)
            normalized["allow_list"] = self._sanitize_allow_list(policy.get("allow_list", normalized.get("allow_list")))
        self.storage.set_config_value(
            key=_POLICY_KEY,
            value=json.dumps(normalized, separators=(",", ":")),
            value_type="json",
            description="ETF investing universe governance policy",
        )

    def load_state(self) -> Dict[str, Any]:
        raw = self.storage.get_config_value(_STATE_KEY, default="")
        state: Dict[str, Any] = {
            "last_screened_at": None,
            "last_replacement_at": None,
            "selected_symbols": {"active": [], "dca": []},
            "symbol_first_seen": {},
            "quarter_replacements": {},
            "last_scores": {},
            "wash_sale_locks": {},
        }
        if not raw:
            return state
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return state
        if not isinstance(payload, dict):
            return state
        state.update(payload)
        selected_symbols = state.get("selected_symbols")
        if not isinstance(selected_symbols, dict):
            selected_symbols = {}
        state["selected_symbols"] = {
            "active": [
                str(s).strip().upper()
                for s in (selected_symbols.get("active") or [])
                if str(s).strip()
            ],
            "dca": [
                str(s).strip().upper()
                for s in (selected_symbols.get("dca") or [])
                if str(s).strip()
            ],
        }
        if not isinstance(state.get("symbol_first_seen"), dict):
            state["symbol_first_seen"] = {}
        if not isinstance(state.get("quarter_replacements"), dict):
            state["quarter_replacements"] = {}
        if not isinstance(state.get("last_scores"), dict):
            state["last_scores"] = {}
        if not isinstance(state.get("wash_sale_locks"), dict):
            state["wash_sale_locks"] = {}
        return state

    def save_state(self, state: Dict[str, Any]) -> None:
        self.storage.set_config_value(
            key=_STATE_KEY,
            value=json.dumps(state, separators=(",", ":")),
            value_type="json",
            description="ETF investing universe governance runtime state",
        )

    @staticmethod
    def _quarter_key(now: datetime) -> str:
        quarter = ((int(now.month) - 1) // 3) + 1
        return f"{int(now.year)}Q{quarter}"

    @staticmethod
    def _is_leveraged_or_inverse(symbol: str, name: str) -> bool:
        haystack = f"{symbol} {name}".lower()
        tokens = (
            "ultra",
            "3x",
            "2x",
            "-1x",
            "-2x",
            "-3x",
            "inverse",
            "bear",
            "short",
            "daily",
            "leveraged",
        )
        return any(token in haystack for token in tokens)

    def _history_metrics(self, screener: Any, symbol: str) -> Dict[str, float]:
        points = screener.get_symbol_chart_window(symbol=symbol, days=900)
        closes = [self._safe_float(row.get("close"), 0.0) for row in points if isinstance(row, dict)]
        closes = [row for row in closes if row > 0]
        if len(closes) < 60:
            return {
                "history_days": float(len(closes)),
                "volatility": 0.30,
                "trend_stability": 0.45,
                "return_12m": 0.0,
            }
        returns: List[float] = []
        for idx in range(1, len(closes)):
            prev = closes[idx - 1]
            if prev <= 0:
                continue
            returns.append((closes[idx] - prev) / prev)
        if returns:
            mean = sum(returns) / len(returns)
            var = sum((row - mean) ** 2 for row in returns) / max(1, len(returns) - 1)
            volatility = math.sqrt(max(0.0, var)) * math.sqrt(252.0)
        else:
            volatility = 0.30

        sma200 = sum(closes[-200:]) / 200.0 if len(closes) >= 200 else sum(closes) / len(closes)
        above_ratio = (
            sum(1 for row in closes[-252:] if row >= sma200) / max(1, min(252, len(closes)))
        )
        return_12m = 0.0
        lookback = min(252, len(closes) - 1)
        if lookback > 0:
            base = closes[-(lookback + 1)]
            if base > 0:
                return_12m = (closes[-1] - base) / base
        trend_stability = max(0.0, min(1.0, (above_ratio * 0.7) + (0.3 if return_12m > 0 else 0.0)))
        return {
            "history_days": float(len(closes)),
            "volatility": max(0.0, volatility),
            "trend_stability": trend_stability,
            "return_12m": return_12m,
        }

    @staticmethod
    def _correlation(a: List[float], b: List[float]) -> Optional[float]:
        n = min(len(a), len(b))
        if n < 30:
            return None
        xa = a[-n:]
        xb = b[-n:]
        ma = sum(xa) / n
        mb = sum(xb) / n
        va = sum((row - ma) ** 2 for row in xa)
        vb = sum((row - mb) ** 2 for row in xb)
        if va <= 0 or vb <= 0:
            return None
        cov = sum((xa[idx] - ma) * (xb[idx] - mb) for idx in range(n))
        return cov / math.sqrt(va * vb)

    def _returns_for_symbol(self, screener: Any, symbol: str) -> List[float]:
        points = screener.get_symbol_chart_window(symbol=symbol, days=400)
        closes = [self._safe_float(row.get("close"), 0.0) for row in points if isinstance(row, dict)]
        closes = [row for row in closes if row > 0]
        returns: List[float] = []
        for idx in range(1, len(closes)):
            prev = closes[idx - 1]
            if prev > 0:
                returns.append((closes[idx] - prev) / prev)
        return returns

    def _average_pairwise_correlation(
        self,
        screener: Any,
        symbols: List[str],
    ) -> Optional[float]:
        if len(symbols) < 2:
            return 0.0
        returns_cache: Dict[str, List[float]] = {
            symbol: self._returns_for_symbol(screener, symbol)
            for symbol in symbols
        }
        rows: List[float] = []
        for idx in range(len(symbols)):
            for jdx in range(idx + 1, len(symbols)):
                corr = self._correlation(
                    returns_cache.get(symbols[idx], []),
                    returns_cache.get(symbols[jdx], []),
                )
                if corr is None:
                    continue
                rows.append(abs(float(corr)))
        if not rows:
            return None
        return sum(rows) / float(len(rows))

    def _eligible_assets(
        self,
        *,
        assets: List[Dict[str, Any]],
        allow_roles: Dict[str, Dict[str, Any]],
        min_dollar_volume: float,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        kept: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []
        for raw in assets:
            symbol = str(raw.get("symbol", "")).strip().upper()
            if not symbol:
                continue
            row = dict(raw)
            meta = allow_roles.get(symbol)
            if not meta or not bool(meta.get("enabled", True)):
                rejected.append({"symbol": symbol, "reason": "not_in_enabled_allow_list"})
                continue
            name = str(row.get("name", "") or "")
            if self._is_leveraged_or_inverse(symbol, name):
                rejected.append({"symbol": symbol, "reason": "leveraged_or_inverse_excluded"})
                continue
            asset_type = str(row.get("asset_type", "etf")).strip().lower()
            if asset_type != "etf":
                rejected.append({"symbol": symbol, "reason": "non_etf_excluded"})
                continue
            dollar_volume = self._safe_float(row.get("dollar_volume"), 0.0)
            if dollar_volume < min_dollar_volume:
                rejected.append(
                    {
                        "symbol": symbol,
                        "reason": "insufficient_dollar_volume",
                        "dollar_volume": round(dollar_volume, 2),
                    }
                )
                continue
            if row.get("broker_tradable") is False:
                rejected.append({"symbol": symbol, "reason": "not_tradable"})
                continue
            if row.get("fractionable") is False:
                rejected.append({"symbol": symbol, "reason": "not_fractionable"})
                continue
            row["_allow_meta"] = meta
            kept.append(row)
        return kept, rejected

    def _score_assets(
        self,
        *,
        screener: Any,
        assets: List[Dict[str, Any]],
        min_history_days_preferred: int,
    ) -> List[Dict[str, Any]]:
        spy_returns = self._returns_for_symbol(screener, "SPY")
        scored: List[Dict[str, Any]] = []
        for raw in assets:
            symbol = str(raw.get("symbol", "")).strip().upper()
            history = self._history_metrics(screener, symbol)
            vol = float(history.get("volatility", 0.30))
            trend_stability = float(history.get("trend_stability", 0.45))
            history_days = float(history.get("history_days", 0.0))
            symbol_returns = self._returns_for_symbol(screener, symbol)
            corr = self._correlation(symbol_returns, spy_returns)
            corr_abs = abs(float(corr)) if corr is not None else 0.65

            liquidity = max(0.0, min(1.0, self._safe_float(raw.get("dollar_volume"), 0.0) / 200_000_000.0))
            volatility_component = max(0.0, min(1.0, 1.0 - (vol / 0.45)))
            trend_component = max(0.0, min(1.0, trend_stability))
            diversification_component = max(0.0, min(1.0, 1.0 - max(0.0, (corr_abs - 0.60) / 0.40)))
            history_penalty = 0.0
            if history_days < float(min_history_days_preferred):
                history_penalty = min(20.0, ((float(min_history_days_preferred) - history_days) / 365.0) * 5.0)
            score = (
                100.0
                * (
                    (0.30 * liquidity)
                    + (0.25 * volatility_component)
                    + (0.25 * trend_component)
                    + (0.20 * diversification_component)
                )
            ) - history_penalty
            row = dict(raw)
            row["governance_score"] = round(float(score), 4)
            row["governance_score_components"] = {
                "liquidity": round(liquidity, 4),
                "volatility_component": round(volatility_component, 4),
                "trend_stability": round(trend_component, 4),
                "diversification_component": round(diversification_component, 4),
                "history_days": int(history_days),
                "history_penalty": round(history_penalty, 4),
            }
            scored.append(row)
        scored.sort(key=lambda row: float(row.get("governance_score", 0.0)), reverse=True)
        return scored

    def _allow_map(self, policy: Dict[str, Any], role: str) -> Dict[str, Dict[str, Any]]:
        requested_role = str(role or "active").strip().lower()
        allow_rows = policy.get("allow_list", [])
        if not isinstance(allow_rows, list):
            return {}
        allowed_roles = {"both", requested_role}
        if requested_role == "active":
            allowed_roles = {"active", "both"}
        elif requested_role == "dca":
            allowed_roles = {"dca", "both"}
        selected: Dict[str, Dict[str, Any]] = {}
        for raw in allow_rows:
            if not isinstance(raw, dict):
                continue
            symbol = str(raw.get("symbol", "")).strip().upper()
            if not symbol:
                continue
            row_role = str(raw.get("role", "both")).strip().lower()
            if row_role not in allowed_roles:
                continue
            selected[symbol] = dict(raw)
        return selected

    def _build_tax_report(
        self,
        *,
        policy: Dict[str, Any],
        holdings_snapshot: List[Dict[str, Any]],
        allow_roles: Dict[str, Dict[str, Any]],
        state: Dict[str, Any],
        now: datetime,
    ) -> Dict[str, Any]:
        dca_rows = [row for row in allow_roles.values() if str(row.get("role", "both")) in {"dca", "both"}]
        target_total = sum(max(0.0, self._safe_float(row.get("max_weight_pct"), 0.0)) for row in dca_rows)
        if target_total <= 0:
            target_total = 1.0
        target_weights = {
            str(row.get("symbol", "")).strip().upper(): (self._safe_float(row.get("max_weight_pct"), 0.0) / target_total)
            for row in dca_rows
            if str(row.get("symbol", "")).strip()
        }
        market_values: Dict[str, float] = {}
        total_value = 0.0
        for row in holdings_snapshot or []:
            symbol = str(row.get("symbol", "")).strip().upper()
            if not symbol:
                continue
            mv = max(0.0, self._safe_float(row.get("market_value"), 0.0))
            market_values[symbol] = market_values.get(symbol, 0.0) + mv
            total_value += mv
        drift_threshold = self._safe_float(policy.get("rebalance_drift_threshold_pct"), 5.0)
        drift_rows: List[Dict[str, Any]] = []
        for symbol, target_weight in target_weights.items():
            actual_weight = (market_values.get(symbol, 0.0) / total_value) if total_value > 0 else 0.0
            drift_pct = (actual_weight - target_weight) * 100.0
            if abs(drift_pct) >= drift_threshold:
                drift_rows.append(
                    {
                        "symbol": symbol,
                        "target_weight_pct": round(target_weight * 100.0, 4),
                        "actual_weight_pct": round(actual_weight * 100.0, 4),
                        "drift_pct": round(drift_pct, 4),
                        "recommended_action": "buy_only_top_up"
                        if bool(policy.get("buy_only_rebalance", True)) and drift_pct < 0
                        else "review_rebalance",
                    }
                )

        tlh_rows: List[Dict[str, Any]] = []
        if bool(policy.get("tlh_enabled", False)):
            min_loss_dollars = self._safe_float(policy.get("tlh_min_loss_dollars"), 250.0)
            min_loss_pct = self._safe_float(policy.get("tlh_min_loss_pct"), 5.0)
            min_hold_days = self._safe_int(policy.get("tlh_min_hold_days"), 30)
            first_seen = state.get("symbol_first_seen", {}) if isinstance(state.get("symbol_first_seen"), dict) else {}
            replacements = dict(ETF_INVESTING_TLH_REPLACEMENT_MAP)
            for holding in holdings_snapshot or []:
                symbol = str(holding.get("symbol", "")).strip().upper()
                qty = max(0.0, self._safe_float(holding.get("quantity"), 0.0))
                if not symbol or qty <= 0:
                    continue
                avg_entry = self._safe_float(holding.get("avg_entry_price"), 0.0)
                current_price = self._safe_float(holding.get("current_price"), 0.0)
                if avg_entry <= 0 or current_price <= 0:
                    continue
                unrealized = (current_price - avg_entry) * qty
                if unrealized >= 0:
                    continue
                loss_dollars = abs(unrealized)
                loss_pct = (loss_dollars / (avg_entry * qty)) * 100.0 if (avg_entry * qty) > 0 else 0.0
                first_seen_dt = self._parse_iso(first_seen.get(symbol))
                hold_days = (now - first_seen_dt).days if first_seen_dt is not None else 0
                if hold_days < min_hold_days:
                    continue
                if loss_dollars < min_loss_dollars and loss_pct < min_loss_pct:
                    continue
                tlh_rows.append(
                    {
                        "symbol": symbol,
                        "loss_dollars": round(loss_dollars, 4),
                        "loss_pct": round(loss_pct, 4),
                        "hold_days": hold_days,
                        "candidate_replacement": replacements.get(symbol),
                        "wash_sale_note": "Ensure replacement buy avoids same CUSIP for 30 days",
                    }
                )

        return {
            "rebalance": {
                "drift_threshold_pct": round(drift_threshold, 4),
                "buy_only_mode": bool(policy.get("buy_only_rebalance", True)),
                "drift_alerts": drift_rows,
            },
            "tax_loss_harvesting": {
                "enabled": bool(policy.get("tlh_enabled", False)),
                "opportunities": tlh_rows,
            },
        }

    def enforce(
        self,
        *,
        screener: Any,
        assets: List[Dict[str, Any]],
        role: str,
        holdings_snapshot: Optional[List[Dict[str, Any]]] = None,
        force_screen: bool = False,
        now: Optional[datetime] = None,
    ) -> GovernanceResult:
        policy = self.load_policy()
        state = self.load_state()
        when = now or self._now_utc()
        allow_roles = self._allow_map(policy, role=role)
        enabled_allow_symbols = list(allow_roles.keys())

        if not bool(policy.get("enabled", True)):
            passthrough = [dict(row) for row in assets if str(row.get("symbol", "")).strip().upper() in set(enabled_allow_symbols)]
            return GovernanceResult(
                assets=passthrough,
                symbols=[str(row.get("symbol", "")).strip().upper() for row in passthrough if row.get("symbol")],
                report={
                    "enabled": False,
                    "reason": "governance_disabled",
                    "allow_list_symbols": enabled_allow_symbols,
                },
            )

        eligible, rejected = self._eligible_assets(
            assets=assets,
            allow_roles=allow_roles,
            min_dollar_volume=self._safe_float(policy.get("min_dollar_volume"), 50_000_000.0),
        )
        scored = self._score_assets(
            screener=screener,
            assets=eligible,
            min_history_days_preferred=self._safe_int(policy.get("min_history_days_preferred"), 252 * 3),
        )
        scores = {
            str(row.get("symbol", "")).strip().upper(): self._safe_float(row.get("governance_score"), 0.0)
            for row in scored
        }
        last_screened_at = self._parse_iso(state.get("last_screened_at"))
        last_replacement_at = self._parse_iso(state.get("last_replacement_at"))
        screen_due = force_screen or last_screened_at is None or (
            when - last_screened_at >= timedelta(days=self._safe_int(policy.get("screen_interval_days"), 30))
        )
        replacement_due = force_screen or last_replacement_at is None or (
            when - last_replacement_at >= timedelta(days=self._safe_int(policy.get("replacement_interval_days"), 90))
        )
        role_key = str(role or "active").strip().lower()
        selected_state = state.get("selected_symbols", {}) if isinstance(state.get("selected_symbols"), dict) else {}
        current_symbols = [
            str(s).strip().upper()
            for s in (selected_state.get(role_key) or [])
            if str(s).strip()
        ]
        if not current_symbols:
            current_symbols = list(enabled_allow_symbols)
        scored_symbols = [str(row.get("symbol", "")).strip().upper() for row in scored]
        symbol_to_asset = {
            str(row.get("symbol", "")).strip().upper(): row
            for row in scored
        }
        first_seen = state.get("symbol_first_seen", {}) if isinstance(state.get("symbol_first_seen"), dict) else {}

        replacement_event: Optional[Dict[str, Any]] = None
        if screen_due:
            current_symbols = [sym for sym in current_symbols if sym in symbol_to_asset]
            if not current_symbols:
                current_symbols = scored_symbols[: max(1, min(5, len(scored_symbols)))]

            if bool(policy.get("dynamic_candidates_enabled", True)) and replacement_due and current_symbols:
                q_key = self._quarter_key(when)
                quarter_counts = state.get("quarter_replacements", {})
                if not isinstance(quarter_counts, dict):
                    quarter_counts = {}
                replacements_used = self._safe_int(quarter_counts.get(q_key), 0)
                replacements_cap = self._safe_int(policy.get("max_replacements_per_quarter"), 1)
                if replacements_used < replacements_cap:
                    ranked_current = sorted(
                        current_symbols,
                        key=lambda sym: self._safe_float(scores.get(sym), -9999.0),
                    )
                    bottom_count = max(1, int(math.ceil(len(ranked_current) * 0.2)))
                    bottom_pool = ranked_current[:bottom_count]
                    min_hold_days = self._safe_int(policy.get("min_hold_days_for_replacement"), 180)
                    score_delta_pct = self._safe_float(policy.get("min_replacement_score_delta_pct"), 20.0)
                    replace_target: Optional[str] = None
                    replacement_symbol: Optional[str] = None
                    for old_symbol in bottom_pool:
                        old_seen = self._parse_iso(first_seen.get(old_symbol))
                        hold_days = (when - old_seen).days if old_seen else 0
                        if hold_days < min_hold_days:
                            continue
                        old_score = self._safe_float(scores.get(old_symbol), 0.0)
                        if old_score <= 0:
                            continue
                        threshold = old_score * (1.0 + (score_delta_pct / 100.0))
                        baseline_corr = self._average_pairwise_correlation(screener, list(current_symbols))
                        for candidate in scored_symbols:
                            if candidate in current_symbols:
                                continue
                            candidate_score = self._safe_float(scores.get(candidate), 0.0)
                            if candidate_score < threshold:
                                continue
                            replaced_symbols = [
                                candidate if symbol_row == old_symbol else symbol_row
                                for symbol_row in current_symbols
                            ]
                            candidate_corr = self._average_pairwise_correlation(screener, replaced_symbols)
                            if (
                                baseline_corr is not None
                                and candidate_corr is not None
                                and candidate_corr > (baseline_corr + 0.05)
                            ):
                                continue
                            replace_target = old_symbol
                            replacement_symbol = candidate
                            break
                        if replace_target and replacement_symbol:
                            break
                    if replace_target and replacement_symbol:
                        current_symbols = [replacement_symbol if sym == replace_target else sym for sym in current_symbols]
                        quarter_counts[q_key] = replacements_used + 1
                        state["quarter_replacements"] = quarter_counts
                        first_seen.setdefault(replacement_symbol, when.isoformat())
                        replacement_event = {
                            "quarter": q_key,
                            "replaced_symbol": replace_target,
                            "replacement_symbol": replacement_symbol,
                            "replacements_used": int(quarter_counts[q_key]),
                            "replacements_cap": replacements_cap,
                        }
                        state["last_replacement_at"] = when.isoformat()

            selected_state[role_key] = current_symbols
            state["selected_symbols"] = selected_state
            state["last_screened_at"] = when.isoformat()
            state["last_scores"] = {symbol: float(score) for symbol, score in scores.items()}
            state["symbol_first_seen"] = first_seen
            self.save_state(state)

        final_symbols = [
            sym for sym in current_symbols if sym in symbol_to_asset
        ]
        if not final_symbols:
            final_symbols = scored_symbols[: max(1, min(5, len(scored_symbols)))]
        for symbol in final_symbols:
            first_seen.setdefault(symbol, when.isoformat())
        state["symbol_first_seen"] = first_seen
        self.save_state(state)

        final_assets = [symbol_to_asset[sym] for sym in final_symbols if sym in symbol_to_asset]
        tax_report = self._build_tax_report(
            policy=policy,
            holdings_snapshot=holdings_snapshot or [],
            allow_roles=allow_roles,
            state=state,
            now=when,
        )
        return GovernanceResult(
            assets=final_assets,
            symbols=final_symbols,
            report={
                "enabled": True,
                "role": role_key,
                "screen_due": bool(screen_due),
                "replacement_due": bool(replacement_due),
                "allow_list_symbols": enabled_allow_symbols,
                "selected_symbols": final_symbols,
                "replacement_event": replacement_event,
                "rejected_assets": rejected[:100],
                "scores": {
                    sym: round(self._safe_float(scores.get(sym), 0.0), 4)
                    for sym in final_symbols
                },
                "policy": {
                    "screen_interval_days": self._safe_int(policy.get("screen_interval_days"), 30),
                    "replacement_interval_days": self._safe_int(policy.get("replacement_interval_days"), 90),
                    "max_replacements_per_quarter": self._safe_int(
                        policy.get("max_replacements_per_quarter"),
                        1,
                    ),
                    "min_hold_days_for_replacement": self._safe_int(
                        policy.get("min_hold_days_for_replacement"),
                        180,
                    ),
                    "min_replacement_score_delta_pct": round(
                        self._safe_float(policy.get("min_replacement_score_delta_pct"), 20.0),
                        4,
                    ),
                    "min_dollar_volume": round(
                        self._safe_float(policy.get("min_dollar_volume"), 50_000_000.0),
                        2,
                    ),
                },
                "tax_controls": tax_report,
            },
        )

    def allow_list_for_role(self, role: str) -> Dict[str, Dict[str, Any]]:
        policy = self.load_policy()
        return self._allow_map(policy, role=role)
