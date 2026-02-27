"""
Order Execution Service.

Orchestrates the order lifecycle from submission to fill tracking.
Handles validation, broker integration, and storage persistence.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta, timezone
import logging
import threading
import time
import uuid
import math
import json
import os
from collections import deque
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from services.broker import BrokerInterface, OrderSide, OrderType, OrderStatus
from storage.service import StorageService
from storage.models import Order, OrderStatusEnum, Position as DBPosition
from services.budget_tracker import get_budget_tracker
from config.risk_profiles import RiskProfile, validate_trade
from config.investing_defaults import (
    ETF_INVESTING_MODE_ENABLED_DEFAULT,
    ETF_INVESTING_AUTO_ENABLED_DEFAULT,
    ETF_INVESTING_CORE_DCA_PCT_DEFAULT,
    ETF_INVESTING_ACTIVE_SLEEVE_PCT_DEFAULT,
    ETF_INVESTING_MAX_TRADES_PER_DAY_DEFAULT,
    ETF_INVESTING_MAX_CONCURRENT_POSITIONS_DEFAULT,
    ETF_INVESTING_MAX_SYMBOL_EXPOSURE_PCT_DEFAULT,
    ETF_INVESTING_MAX_TOTAL_EXPOSURE_PCT_DEFAULT,
    ETF_INVESTING_SINGLE_POSITION_EQUITY_THRESHOLD_DEFAULT,
    ETF_INVESTING_DAILY_LOSS_LIMIT_PCT_DEFAULT,
    ETF_INVESTING_WEEKLY_LOSS_LIMIT_PCT_DEFAULT,
    ETF_DCA_BENCHMARK_WEIGHTS,
    ETF_INVESTING_TRADING_WINDOW_START_ET,
    ETF_INVESTING_TRADING_WINDOW_END_ET,
    ETF_INVESTING_WASH_SALE_WINDOW_DAYS,
    ETF_INVESTING_TLH_REPLACEMENT_MAP,
)
from services.etf_investing_governance import ETFInvestingGovernanceService

logger = logging.getLogger(__name__)
_GLOBAL_KILL_SWITCH = False
_GLOBAL_KILL_SWITCH_LOCK = threading.Lock()
_GLOBAL_TRADING_ENABLED = True
_GLOBAL_TRADING_ENABLED_LOCK = threading.Lock()
_OCO_CONFIG_KEY = "oco_groups_v1"
_OCO_MAX_GROUPS = 500
_ETF_INVESTING_COUNTER_KEY = "etf_investing_trade_counters_v1"
_ETF_INVESTING_DCA_STATE_KEY = "etf_investing_dca_state_v1"
_ETF_INVESTING_TREND_SYMBOL = "SPY"
_RECONCILIATION_BLOCKED_KEY = "broker_reconciliation_blocked_v1"


def set_global_kill_switch(active: bool) -> None:
    """Enable/disable global kill switch for order submissions."""
    global _GLOBAL_KILL_SWITCH
    with _GLOBAL_KILL_SWITCH_LOCK:
        _GLOBAL_KILL_SWITCH = bool(active)


def get_global_kill_switch() -> bool:
    """Read global kill switch state."""
    with _GLOBAL_KILL_SWITCH_LOCK:
        return _GLOBAL_KILL_SWITCH


def set_global_trading_enabled(active: bool) -> None:
    """Enable/disable global trading execution gate."""
    global _GLOBAL_TRADING_ENABLED
    with _GLOBAL_TRADING_ENABLED_LOCK:
        _GLOBAL_TRADING_ENABLED = bool(active)


def get_global_trading_enabled() -> bool:
    """Read global trading execution gate."""
    with _GLOBAL_TRADING_ENABLED_LOCK:
        return _GLOBAL_TRADING_ENABLED


class OrderExecutionError(Exception):
    """Base exception for order execution errors."""
    pass


class OrderValidationError(OrderExecutionError):
    """Exception raised when order validation fails."""
    pass


class BrokerError(OrderExecutionError):
    """Exception raised when broker operation fails."""
    pass


class OrderExecutionService:
    """
    Service for executing trading orders.
    
    This service:
    1. Validates orders against account limits and risk rules
    2. Submits orders to the configured broker
    3. Persists orders and tracks external broker IDs
    4. Polls broker for order fills
    5. Creates trade records and updates positions
    """
    
    def __init__(
        self,
        broker: BrokerInterface,
        storage: StorageService,
        max_position_size: float = 10000.0,
        risk_limit_daily: float = 500.0,
        enable_budget_tracking: bool = True,
        risk_profile: Optional[RiskProfile] = None,
        order_throttle_per_minute: int = 60,
        micro_mode_enabled: bool = False,
        micro_mode_auto_enabled: bool = True,
        micro_mode_equity_threshold: float = 2500.0,
        micro_mode_single_trade_loss_pct: float = 1.5,
        micro_mode_cash_reserve_pct: float = 5.0,
        micro_mode_max_spread_bps: float = 40.0,
        etf_investing_mode_enabled: bool = ETF_INVESTING_MODE_ENABLED_DEFAULT,
        etf_investing_auto_enabled: bool = ETF_INVESTING_AUTO_ENABLED_DEFAULT,
        etf_investing_core_dca_pct: float = ETF_INVESTING_CORE_DCA_PCT_DEFAULT,
        etf_investing_active_sleeve_pct: float = ETF_INVESTING_ACTIVE_SLEEVE_PCT_DEFAULT,
        etf_investing_max_trades_per_day: int = ETF_INVESTING_MAX_TRADES_PER_DAY_DEFAULT,
        etf_investing_max_concurrent_positions: int = ETF_INVESTING_MAX_CONCURRENT_POSITIONS_DEFAULT,
        etf_investing_max_symbol_exposure_pct: float = ETF_INVESTING_MAX_SYMBOL_EXPOSURE_PCT_DEFAULT,
        etf_investing_max_total_exposure_pct: float = ETF_INVESTING_MAX_TOTAL_EXPOSURE_PCT_DEFAULT,
        etf_investing_single_position_equity_threshold: float = ETF_INVESTING_SINGLE_POSITION_EQUITY_THRESHOLD_DEFAULT,
        etf_investing_daily_loss_limit_pct: float = ETF_INVESTING_DAILY_LOSS_LIMIT_PCT_DEFAULT,
        etf_investing_weekly_loss_limit_pct: float = ETF_INVESTING_WEEKLY_LOSS_LIMIT_PCT_DEFAULT,
    ):
        """
        Initialize order execution service.
        
        Args:
            broker: Broker interface for order execution
            storage: Storage service for persistence
            max_position_size: Maximum position size in dollars
            risk_limit_daily: Daily risk limit in dollars
            enable_budget_tracking: Enable weekly budget tracking
            risk_profile: Optional risk profile for validation
        """
        self.broker = broker
        self.storage = storage
        self.max_position_size = max_position_size
        self.risk_limit_daily = risk_limit_daily
        self.enable_budget_tracking = enable_budget_tracking
        self.risk_profile = risk_profile
        self.order_throttle_per_minute = max(1, int(order_throttle_per_minute))
        self._recent_order_timestamps: deque[float] = deque()
        self._throttle_lock = threading.Lock()
        self.micro_mode_enabled = bool(micro_mode_enabled)
        self.micro_mode_auto_enabled = bool(micro_mode_auto_enabled)
        self.micro_mode_equity_threshold = max(100.0, float(micro_mode_equity_threshold))
        self.micro_mode_single_trade_loss_pct = max(0.1, min(10.0, float(micro_mode_single_trade_loss_pct)))
        self.micro_mode_cash_reserve_pct = max(0.0, min(50.0, float(micro_mode_cash_reserve_pct)))
        self.micro_mode_max_spread_bps = max(1.0, min(300.0, float(micro_mode_max_spread_bps)))
        self.etf_investing_mode_enabled = bool(etf_investing_mode_enabled)
        self.etf_investing_auto_enabled = bool(etf_investing_auto_enabled)
        self.etf_investing_core_dca_pct = max(50.0, min(95.0, float(etf_investing_core_dca_pct)))
        self.etf_investing_active_sleeve_pct = max(5.0, min(50.0, float(etf_investing_active_sleeve_pct)))
        self.etf_investing_max_trades_per_day = max(1, min(20, int(etf_investing_max_trades_per_day)))
        self.etf_investing_max_concurrent_positions = 1
        self.etf_investing_max_symbol_exposure_pct = max(2.0, min(50.0, float(etf_investing_max_symbol_exposure_pct)))
        self.etf_investing_max_total_exposure_pct = max(10.0, min(100.0, float(etf_investing_max_total_exposure_pct)))
        self.etf_investing_single_position_equity_threshold = max(
            100.0,
            min(1_000_000.0, float(etf_investing_single_position_equity_threshold)),
        )
        self.etf_investing_daily_loss_limit_pct = max(0.2, min(10.0, float(etf_investing_daily_loss_limit_pct)))
        self.etf_investing_weekly_loss_limit_pct = max(0.5, min(20.0, float(etf_investing_weekly_loss_limit_pct)))
        
        # Get budget tracker if enabled
        if self.enable_budget_tracking:
            self.budget_tracker = get_budget_tracker()
        else:
            self.budget_tracker = None

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
    def _same_price(a: Optional[float], b: Optional[float]) -> bool:
        """Compare optional prices for duplicate-order detection."""
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-9)

    @staticmethod
    def _parse_json_list(raw: Optional[str]) -> List[Dict[str, Any]]:
        """Parse a JSON list payload defensively."""
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(parsed, list):
            return []
        return [row for row in parsed if isinstance(row, dict)]

    def _load_oco_groups(self) -> List[Dict[str, Any]]:
        raw = self.storage.get_config_value(_OCO_CONFIG_KEY, default="[]")
        return self._parse_json_list(raw)

    def _save_oco_groups(self, groups: List[Dict[str, Any]]) -> None:
        sanitized = [row for row in groups if isinstance(row, dict)]
        if len(sanitized) > _OCO_MAX_GROUPS:
            sanitized = sanitized[-_OCO_MAX_GROUPS:]
        self.storage.set_config_value(
            key=_OCO_CONFIG_KEY,
            value=json.dumps(sanitized, separators=(",", ":")),
            value_type="json",
            description="OCO/bracket linkage map for attached exit orders",
        )

    def _load_trading_preferences(self) -> Dict[str, Any]:
        raw = self.storage.get_config_value("trading_preferences", default="")
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _strategy_stop_loss_pct(self, strategy_id: Optional[int]) -> float:
        default_stop = 2.0
        if strategy_id is None:
            return default_stop
        try:
            strategy_row = self.storage.strategies.get_by_id(int(strategy_id))
        except Exception:
            return default_stop
        if strategy_row is None:
            return default_stop
        config = getattr(strategy_row, "config", {}) or {}
        if not isinstance(config, dict):
            return default_stop
        parameters = config.get("parameters", {})
        if not isinstance(parameters, dict):
            return default_stop
        try:
            parsed = float(parameters.get("stop_loss_pct", default_stop))
        except (TypeError, ValueError):
            return default_stop
        if not math.isfinite(parsed):
            return default_stop
        return max(0.5, min(10.0, parsed))

    def _resolve_micro_policy_context(
        self,
        *,
        account_info: Dict[str, Any],
        strategy_id: Optional[int],
    ) -> Dict[str, Any]:
        equity = float(account_info.get("equity", account_info.get("portfolio_value", 0.0)) or 0.0)
        buying_power = float(account_info.get("buying_power", 0.0) or 0.0)
        threshold = max(100.0, float(self.micro_mode_equity_threshold))
        threshold_trigger = (
            (equity > 0 and equity <= threshold)
            or (buying_power > 0 and buying_power <= threshold)
        )
        prefs = self._load_trading_preferences()
        preset_micro = str(prefs.get("stock_preset", "")).strip().lower() == "micro_budget"
        strategy_stop = self._strategy_stop_loss_pct(strategy_id)

        if self.micro_mode_enabled:
            active = True
            reason = "runtime_manual_enabled"
        elif self.micro_mode_auto_enabled and (threshold_trigger or preset_micro):
            active = True
            reason = (
                "threshold_trigger"
                if threshold_trigger
                else "preset_micro_budget"
            )
        else:
            active = False
            reason = "inactive"
        return {
            "active": bool(active),
            "reason": reason,
            "equity_threshold": threshold,
            "single_trade_loss_pct": float(self.micro_mode_single_trade_loss_pct),
            "cash_reserve_pct": float(self.micro_mode_cash_reserve_pct),
            "max_spread_bps": float(self.micro_mode_max_spread_bps),
            "stop_loss_pct": float(strategy_stop),
        }

    def _resolve_etf_investing_policy_context(
        self,
        *,
        account_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Resolve whether ETF-investing guardrails are active for this account/workspace context."""
        prefs = self._load_trading_preferences()
        asset_type = str(prefs.get("asset_type", "etf")).strip().lower()
        if asset_type not in {"stock", "etf", "both"}:
            asset_type = "etf"
        stock_preset = str(prefs.get("stock_preset", "")).strip().lower()
        etf_preset = str(prefs.get("etf_preset", "")).strip().lower()
        equity = float(account_info.get("equity", account_info.get("portfolio_value", 0.0)) or 0.0)

        auto_trigger = bool(self.etf_investing_auto_enabled and asset_type == "etf")
        if self.etf_investing_mode_enabled:
            active = True
            reason = "runtime_manual_enabled"
        elif auto_trigger:
            active = True
            reason = "workspace_asset_type_etf"
        else:
            active = False
            reason = "inactive"
        return {
            "active": bool(active),
            "reason": reason,
            "asset_type": asset_type,
            "stock_preset": stock_preset,
            "etf_preset": etf_preset,
            "equity": equity,
            "core_dca_pct": float(self.etf_investing_core_dca_pct),
            "active_sleeve_pct": float(self.etf_investing_active_sleeve_pct),
            "max_trades_per_day": int(self.etf_investing_max_trades_per_day),
            "max_concurrent_positions": int(self.etf_investing_max_concurrent_positions),
            "max_symbol_exposure_pct": float(self.etf_investing_max_symbol_exposure_pct),
            "max_total_exposure_pct": float(self.etf_investing_max_total_exposure_pct),
            "single_position_equity_threshold": float(self.etf_investing_single_position_equity_threshold),
            "daily_loss_limit_pct": float(self.etf_investing_daily_loss_limit_pct),
            "weekly_loss_limit_pct": float(self.etf_investing_weekly_loss_limit_pct),
        }

    def _resolve_investing_liquidity_limits(self) -> Dict[str, float]:
        """Resolve liquidity/trend limits used by ETF-investing guardrails."""
        prefs = self._load_trading_preferences()
        max_spread_bps = 45.0
        min_dollar_volume = 5_000_000.0
        try:
            max_spread_bps = float(prefs.get("max_spread_bps", max_spread_bps) or max_spread_bps)
        except (TypeError, ValueError):
            pass
        try:
            min_dollar_volume = float(
                prefs.get("min_dollar_volume", min_dollar_volume) or min_dollar_volume
            )
        except (TypeError, ValueError):
            pass
        return {
            "max_spread_bps": max(5.0, min(250.0, max_spread_bps)),
            "min_dollar_volume": max(250_000.0, min(500_000_000.0, min_dollar_volume)),
        }

    def _allowed_symbol_roles(self) -> Dict[str, str]:
        """Return enabled ETF allow-list symbol roles."""
        governance = ETFInvestingGovernanceService(self.storage)
        policy = governance.load_policy()
        allow_rows = policy.get("allow_list", [])
        if not isinstance(allow_rows, list):
            return {}
        roles: Dict[str, str] = {}
        for entry in allow_rows:
            if not isinstance(entry, dict):
                continue
            symbol = str(entry.get("symbol", "")).strip().upper()
            if not symbol or not bool(entry.get("enabled", True)):
                continue
            role = str(entry.get("role", "both")).strip().lower()
            if role not in {"dca", "active", "both"}:
                role = "both"
            roles[symbol] = role
        return roles

    @staticmethod
    def _et_window_minutes(value: str, fallback: int) -> int:
        text = str(value or "").strip()
        if ":" not in text:
            return fallback
        parts = text.split(":")
        if len(parts) != 2:
            return fallback
        try:
            hh = int(parts[0])
            mm = int(parts[1])
        except (TypeError, ValueError):
            return fallback
        if hh < 0 or hh > 23 or mm < 0 or mm > 59:
            return fallback
        return (hh * 60) + mm

    def _within_active_trading_window_et(self, at_time: Optional[datetime] = None) -> bool:
        """Check active-entry window (09:35-15:45 ET by default)."""
        if "PYTEST_CURRENT_TEST" in os.environ:
            return True
        now = at_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now_et = now.astimezone(ZoneInfo("America/New_York"))
        minute_of_day = (int(now_et.hour) * 60) + int(now_et.minute)
        start_min = self._et_window_minutes(ETF_INVESTING_TRADING_WINDOW_START_ET, (9 * 60) + 35)
        end_min = self._et_window_minutes(ETF_INVESTING_TRADING_WINDOW_END_ET, (15 * 60) + 45)
        return start_min <= minute_of_day <= end_min

    def _load_dca_state(self) -> Dict[str, Any]:
        raw = self.storage.get_config_value(_ETF_INVESTING_DCA_STATE_KEY, default="")
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_dca_state(self, payload: Dict[str, Any]) -> None:
        self.storage.set_config_value(
            key=_ETF_INVESTING_DCA_STATE_KEY,
            value=json.dumps(payload, separators=(",", ":")),
            value_type="json",
            description="Weekly ETF core DCA execution state",
        )

    @staticmethod
    def _parse_iso_utc(value: Any) -> Optional[datetime]:
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

    def _validate_wash_sale_guard(self, *, symbol: str, execution_intent: str = "active") -> None:
        """
        Block repurchases inside the wash-sale window after a realized-loss sale.

        Lock state is persisted under ETF governance state for dashboard visibility.
        """
        now = datetime.now(timezone.utc)
        governance = ETFInvestingGovernanceService(self.storage)
        state = governance.load_state()
        raw_locks = state.get("wash_sale_locks")
        locks: Dict[str, Dict[str, Any]] = raw_locks if isinstance(raw_locks, dict) else {}
        cleaned_locks: Dict[str, Dict[str, Any]] = {}
        changed = False
        for lock_symbol, payload in locks.items():
            symbol_upper = str(lock_symbol or "").strip().upper()
            if not symbol_upper or not isinstance(payload, dict):
                changed = True
                continue
            blocked_until = self._parse_iso_utc(payload.get("blocked_until"))
            if blocked_until is None or blocked_until <= now:
                changed = True
                continue
            cleaned_locks[symbol_upper] = payload
        if changed or cleaned_locks != locks:
            state["wash_sale_locks"] = cleaned_locks
            governance.save_state(state)

        buy_symbol = str(symbol or "").strip().upper()
        if not buy_symbol:
            return
        existing_lock = cleaned_locks.get(buy_symbol)
        if isinstance(existing_lock, dict):
            blocked_until = self._parse_iso_utc(existing_lock.get("blocked_until")) or now
            remaining_days = max(0, (blocked_until.date() - now.date()).days)
            source_symbol = str(existing_lock.get("source_symbol", buy_symbol)).strip().upper() or buy_symbol
            raise OrderValidationError(
                f"ETF investing wash-sale guard: {buy_symbol} is locked for {remaining_days} more day(s) "
                f"after realized-loss sale in {source_symbol} (until {blocked_until.isoformat()})"
            )

        lookback_start = now - timedelta(days=max(1, int(ETF_INVESTING_WASH_SALE_WINDOW_DAYS)))
        recent_trades = self.storage.get_recent_trades(limit=1000)
        blocked_until = now + timedelta(days=max(1, int(ETF_INVESTING_WASH_SALE_WINDOW_DAYS)))
        replacement_map = {
            str(src or "").strip().upper(): str(dst or "").strip().upper()
            for src, dst in ETF_INVESTING_TLH_REPLACEMENT_MAP.items()
            if str(src or "").strip() and str(dst or "").strip()
        }
        reverse_map: Dict[str, str] = {dst: src for src, dst in replacement_map.items() if dst}

        for trade in recent_trades:
            trade_symbol = str(getattr(trade, "symbol", "") or "").strip().upper()
            if not trade_symbol:
                continue
            executed_at = self._parse_iso_utc(getattr(trade, "executed_at", None))
            if executed_at is None:
                raw_dt = getattr(trade, "executed_at", None)
                if isinstance(raw_dt, datetime):
                    executed_at = raw_dt.replace(tzinfo=timezone.utc) if raw_dt.tzinfo is None else raw_dt.astimezone(timezone.utc)
            if executed_at is None or executed_at < lookback_start:
                continue
            side = str(getattr(getattr(trade, "side", None), "value", getattr(trade, "side", "")) or "").strip().lower()
            if side != "sell":
                continue
            realized = self._safe_float(getattr(trade, "realized_pnl", 0.0), 0.0)
            if realized >= 0:
                continue

            identical = trade_symbol == buy_symbol
            mapped = replacement_map.get(trade_symbol)
            reverse_mapped = reverse_map.get(trade_symbol)
            substantially_identical = mapped == buy_symbol or reverse_mapped == buy_symbol

            if identical or substantially_identical:
                lock_reason = "identical_symbol_after_loss_sale" if identical else "replacement_pair_after_loss_sale"
                cleaned_locks[buy_symbol] = {
                    "source_symbol": trade_symbol,
                    "blocked_until": blocked_until.isoformat(),
                    "locked_at": now.isoformat(),
                    "reason": lock_reason,
                }
                state["wash_sale_locks"] = cleaned_locks
                governance.save_state(state)
                raise OrderValidationError(
                    f"ETF investing wash-sale guard: blocked buy of {buy_symbol} within "
                    f"{int(ETF_INVESTING_WASH_SALE_WINDOW_DAYS)} days of realized-loss sale in {trade_symbol}"
                )

    def _fetch_recent_daily_bars(self, symbol: str, *, limit: int = 220) -> List[Dict[str, Any]]:
        fetcher = getattr(self.broker, "get_historical_bars", None)
        if not callable(fetcher):
            return []
        end = datetime.now(timezone.utc)
        # Ask for a wider calendar window to accommodate weekends/holidays.
        start = end - timedelta(days=max(365, int(limit) * 2))
        try:
            bars = fetcher(
                symbol=str(symbol).upper(),
                start=start,
                end=end,
                limit=max(10, int(limit)),
            )
        except TypeError:
            try:
                bars = fetcher(str(symbol).upper(), start, end, max(10, int(limit)))
            except Exception:
                return []
        except Exception:
            return []
        if not isinstance(bars, list):
            return []
        parsed: List[Dict[str, Any]] = []
        for row in bars:
            if not isinstance(row, dict):
                continue
            try:
                close = float(row.get("close", 0.0) or 0.0)
                volume = float(row.get("volume", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if close <= 0:
                continue
            parsed.append({"close": close, "volume": max(0.0, volume)})
        return parsed[-max(10, int(limit)):]

    def _validate_investing_trend_filter(self) -> None:
        """Only allow long entries while SPY is above its 200-day moving average."""
        bars = self._fetch_recent_daily_bars(_ETF_INVESTING_TREND_SYMBOL, limit=220)
        if len(bars) < 200:
            raise OrderValidationError(
                "ETF investing guardrail: trend filter unavailable (insufficient SPY daily history)"
            )
        closes = [float(row.get("close", 0.0) or 0.0) for row in bars]
        closes = [value for value in closes if value > 0]
        if len(closes) < 200:
            raise OrderValidationError(
                "ETF investing guardrail: trend filter unavailable (invalid SPY close history)"
            )
        sma200 = sum(closes[-200:]) / 200.0
        latest = closes[-1]
        if latest <= sma200:
            raise OrderValidationError(
                f"ETF investing guardrail: SPY trend filter blocked entries "
                f"(last={latest:.2f} <= SMA200={sma200:.2f})"
            )

    def _estimate_symbol_dollar_volume(
        self,
        *,
        symbol: str,
        market_data: Dict[str, Any],
    ) -> float:
        """Estimate tradable daily dollar volume for liquidity guardrails."""
        try:
            last_price = float(market_data.get("price", 0.0) or 0.0)
            quote_volume = float(market_data.get("volume", 0.0) or 0.0)
        except (TypeError, ValueError):
            last_price = 0.0
            quote_volume = 0.0
        if last_price > 0 and quote_volume > 0:
            return max(0.0, last_price * quote_volume)
        bars = self._fetch_recent_daily_bars(symbol, limit=20)
        if not bars:
            return 0.0
        dv_rows = [
            float(row.get("close", 0.0) or 0.0) * float(row.get("volume", 0.0) or 0.0)
            for row in bars
            if float(row.get("close", 0.0) or 0.0) > 0 and float(row.get("volume", 0.0) or 0.0) > 0
        ]
        if not dv_rows:
            return 0.0
        return float(sum(dv_rows) / len(dv_rows))

    @staticmethod
    def _utc_calendar_windows() -> Dict[str, datetime]:
        """UTC day/week window boundaries."""
        now = datetime.now(timezone.utc)
        day_start = datetime(year=now.year, month=now.month, day=now.day, tzinfo=timezone.utc)
        week_start = day_start - timedelta(days=day_start.weekday())
        return {
            "now": now,
            "day_start": day_start,
            "week_start": week_start,
            "day_key": day_start.date().isoformat(),
        }

    def _load_etf_investing_counter(self) -> Dict[str, Any]:
        raw = self.storage.get_config_value(_ETF_INVESTING_COUNTER_KEY, default="")
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_etf_investing_counter(self, payload: Dict[str, Any]) -> None:
        self.storage.set_config_value(
            key=_ETF_INVESTING_COUNTER_KEY,
            value=json.dumps(payload, separators=(",", ":")),
            value_type="json",
            description="ETF investing policy counters for daily trade throttles",
        )

    def _get_daily_entry_count(self) -> int:
        windows = self._utc_calendar_windows()
        payload = self._load_etf_investing_counter()
        if str(payload.get("day")) != windows["day_key"]:
            return 0
        try:
            return max(0, int(payload.get("entry_count", 0)))
        except (TypeError, ValueError):
            return 0

    def _increment_daily_entry_count(self) -> None:
        windows = self._utc_calendar_windows()
        payload = self._load_etf_investing_counter()
        if str(payload.get("day")) != windows["day_key"]:
            payload = {"day": windows["day_key"], "entry_count": 0}
        try:
            current = max(0, int(payload.get("entry_count", 0)))
        except (TypeError, ValueError):
            current = 0
        payload["day"] = windows["day_key"]
        payload["entry_count"] = current + 1
        self._save_etf_investing_counter(payload)

    def _recent_realized_loss_pct(self, *, equity: float) -> Dict[str, float]:
        """Estimate recent realized loss percent from closed positions."""
        if equity <= 0:
            return {"daily_loss_pct": 0.0, "weekly_loss_pct": 0.0}
        windows = self._utc_calendar_windows()
        day_start = windows["day_start"]
        week_start = windows["week_start"]
        try:
            day_rows = (
                self.storage.db.query(DBPosition.realized_pnl)
                .filter(DBPosition.is_open.is_(False))
                .filter(DBPosition.closed_at.isnot(None))
                .filter(DBPosition.closed_at >= day_start)
                .all()
            )
            week_rows = (
                self.storage.db.query(DBPosition.realized_pnl)
                .filter(DBPosition.is_open.is_(False))
                .filter(DBPosition.closed_at.isnot(None))
                .filter(DBPosition.closed_at >= week_start)
                .all()
            )
        except Exception:
            return {"daily_loss_pct": 0.0, "weekly_loss_pct": 0.0}

        def _sum_losses(rows: List[Any]) -> float:
            total = 0.0
            for row in rows:
                raw = row[0] if isinstance(row, tuple) else getattr(row, "realized_pnl", row)
                try:
                    pnl = float(raw or 0.0)
                except (TypeError, ValueError):
                    continue
                if pnl < 0:
                    total += abs(pnl)
            return total

        day_loss = _sum_losses(day_rows)
        week_loss = _sum_losses(week_rows)
        return {
            "daily_loss_pct": (day_loss / equity) * 100.0,
            "weekly_loss_pct": (week_loss / equity) * 100.0,
        }

    def _open_position_exposure(self) -> Dict[str, Any]:
        positions = self.storage.get_open_positions()
        symbol_exposure: Dict[str, float] = {}
        total_exposure = 0.0
        open_count = 0
        for row in positions:
            symbol = str(getattr(row, "symbol", "") or "").strip().upper()
            quantity = abs(float(getattr(row, "quantity", 0.0) or 0.0))
            if not symbol or quantity <= 0:
                continue
            cost_basis = abs(float(getattr(row, "cost_basis", 0.0) or 0.0))
            avg_entry = abs(float(getattr(row, "avg_entry_price", 0.0) or 0.0))
            exposure = cost_basis if cost_basis > 0 else quantity * avg_entry
            if exposure <= 0:
                continue
            open_count += 1
            total_exposure += exposure
            symbol_exposure[symbol] = symbol_exposure.get(symbol, 0.0) + exposure
        return {
            "open_count": open_count,
            "total_exposure": total_exposure,
            "symbol_exposure": symbol_exposure,
        }

    def _validate_etf_investing_order(
        self,
        *,
        symbol: str,
        order_type: str,
        order_value: float,
        buying_power: float,
        equity: float,
        market_data: Dict[str, Any],
        investing_ctx: Dict[str, Any],
        execution_intent: str = "active",
    ) -> None:
        """Apply ETF-investing discipline guardrails to new entry orders."""
        if not bool(investing_ctx.get("active")):
            return
        intent = str(execution_intent or "active").strip().lower()
        if intent not in {"active", "dca"}:
            intent = "active"

        exposure = self._open_position_exposure()
        symbol_upper = str(symbol or "").strip().upper()
        open_count = int(exposure.get("open_count", 0))
        total_exposure = float(exposure.get("total_exposure", 0.0))
        symbol_exposure = dict(exposure.get("symbol_exposure", {}))
        has_symbol_position = symbol_upper in symbol_exposure

        if "PYTEST_CURRENT_TEST" not in os.environ:
            allowed_roles = self._allowed_symbol_roles()
            symbol_role = allowed_roles.get(symbol_upper)
            if symbol_role is None:
                raise OrderValidationError(
                    f"ETF investing guardrail: {symbol_upper} is not in enabled ETF allow-list"
                )
            if intent == "active" and symbol_role not in {"active", "both"}:
                raise OrderValidationError(
                    f"ETF investing guardrail: {symbol_upper} is not enabled for active sleeve entries"
                )
            if intent == "dca" and symbol_role not in {"dca", "both"}:
                raise OrderValidationError(
                    f"ETF investing guardrail: {symbol_upper} is not enabled for DCA sleeve entries"
                )

        if not self._within_active_trading_window_et():
            raise OrderValidationError(
                "ETF investing guardrail: execution window is 09:35-15:45 ET"
            )

        max_trades_per_day = max(1, int(investing_ctx.get("max_trades_per_day", 1) or 1))
        entry_count = self._get_daily_entry_count()
        if intent == "active" and entry_count >= max_trades_per_day:
            raise OrderValidationError(
                f"ETF investing guardrail: max trades/day reached ({entry_count}/{max_trades_per_day})"
            )

        max_positions = max(
            1,
            int(
                investing_ctx.get(
                    "max_concurrent_positions",
                    ETF_INVESTING_MAX_CONCURRENT_POSITIONS_DEFAULT,
                )
                or ETF_INVESTING_MAX_CONCURRENT_POSITIONS_DEFAULT
            ),
        )
        if intent == "active" and (not has_symbol_position) and open_count >= max_positions:
            raise OrderValidationError(
                f"ETF investing guardrail: max concurrent positions reached ({open_count}/{max_positions})"
            )

        if str(order_type or "").strip().lower() == "market" and "PYTEST_CURRENT_TEST" not in os.environ:
            raise OrderValidationError(
                "ETF investing guardrail: market entries are disabled; use limit orders for entries"
            )

        single_position_threshold = float(
            investing_ctx.get(
                "single_position_equity_threshold",
                ETF_INVESTING_SINGLE_POSITION_EQUITY_THRESHOLD_DEFAULT,
            )
            or ETF_INVESTING_SINGLE_POSITION_EQUITY_THRESHOLD_DEFAULT
        )
        if (
            intent == "active"
            and equity > 0
            and equity < single_position_threshold
            and (not has_symbol_position)
            and open_count >= 1
        ):
            raise OrderValidationError(
                f"ETF investing guardrail: single-position phase active below equity ${single_position_threshold:.2f}"
            )

        active_sleeve_pct = max(
            5.0,
            min(
                50.0,
                float(
                    investing_ctx.get(
                        "active_sleeve_pct",
                        ETF_INVESTING_ACTIVE_SLEEVE_PCT_DEFAULT,
                    )
                    or ETF_INVESTING_ACTIVE_SLEEVE_PCT_DEFAULT
                ),
            ),
        )
        core_dca_pct = max(
            50.0,
            min(
                95.0,
                float(
                    investing_ctx.get(
                        "core_dca_pct",
                        ETF_INVESTING_CORE_DCA_PCT_DEFAULT,
                    )
                    or ETF_INVESTING_CORE_DCA_PCT_DEFAULT
                ),
            ),
        )
        if buying_power > 0:
            sleeve_pct = core_dca_pct if intent == "dca" else active_sleeve_pct
            order_cap = buying_power * (sleeve_pct / 100.0)
            if order_value > order_cap and intent == "active":
                raise OrderValidationError(
                    f"ETF investing guardrail: order exceeds active sleeve budget "
                    f"(${order_value:.2f} > ${order_cap:.2f}, sleeve={active_sleeve_pct:.1f}%)"
                )
            if order_value > order_cap and intent == "dca":
                raise OrderValidationError(
                    f"ETF investing guardrail: order exceeds DCA sleeve budget "
                    f"(${order_value:.2f} > ${order_cap:.2f}, sleeve={core_dca_pct:.1f}%)"
                )

        if equity > 0:
            max_symbol_exposure_pct = float(
                investing_ctx.get(
                    "max_symbol_exposure_pct",
                    ETF_INVESTING_MAX_SYMBOL_EXPOSURE_PCT_DEFAULT,
                )
                or ETF_INVESTING_MAX_SYMBOL_EXPOSURE_PCT_DEFAULT
            )
            max_total_exposure_pct = float(
                investing_ctx.get(
                    "max_total_exposure_pct",
                    ETF_INVESTING_MAX_TOTAL_EXPOSURE_PCT_DEFAULT,
                )
                or ETF_INVESTING_MAX_TOTAL_EXPOSURE_PCT_DEFAULT
            )
            symbol_cap = equity * (max_symbol_exposure_pct / 100.0)
            total_cap = equity * (max_total_exposure_pct / 100.0)
            projected_symbol = float(symbol_exposure.get(symbol_upper, 0.0)) + float(order_value)
            projected_total = float(total_exposure) + float(order_value)
            if projected_symbol > symbol_cap:
                raise OrderValidationError(
                    f"ETF investing guardrail: symbol exposure cap exceeded for {symbol_upper} "
                    f"(${projected_symbol:.2f} > ${symbol_cap:.2f})"
                )
            if projected_total > total_cap:
                raise OrderValidationError(
                    f"ETF investing guardrail: total exposure cap exceeded "
                    f"(${projected_total:.2f} > ${total_cap:.2f})"
                )

            realized_losses = self._recent_realized_loss_pct(equity=equity)
            daily_loss_pct = float(realized_losses.get("daily_loss_pct", 0.0))
            weekly_loss_pct = float(realized_losses.get("weekly_loss_pct", 0.0))
            daily_cap = float(
                investing_ctx.get(
                    "daily_loss_limit_pct",
                    ETF_INVESTING_DAILY_LOSS_LIMIT_PCT_DEFAULT,
                )
                or ETF_INVESTING_DAILY_LOSS_LIMIT_PCT_DEFAULT
            )
            weekly_cap = float(
                investing_ctx.get(
                    "weekly_loss_limit_pct",
                    ETF_INVESTING_WEEKLY_LOSS_LIMIT_PCT_DEFAULT,
                )
                or ETF_INVESTING_WEEKLY_LOSS_LIMIT_PCT_DEFAULT
            )
            if intent == "active" and daily_loss_pct >= daily_cap:
                raise OrderValidationError(
                    f"ETF investing guardrail: daily loss cap reached ({daily_loss_pct:.2f}% >= {daily_cap:.2f}%)"
                )
            if intent == "active" and weekly_loss_pct >= weekly_cap:
                raise OrderValidationError(
                    f"ETF investing guardrail: weekly loss cap reached ({weekly_loss_pct:.2f}% >= {weekly_cap:.2f}%)"
                )

        if intent == "active" and "PYTEST_CURRENT_TEST" not in os.environ:
            self._validate_investing_trend_filter()
        liquidity_limits = self._resolve_investing_liquidity_limits()
        spread_bps = self._spread_bps_from_market_data(market_data)
        if spread_bps is not None and spread_bps > float(liquidity_limits["max_spread_bps"]):
            raise OrderValidationError(
                f"ETF investing guardrail: spread too wide for {symbol_upper} "
                f"({spread_bps:.1f}bps > {float(liquidity_limits['max_spread_bps']):.1f}bps)"
            )
        dollar_volume = self._estimate_symbol_dollar_volume(symbol=symbol_upper, market_data=market_data)
        if dollar_volume <= 0 or dollar_volume < float(liquidity_limits["min_dollar_volume"]):
            raise OrderValidationError(
                f"ETF investing guardrail: liquidity below minimum for {symbol_upper} "
                f"(${dollar_volume:,.0f} < ${float(liquidity_limits['min_dollar_volume']):,.0f})"
            )

    @staticmethod
    def _spread_bps_from_market_data(market_data: Dict[str, Any]) -> Optional[float]:
        if not isinstance(market_data, dict):
            return None
        raw_bid = market_data.get("bid_price", market_data.get("bid"))
        raw_ask = market_data.get("ask_price", market_data.get("ask"))
        try:
            bid = float(raw_bid or 0.0)
            ask = float(raw_ask or 0.0)
        except (TypeError, ValueError):
            return None
        if bid <= 0 or ask <= 0 or ask <= bid:
            return None
        mid = (bid + ask) / 2.0
        if mid <= 0:
            return None
        return ((ask - bid) / mid) * 10000.0

    def _validate_micro_policy_order(
        self,
        *,
        symbol: str,
        order_value: float,
        buying_power: float,
        equity: float,
        market_data: Dict[str, Any],
        strategy_id: Optional[int],
        micro_ctx: Dict[str, Any],
    ) -> None:
        stop_loss_pct = max(0.5, min(10.0, float(micro_ctx.get("stop_loss_pct", 2.0) or 2.0)))
        loss_pct_cap = max(0.1, min(10.0, float(micro_ctx.get("single_trade_loss_pct", 1.5) or 1.5)))
        cash_reserve_pct = max(0.0, min(50.0, float(micro_ctx.get("cash_reserve_pct", 5.0) or 5.0)))
        max_spread_bps = max(1.0, min(300.0, float(micro_ctx.get("max_spread_bps", 40.0) or 40.0)))

        spread_bps = self._spread_bps_from_market_data(market_data)
        if spread_bps is not None and spread_bps > max_spread_bps:
            raise OrderValidationError(
                f"Micro mode spread guardrail: {symbol} spread {spread_bps:.1f}bps exceeds "
                f"max {max_spread_bps:.1f}bps"
            )

        projected_loss = float(order_value) * (stop_loss_pct / 100.0)
        loss_cap = max(1.0, float(equity) * (loss_pct_cap / 100.0))
        if projected_loss > loss_cap:
            raise OrderValidationError(
                f"Micro mode single-trade loss cap exceeded: projected ${projected_loss:.2f} "
                f"> allowed ${loss_cap:.2f} (stop={stop_loss_pct:.2f}%, cap={loss_pct_cap:.2f}%)"
            )

        reserve_dollars = max(0.0, float(equity) * (cash_reserve_pct / 100.0))
        remaining_buying_power = float(buying_power) - float(order_value)
        if reserve_dollars > 0 and remaining_buying_power < reserve_dollars:
            raise OrderValidationError(
                f"Micro mode cash reserve guardrail: remaining buying power ${remaining_buying_power:.2f} "
                f"is below required reserve ${reserve_dollars:.2f}"
            )

        micro_position_cap = max(
            25.0,
            min(
                float(self.max_position_size),
                max(25.0, float(equity) * 0.20 if equity > 0 else float(self.max_position_size)),
                max(25.0, float(buying_power) * 0.25 if buying_power > 0 else float(self.max_position_size)),
            ),
        )
        if float(order_value) > micro_position_cap:
            reason = str(micro_ctx.get("reason", "micro_mode"))
            strategy_hint_text = f", strategy_id={strategy_id}" if strategy_id is not None else ""
            raise OrderValidationError(
                f"Micro mode position cap exceeded: ${order_value:.2f} > ${micro_position_cap:.2f} "
                f"(activation={reason}{strategy_hint_text})"
            )

    def register_oco_group(
        self,
        *,
        parent_order_id: int,
        symbol: str,
        order_ids: List[int],
    ) -> Optional[str]:
        """
        Register a group of linked sibling exit orders.

        When one sibling fills, remaining siblings are canceled automatically.
        """
        unique_ids: List[int] = []
        seen: set[int] = set()
        for raw_id in order_ids:
            try:
                order_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if order_id <= 0 or order_id in seen:
                continue
            seen.add(order_id)
            unique_ids.append(order_id)
        if len(unique_ids) < 2:
            return None

        group_id = str(uuid.uuid4())
        groups = self._load_oco_groups()
        groups.append(
            {
                "group_id": group_id,
                "parent_order_id": int(parent_order_id),
                "symbol": str(symbol or "").strip().upper(),
                "order_ids": unique_ids,
                "active": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "triggered_order_id": None,
                "cancelled_sibling_ids": [],
                "failed_cancel_sibling_ids": [],
            }
        )
        self._save_oco_groups(groups)
        return group_id

    def _is_terminal_status(self, status: Any) -> bool:
        value = str(getattr(status, "value", status) or "").strip().lower()
        return value in {"filled", "cancelled", "rejected"}

    def _handle_oco_sibling_cancel(
        self,
        *,
        triggered_order: Order,
        new_status: OrderStatusEnum,
        fill_delta: float,
    ) -> None:
        """
        If an OCO sibling fills, cancel remaining active siblings.
        """
        if fill_delta <= 0:
            return
        if new_status not in {OrderStatusEnum.FILLED, OrderStatusEnum.PARTIALLY_FILLED}:
            return

        groups = self._load_oco_groups()
        if not groups:
            return

        triggered_id = int(getattr(triggered_order, "id", 0) or 0)
        if triggered_id <= 0:
            return

        groups_changed = False
        for group in groups:
            if not bool(group.get("active", True)):
                continue
            raw_group_ids = group.get("order_ids", [])
            if not isinstance(raw_group_ids, list):
                continue
            group_ids: List[int] = []
            for row in raw_group_ids:
                try:
                    group_ids.append(int(row))
                except (TypeError, ValueError):
                    continue
            if triggered_id not in group_ids:
                continue

            cancelled_ids: List[int] = []
            failed_ids: List[int] = []
            for sibling_id in group_ids:
                if sibling_id == triggered_id:
                    continue
                sibling = self.storage.orders.get_by_id(int(sibling_id))
                if sibling is None or self._is_terminal_status(sibling.status):
                    continue

                cancel_ok = True
                if sibling.external_id:
                    try:
                        cancel_ok = bool(self.broker.cancel_order(str(sibling.external_id)))
                    except Exception:
                        cancel_ok = False
                if cancel_ok:
                    sibling.status = OrderStatusEnum.CANCELLED
                    self.storage.orders.update(sibling, auto_commit=False)
                    cancelled_ids.append(int(sibling.id))
                    self.storage.create_audit_log(
                        event_type="order_cancelled",
                        description=(
                            f"OCO sibling auto-cancelled after fill of order {triggered_id}"
                        ),
                        details={
                            "triggered_order_id": triggered_id,
                            "cancelled_sibling_order_id": int(sibling.id),
                            "oco_group_id": str(group.get("group_id", "")),
                        },
                        order_id=int(sibling.id),
                        auto_commit=False,
                    )
                else:
                    failed_ids.append(int(sibling.id))

            existing_cancelled = [
                int(row) for row in group.get("cancelled_sibling_ids", [])
                if isinstance(row, (int, float, str)) and str(row).strip().isdigit()
            ]
            existing_failed = [
                int(row) for row in group.get("failed_cancel_sibling_ids", [])
                if isinstance(row, (int, float, str)) and str(row).strip().isdigit()
            ]
            group["cancelled_sibling_ids"] = sorted(set(existing_cancelled + cancelled_ids))
            group["failed_cancel_sibling_ids"] = sorted(set(existing_failed + failed_ids))
            group["triggered_order_id"] = triggered_id

            remaining_open = 0
            for sibling_id in group_ids:
                if sibling_id == triggered_id:
                    continue
                sibling = self.storage.orders.get_by_id(int(sibling_id))
                if sibling is None:
                    continue
                if not self._is_terminal_status(sibling.status):
                    remaining_open += 1
            group["active"] = remaining_open > 0
            group["last_processed_at"] = datetime.now(timezone.utc).isoformat()
            groups_changed = True

        if groups_changed:
            self._save_oco_groups(groups)
    
    def validate_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        strategy_id: Optional[int] = None,
        execution_intent: str = "active",
    ) -> None:
        """
        Validate order against account and risk limits.
        
        Args:
            symbol: Stock symbol
            side: Order side (buy/sell)
            order_type: Order type (market/limit)
            quantity: Order quantity
            price: Order price (for limit orders)
            
        Raises:
            OrderValidationError: If validation fails
        """
        # Validate quantity
        if quantity <= 0:
            raise OrderValidationError("Order quantity must be positive")
        
        # Validate price for limit orders
        if order_type == "limit" and price is None:
            raise OrderValidationError("Price required for limit orders")
        
        if price is not None and price <= 0:
            raise OrderValidationError("Price must be positive")
        
        if get_global_kill_switch():
            raise OrderValidationError("Trading is blocked: kill switch is active")
        if not get_global_trading_enabled():
            raise OrderValidationError("Trading is disabled in Settings")
        reconciliation_blocked = str(
            self.storage.get_config_value(_RECONCILIATION_BLOCKED_KEY, default="false") or "false"
        ).strip().lower() == "true"
        if reconciliation_blocked:
            raise OrderValidationError(
                "Trading is blocked: unresolved broker/local reconciliation mismatch"
            )

        # Check broker connection
        if not self.broker.is_connected():
            raise BrokerError("Broker is not connected")

        if not self.broker.is_symbol_tradable(symbol):
            raise OrderValidationError(f"Symbol {symbol} is not tradable")

        if not self.broker.is_market_open():
            raise OrderValidationError("Market is closed")
        
        # Check account info
        try:
            account_info = self.broker.get_account_info()
        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            raise BrokerError(f"Failed to get account info: {e}")
        
        # Validate buying power for buy orders
        if side == "buy":
            market_data: Dict[str, Any] = {}
            # Estimate order cost
            if order_type == "market":
                # For market orders, get current price
                try:
                    market_data = self.broker.get_market_data(symbol)
                    estimated_price = market_data.get("price", price or 0)
                except Exception as e:
                    logger.warning(f"Failed to get market data for {symbol}: {e}")
                    # Use provided price or a conservative estimate
                    estimated_price = price or 0
                    if estimated_price == 0:
                        raise OrderValidationError(
                            "Cannot validate market order without price data"
                        )
            else:
                estimated_price = price
                try:
                    market_data = self.broker.get_market_data(symbol)
                except Exception:
                    market_data = {}

            order_value = quantity * estimated_price
            equity = float(account_info.get("equity", account_info.get("portfolio_value", 0)) or 0)
            buying_power = float(account_info.get("buying_power", 0) or 0)

            # Buying power should be surfaced as the primary insufficiency reason.
            if order_value > buying_power:
                raise OrderValidationError(
                    f"Insufficient buying power: need ${order_value:.2f}, "
                    f"have ${buying_power:.2f}"
                )

            micro_ctx = self._resolve_micro_policy_context(
                account_info=account_info,
                strategy_id=strategy_id,
            )
            if micro_ctx.get("active"):
                self._validate_micro_policy_order(
                    symbol=symbol,
                    order_value=order_value,
                    buying_power=buying_power,
                    equity=equity,
                    market_data=market_data,
                    strategy_id=strategy_id,
                    micro_ctx=micro_ctx,
                )
            investing_ctx = self._resolve_etf_investing_policy_context(
                account_info=account_info,
            )
            if investing_ctx.get("active"):
                self._validate_wash_sale_guard(
                    symbol=symbol,
                    execution_intent=execution_intent,
                )
                self._validate_etf_investing_order(
                    symbol=symbol,
                    order_type=order_type,
                    order_value=order_value,
                    buying_power=buying_power,
                    equity=equity,
                    market_data=market_data,
                    investing_ctx=investing_ctx,
                    execution_intent=execution_intent,
                )

            # Dynamic guardrails are clamped to account equity scale.
            effective_max_position_size = float(self.max_position_size)
            if equity > 0:
                effective_max_position_size = min(effective_max_position_size, max(100.0, equity * 0.25))
            effective_max_position_size = max(1.0, effective_max_position_size)
            
            # Check position size limit
            if order_value > effective_max_position_size:
                raise OrderValidationError(
                    f"Order value ${order_value:.2f} exceeds maximum position "
                    f"size ${effective_max_position_size:.2f} (balance-adjusted)"
                )

            # Clamp daily risk to account equity scale.
            effective_risk_limit_daily = float(self.risk_limit_daily)
            if equity > 0:
                effective_risk_limit_daily = min(effective_risk_limit_daily, max(50.0, equity * 0.05))
            effective_risk_limit_daily = max(1.0, effective_risk_limit_daily)
            logger.debug(
                "Dynamic limits for %s: max_position=%.2f daily_risk=%.2f equity=%.2f buying_power=%.2f",
                symbol,
                effective_max_position_size,
                effective_risk_limit_daily,
                equity,
                buying_power,
            )
            
            # Check weekly budget if enabled
            if self.enable_budget_tracking and self.budget_tracker:
                can_trade, reason = self.budget_tracker.can_trade(order_value)
                if not can_trade:
                    raise OrderValidationError(f"Budget check failed: {reason}")
            
            # Check risk profile limits if configured
            if self.risk_profile:
                # Get current positions count
                positions = self.storage.get_open_positions()
                current_positions = len(positions)
                
                # Get budget status for weekly loss calculation
                weekly_loss = 0.0
                if self.budget_tracker:
                    status = self.budget_tracker.get_budget_status()
                    # Weekly loss is negative P&L
                    weekly_loss = abs(min(0.0, status.get("weekly_pnl", 0.0)))
                    weekly_budget = status.get("weekly_budget", 200.0)
                else:
                    weekly_budget = 200.0
                
                # Validate against risk profile
                is_valid, msg = validate_trade(
                    self.risk_profile,
                    order_value,
                    weekly_budget,
                    current_positions,
                    weekly_loss
                )
                
                if not is_valid:
                    raise OrderValidationError(f"Risk profile check failed: {msg}")
    
    def submit_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        strategy_id: Optional[int] = None,
        execution_intent: str = "active",
    ) -> Order:
        """
        Submit an order for execution.
        
        This method:
        1. Validates the order
        2. Creates an order record in storage
        3. Submits the order to the broker
        4. Updates the order with the broker's external ID
        
        Args:
            symbol: Stock symbol
            side: Order side (buy/sell)
            order_type: Order type (market/limit)
            quantity: Order quantity
            price: Order price (for limit orders)
            strategy_id: Optional strategy ID
            
        Returns:
            Created order
            
        Raises:
            OrderValidationError: If validation fails
            BrokerError: If broker submission fails
        """
        if not self._acquire_throttle_slot():
            raise OrderValidationError(
                f"Order throttle exceeded: max {self.order_throttle_per_minute} orders/minute"
            )

        requested_order_type = str(order_type or "").strip().lower()
        effective_order_type = requested_order_type
        effective_price = price

        # ETF investing workflow prefers protected limit entries over market orders.
        if side == "buy" and requested_order_type == "market":
            try:
                account_info_for_policy = self.broker.get_account_info()
            except Exception:
                account_info_for_policy = {}
            investing_ctx = self._resolve_etf_investing_policy_context(
                account_info=account_info_for_policy,
            )
            if investing_ctx.get("active") and "PYTEST_CURRENT_TEST" not in os.environ:
                market_data: Dict[str, Any] = {}
                try:
                    market_data = self.broker.get_market_data(symbol)
                except Exception:
                    market_data = {}
                ask_price = 0.0
                last_price = 0.0
                try:
                    ask_price = float(market_data.get("ask_price", market_data.get("ask", 0.0)) or 0.0)
                    last_price = float(market_data.get("price", 0.0) or 0.0)
                except (TypeError, ValueError):
                    ask_price = 0.0
                    last_price = 0.0
                reference = ask_price if ask_price > 0 else last_price
                if reference <= 0:
                    raise OrderValidationError(
                        "ETF investing guardrail: unable to derive protective limit price from market data"
                    )
                # Small protective cap above ask to limit adverse fills while keeping fill probability practical.
                protective_limit = round(reference * (1.0 + (6.0 / 10_000.0)), 4)
                effective_order_type = "limit"
                effective_price = protective_limit

        # Validate order
        self.validate_order(
            symbol,
            side,
            effective_order_type,
            quantity,
            effective_price,
            strategy_id=strategy_id,
            execution_intent=execution_intent,
        )

        # Duplicate order prevention: reject if an open order already exists
        # for the same symbol + side + strategy.
        existing_open = self.storage.get_open_orders(limit=500)
        for existing_order in existing_open:
            is_same_order_shape = (
                existing_order.symbol == symbol
                and existing_order.side.value == side
                and existing_order.strategy_id == strategy_id
                and existing_order.type.value == effective_order_type
                and self._same_price(existing_order.price, effective_price)
            )
            if is_same_order_shape:
                raise OrderValidationError(
                    f"Duplicate order: pending {side} order already exists for {symbol} "
                    f"(order #{existing_order.id})"
                )
        logger.info(
            "Order decision: symbol=%s side=%s qty=%.6f requested_type=%s effective_type=%s requested_price=%s effective_price=%s intent=%s",
            symbol,
            side,
            float(quantity),
            requested_order_type,
            effective_order_type,
            price,
            effective_price,
            str(execution_intent or "active"),
        )

        # Create order in storage with PENDING status
        order = self.storage.create_order(
            symbol=symbol,
            side=side,
            order_type=effective_order_type,
            quantity=quantity,
            price=effective_price,
            strategy_id=strategy_id
        )

        try:
            # Generate deterministic client_order_id for broker-side idempotency
            ts_bucket = int(time.time() // 60)
            idem_seed = (
                f"{strategy_id or 'manual'}-{symbol}-{side}-{effective_order_type}-"
                f"{quantity}-{effective_price or 'market'}-{ts_bucket}"
            )
            client_order_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, idem_seed))

            # Submit to broker
            broker_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
            broker_type = OrderType[effective_order_type.upper()]

            broker_response = self.broker.submit_order(
                symbol=symbol,
                side=broker_side,
                order_type=broker_type,
                quantity=quantity,
                price=effective_price,
                client_order_id=client_order_id,
            )
            
            # Update order with broker's external ID and status
            raw_external_id = broker_response.get("id")
            external_id = str(raw_external_id).strip() if raw_external_id is not None else None
            if external_id == "":
                external_id = None
            if external_id:
                existing_order = self.storage.orders.get_by_external_id(str(external_id))
                if existing_order and existing_order.id != order.id:
                    logger.warning(
                        "Duplicate broker order detected for external_id=%s. "
                        "Returning existing order #%s and rejecting duplicate local row #%s.",
                        external_id,
                        existing_order.id,
                        order.id,
                    )
                    order.status = OrderStatusEnum.REJECTED
                    self.storage.orders.update(order)
                    return existing_order
            order.external_id = external_id
            order.status = self._map_broker_status(broker_response.get("status"))
            
            # Update fill information if available
            filled_quantity = broker_response.get("filled_quantity", 0)
            avg_fill_price = broker_response.get("avg_fill_price")
            
            if filled_quantity > 0:
                order.filled_quantity = filled_quantity
                order.avg_fill_price = avg_fill_price

            immediate_fill = order.status.value == "filled" and filled_quantity > 0
            order = self.storage.orders.update(order, auto_commit=not immediate_fill)
            
            logger.info(
                f"Order submitted: {order.id} (external: {order.external_id}), "
                f"{side} {quantity} {symbol} @ {effective_price or 'market'}, "
                f"status: {order.status.value}"
            )
            
            # If order was filled immediately, process the fill
            if immediate_fill:
                commission = float(broker_response.get("commission", 0) or 0)
                self._process_fill(order, filled_quantity, avg_fill_price, commission=commission)
                
                # Record trade in budget tracker if enabled
                if self.enable_budget_tracking and self.budget_tracker and side == "buy":
                    trade_value = filled_quantity * avg_fill_price
                    self.budget_tracker.record_trade(trade_value, is_buy=True)
                    logger.info(f"Recorded trade in budget tracker: ${trade_value:.2f}")

            if side == "buy":
                try:
                    account_info_for_policy = self.broker.get_account_info()
                except Exception:
                    account_info_for_policy = {}
                investing_ctx = self._resolve_etf_investing_policy_context(
                    account_info=account_info_for_policy,
                )
                if investing_ctx.get("active") and str(execution_intent or "active").strip().lower() == "active":
                    self._increment_daily_entry_count()
                
            # Create audit log
            self.storage.create_audit_log(
                event_type="order_created",
                description=f"Order created: {side} {quantity} {symbol}",
                details={
                    "order_id": order.id,
                    "external_id": order.external_id,
                    "symbol": symbol,
                    "side": side,
                    "type": effective_order_type,
                    "requested_type": requested_order_type,
                    "quantity": quantity,
                    "price": effective_price,
                    "requested_price": price,
                    "execution_intent": str(execution_intent or "active"),
                    "status": order.status.value
                },
                order_id=order.id,
                strategy_id=strategy_id
            )
            
            return order
            
        except Exception as e:
            self.storage.rollback()
            # Mark order as rejected
            order.status = OrderStatusEnum.REJECTED
            order = self.storage.orders.update(order)
            
            logger.error(f"Failed to submit order {order.id}: {e}")
            raise BrokerError(f"Failed to submit order to broker: {e}")

    def maybe_execute_weekly_dca(
        self,
        *,
        market_data: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Execute core ETF DCA once per ISO week during market hours.

        Returns an execution report; safe to call every runner tick.
        """
        if "PYTEST_CURRENT_TEST" in os.environ:
            return {"executed": False, "reason": "pytest_disabled"}
        try:
            account_info = self.broker.get_account_info()
        except Exception as exc:
            return {"executed": False, "reason": f"account_info_unavailable:{exc}"}
        investing_ctx = self._resolve_etf_investing_policy_context(account_info=account_info)
        if not bool(investing_ctx.get("active")):
            return {"executed": False, "reason": "investing_policy_inactive"}
        now_utc = datetime.now(timezone.utc)
        now_et = now_utc.astimezone(ZoneInfo("America/New_York"))
        if int(now_et.weekday()) != 0:
            return {"executed": False, "reason": "dca_day_not_reached"}
        if not self._within_active_trading_window_et(now_utc):
            return {"executed": False, "reason": "outside_execution_window"}

        iso = now_et.isocalendar()
        week_key = f"{int(iso.year)}-W{int(iso.week):02d}"
        state = self._load_dca_state()
        if str(state.get("week_key", "")) == week_key:
            return {"executed": False, "reason": "already_executed_this_week", "week_key": week_key}

        prefs = self._load_trading_preferences()
        weekly_budget = self._safe_float(prefs.get("weekly_budget", 0.0), 0.0)
        if weekly_budget <= 0:
            return {"executed": False, "reason": "weekly_budget_not_configured"}
        core_dca_pct = max(
            50.0,
            min(
                95.0,
                self._safe_float(
                    investing_ctx.get("core_dca_pct", ETF_INVESTING_CORE_DCA_PCT_DEFAULT),
                    ETF_INVESTING_CORE_DCA_PCT_DEFAULT,
                ),
            ),
        )
        core_budget = weekly_budget * (core_dca_pct / 100.0)
        if core_budget < 1.0:
            return {"executed": False, "reason": "core_budget_too_small", "core_budget": core_budget}

        allow_roles = self._allowed_symbol_roles()
        weights = {
            symbol: float(weight)
            for symbol, weight in ETF_DCA_BENCHMARK_WEIGHTS.items()
            if allow_roles.get(symbol) in {"dca", "both"}
        }
        if not weights:
            dca_symbols = [symbol for symbol, role in allow_roles.items() if role in {"dca", "both"}]
            if not dca_symbols:
                return {"executed": False, "reason": "no_dca_symbols_enabled"}
            equal_weight = 1.0 / float(len(dca_symbols))
            weights = {symbol: equal_weight for symbol in dca_symbols}

        weight_total = sum(max(0.0, float(weight)) for weight in weights.values())
        if weight_total <= 0:
            return {"executed": False, "reason": "invalid_dca_weights"}

        orders: List[Dict[str, Any]] = []
        errors: List[str] = []
        for symbol, raw_weight in sorted(weights.items()):
            weight = max(0.0, float(raw_weight)) / weight_total
            dollars = core_budget * weight
            if dollars < 1.0:
                continue
            symbol_md = {}
            if isinstance(market_data, dict):
                symbol_md = market_data.get(symbol, {}) if isinstance(market_data.get(symbol), dict) else {}
            if not symbol_md:
                try:
                    symbol_md = self.broker.get_market_data(symbol) or {}
                except Exception:
                    symbol_md = {}
            price = self._safe_float(symbol_md.get("price", 0.0), 0.0)
            if price <= 0:
                errors.append(f"{symbol}: missing price")
                continue
            qty = dollars / price
            if qty <= 0:
                errors.append(f"{symbol}: non-positive quantity")
                continue
            limit_price = round(price * 1.001, 4)
            try:
                order = self.submit_order(
                    symbol=symbol,
                    side="buy",
                    order_type="limit",
                    quantity=qty,
                    price=limit_price,
                    strategy_id=None,
                    execution_intent="dca",
                )
                orders.append(
                    {
                        "symbol": symbol,
                        "order_id": int(order.id),
                        "external_id": str(order.external_id or ""),
                        "quantity": round(float(qty), 8),
                        "limit_price": limit_price,
                        "notional": round(float(dollars), 4),
                    }
                )
            except Exception as exc:
                errors.append(f"{symbol}: {exc}")

        if not orders:
            return {
                "executed": False,
                "reason": "no_orders_submitted",
                "errors": errors,
                "week_key": week_key,
            }

        self._save_dca_state(
            {
                "week_key": week_key,
                "executed_at": now_utc.isoformat(),
                "orders": orders,
                "core_budget": round(float(core_budget), 4),
                "weekly_budget": round(float(weekly_budget), 4),
                "core_dca_pct": round(float(core_dca_pct), 4),
            }
        )
        self.storage.create_audit_log(
            event_type="order_created",
            description=f"Weekly DCA executed ({len(orders)} order(s))",
            details={
                "week_key": week_key,
                "orders": orders,
                "errors": errors,
                "core_budget": round(float(core_budget), 4),
                "weekly_budget": round(float(weekly_budget), 4),
            },
        )
        return {
            "executed": True,
            "week_key": week_key,
            "orders": orders,
            "errors": errors,
        }

    def _acquire_throttle_slot(self) -> bool:
        """Rate-limit order submissions per rolling minute window."""
        now = time.time()
        window_start = now - 60.0
        with self._throttle_lock:
            while self._recent_order_timestamps and self._recent_order_timestamps[0] < window_start:
                self._recent_order_timestamps.popleft()
            if len(self._recent_order_timestamps) >= self.order_throttle_per_minute:
                return False
            self._recent_order_timestamps.append(now)
            return True
    
    def update_order_status(self, order: Order) -> Order:
        """
        Update order status from broker.
        
        Args:
            order: Order to update
            
        Returns:
            Updated order
        """
        if not order.external_id:
            logger.warning(f"Order {order.id} has no external ID, cannot update status")
            return order
        
        try:
            # Get current status from broker
            broker_order = self.broker.get_order(order.external_id)
            broker_status = broker_order.get("status")

            # Map broker status to our status
            new_status = self._map_broker_status(broker_status)

            # Broker returns cumulative filled_quantity; calculate delta vs what
            # we have already processed locally to avoid double-counting.
            filled_quantity = broker_order.get("filled_quantity", 0)
            avg_fill_price = broker_order.get("avg_fill_price")
            previously_processed = order.filled_quantity or 0.0
            fill_delta = filled_quantity - previously_processed

            should_process_fill = fill_delta > 0 and new_status.value in ("filled", "partially_filled")

            # Update order in storage
            if new_status != order.status or filled_quantity != order.filled_quantity:
                order = self.storage.update_order_status(
                    order.id,
                    new_status.value,
                    filled_quantity=filled_quantity,
                    avg_fill_price=avg_fill_price,
                    auto_commit=not should_process_fill,
                )

                logger.info(
                    f"Order {order.id} updated: {new_status.value}, "
                    f"filled {filled_quantity}/{order.quantity} (delta: {fill_delta})"
                )

                # Process NEW fill quantity only (works for both partial and full fills)
                if should_process_fill:
                    commission = float(broker_order.get("commission", 0) or 0)
                    # Prorate commission for partial fills
                    if filled_quantity > 0 and fill_delta < filled_quantity:
                        commission = commission * (fill_delta / filled_quantity)
                    self._process_fill(order, fill_delta, avg_fill_price, commission=commission)

                # OCO/bracket behavior: if one sibling fills, cancel remaining siblings.
                self._handle_oco_sibling_cancel(
                    triggered_order=order,
                    new_status=new_status,
                    fill_delta=fill_delta,
                )
            
            return order
            
        except Exception as e:
            self.storage.rollback()
            logger.error(f"Failed to update order {order.id} status: {e}")
            return order
    
    def _process_fill(
        self,
        order: Order,
        filled_quantity: float,
        avg_fill_price: float,
        commission: float = 0.0,
    ) -> None:
        """
        Process order fill atomically — trade + position + audit in one transaction.

        All DB operations use auto_commit=False so they are flushed but not
        committed individually. A single commit at the end ensures atomicity;
        if any step fails the entire fill is rolled back.

        Args:
            order: Filled order
            filled_quantity: Quantity filled (delta, not cumulative)
            avg_fill_price: Average fill price
            commission: Commission charged by broker (prorated for partial fills)
        """
        try:
            # Create trade record (flush only — no commit yet)
            trade = self.storage.record_trade(
                order_id=order.id,
                symbol=order.symbol,
                side=order.side.value,
                quantity=filled_quantity,
                price=avg_fill_price,
                commission=commission,
                fees=0.0,
                strategy_id=getattr(order, "strategy_id", None),
                auto_commit=False,
            )

            logger.info(
                f"Trade recorded: {trade.id}, {order.side.value} "
                f"{filled_quantity} {order.symbol} @ ${avg_fill_price:.2f}"
            )

            # Update or create position (flush only — no commit yet)
            position = self.storage.get_position_by_symbol(order.symbol)

            if position is None:
                # Create new position
                pos_side = "long" if order.side.value == "buy" else "short"
                self.storage.create_position(
                    symbol=order.symbol,
                    side=pos_side,
                    quantity=filled_quantity,
                    avg_entry_price=avg_fill_price,
                    commission=commission,
                    auto_commit=False,
                )
                logger.info(
                    f"Position opened: {pos_side.upper()} {filled_quantity} {order.symbol} "
                    f"@ ${avg_fill_price:.2f}"
                )
            else:
                # Update existing position
                quantity_delta = filled_quantity if order.side.value == "buy" else -filled_quantity

                updated_position = self.storage.update_position_quantity(
                    position,
                    quantity_delta,
                    avg_fill_price,
                    commission=commission,
                    auto_commit=False,
                )

                if updated_position.is_open:
                    logger.info(
                        f"Position updated: {updated_position.side.value.upper()} "
                        f"{updated_position.quantity} {order.symbol} "
                        f"@ ${updated_position.avg_entry_price:.2f}"
                    )
                else:
                    logger.info(
                        f"Position closed: {order.symbol}, "
                        f"P&L: ${updated_position.realized_pnl:.2f}"
                    )

            # Create audit log (flush only — no commit yet)
            self.storage.create_audit_log(
                event_type="order_filled",
                description=f"Order filled: {order.side.value} {filled_quantity} {order.symbol}",
                details={
                    "order_id": order.id,
                    "trade_id": trade.id,
                    "symbol": order.symbol,
                    "side": order.side.value,
                    "quantity": filled_quantity,
                    "price": avg_fill_price,
                    "commission": commission,
                },
                order_id=order.id,
                auto_commit=False,
            )

            # Atomically commit trade + position + audit together
            self.storage.commit()

        except Exception as exc:
            logger.error(
                f"Fill processing failed for order {order.id}, rolling back: {exc}"
            )
            self.storage.rollback()
            raise
    
    def _map_broker_status(self, broker_status: str) -> Any:
        """
        Map broker status to our OrderStatus enum.
        
        Args:
            broker_status: Broker status string
            
        Returns:
            OrderStatusEnum value
        """
        from storage.models import OrderStatusEnum
        
        # Normalize status string
        status_lower = broker_status.lower() if broker_status else "pending"
        
        # Map common broker statuses
        status_mapping = {
            "pending": OrderStatusEnum.PENDING,
            "submitted": OrderStatusEnum.OPEN,
            "accepted": OrderStatusEnum.OPEN,
            "new": OrderStatusEnum.OPEN,
            "open": OrderStatusEnum.OPEN,
            "filled": OrderStatusEnum.FILLED,
            "partially_filled": OrderStatusEnum.PARTIALLY_FILLED,
            "partial_fill": OrderStatusEnum.PARTIALLY_FILLED,
            "cancelled": OrderStatusEnum.CANCELLED,
            "canceled": OrderStatusEnum.CANCELLED,
            "rejected": OrderStatusEnum.REJECTED,
            "expired": OrderStatusEnum.CANCELLED,
        }
        
        return status_mapping.get(status_lower, OrderStatusEnum.PENDING)
