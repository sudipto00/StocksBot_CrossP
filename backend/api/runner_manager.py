"""
Strategy Runner Manager - Singleton instance for managing strategy runner lifecycle.
"""
from typing import Optional, Dict, Any
import logging
import threading
import time
import math
import re
from sqlalchemy.orm import Session

from engine.strategy_runner import StrategyRunner, StrategyStatus
from engine.strategies import MetricsDrivenStrategy
from services.broker import PaperBroker
from services.order_execution import OrderExecutionService
from services.budget_tracker import get_budget_tracker
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
)
from storage.database import SessionLocal
from storage.service import StorageService
import json

logger = logging.getLogger(__name__)


class RunnerManager:
    """
    Singleton manager for the strategy runner.
    
    Ensures only one runner instance exists and provides
    thread-safe start/stop operations.
    """
    
    _instance: Optional['RunnerManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize the runner manager (only once)."""
        if self._initialized:
            return

        self.runner: Optional[StrategyRunner] = None
        self._initialized = True

        # ── Watchdog state ──────────────────────────────────────────
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_stop = threading.Event()
        self._crash_detected_at: Optional[str] = None
        self._auto_restart_count: int = 0
        self._auto_restart_timestamps: list[float] = []

    @staticmethod
    def _runner_thread_alive(runner: StrategyRunner) -> bool:
        """Best-effort runner thread liveness check."""
        try:
            return bool(runner.is_thread_alive())
        except Exception:
            return False

    def _normalize_stale_runner_state(self, runner: StrategyRunner) -> None:
        """
        Normalize stale active status when thread is not alive.
        Prevents UI/start controls from being stuck in RUNNING/SLEEPING forever.
        """
        alive = self._runner_thread_alive(runner)
        if alive:
            return
        if runner.status not in (StrategyStatus.RUNNING, StrategyStatus.SLEEPING, StrategyStatus.PAUSED):
            return
        runner.status = StrategyStatus.STOPPED
        runner.sleeping = False
        runner.sleep_since = None
        runner.next_market_open_at = None
        runner.market_session_open = None
        if not str(runner.last_poll_error or "").strip():
            runner.last_poll_error = "Runner thread inactive; status reset to stopped"
        try:
            runner._persist_sleep_state()  # noqa: SLF001
            runner._persist_runtime_state()  # noqa: SLF001
        except Exception:
            pass

    def _start_watchdog(self) -> None:
        """Start the background watchdog thread that monitors runner liveness."""
        self._watchdog_stop.clear()
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            return  # Already running

        def _watchdog_loop() -> None:
            logger.info("Runner watchdog started")
            while not self._watchdog_stop.wait(timeout=30.0):
                with self._lock:
                    if self.runner is None:
                        continue
                    if self.runner.status not in (
                        StrategyStatus.RUNNING,
                        StrategyStatus.SLEEPING,
                        StrategyStatus.PAUSED,
                    ):
                        continue
                    if self._runner_thread_alive(self.runner):
                        continue

                    # Runner thread has died while status indicates it should be active
                    from datetime import datetime, timezone

                    crash_time = datetime.now(timezone.utc).isoformat()
                    last_error = str(self.runner.last_poll_error or "unknown cause")
                    logger.warning(
                        "Watchdog detected runner crash at %s (last error: %s)",
                        crash_time,
                        last_error[:200],
                    )
                    self._crash_detected_at = crash_time
                    self._normalize_stale_runner_state(self.runner)

                    # Auto-restart logic: max 2 restarts per hour
                    now = time.monotonic()
                    self._auto_restart_timestamps = [
                        ts for ts in self._auto_restart_timestamps if now - ts < 3600
                    ]
                    if len(self._auto_restart_timestamps) < 2:
                        logger.info("Watchdog attempting auto-restart of runner")
                        try:
                            session = SessionLocal()
                            try:
                                storage = StorageService(session)
                                storage.create_audit_log(
                                    event_type="runner_started",
                                    description="Runner auto-restarted by watchdog after crash",
                                    details={"crash_time": crash_time, "last_error": last_error[:200]},
                                )
                            finally:
                                session.close()
                            # Reset runner so start_runner() rebuilds it cleanly
                            self.runner = None
                        except Exception:
                            logger.exception("Watchdog: failed to log auto-restart audit event")
                        self._auto_restart_count += 1
                        self._auto_restart_timestamps.append(now)
                    else:
                        logger.warning(
                            "Watchdog: auto-restart limit reached (2/hour). Manual restart required."
                        )
            logger.info("Runner watchdog stopped")

        self._watchdog_thread = threading.Thread(
            target=_watchdog_loop,
            name="runner-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

    def _stop_watchdog(self) -> None:
        """Signal the watchdog thread to stop."""
        self._watchdog_stop.set()
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=5.0)
            self._watchdog_thread = None

    @staticmethod
    def _load_persisted_runtime_state() -> Dict[str, Any]:
        """Read last persisted runner runtime state for status continuity."""
        session = SessionLocal()
        try:
            storage = StorageService(session)
            entry = storage.config.get_by_key("runner_runtime_state")
            if not entry or not entry.value:
                return {}
            raw = json.loads(entry.value)
            if isinstance(raw, dict):
                return raw
            return {}
        except Exception:
            return {}
        finally:
            session.close()
    
    def get_or_create_runner(
        self,
        db: Optional[Session] = None,
        broker: Optional[Any] = None,
        max_position_size: float = 10000.0,
        risk_limit_daily: float = 500.0,
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
        tick_interval: float = 60.0,
        streaming_enabled: bool = False,
    ) -> StrategyRunner:
        """
        Get the runner instance, creating it if necessary.
        
        Returns:
            StrategyRunner instance
        """
        if self.runner is None:
            # Use provided broker (paper/live/alpaca), fallback to local paper broker.
            active_broker = broker or PaperBroker(starting_balance=100000.0)
            
            # Create dedicated storage session for runner lifetime.
            # Do not reuse request-scoped sessions.
            db_session = SessionLocal()
            storage = StorageService(db_session)
            execution_service = OrderExecutionService(
                broker=active_broker,
                storage=storage,
                max_position_size=max_position_size,
                risk_limit_daily=risk_limit_daily,
                enable_budget_tracking=True,
                micro_mode_enabled=micro_mode_enabled,
                micro_mode_auto_enabled=micro_mode_auto_enabled,
                micro_mode_equity_threshold=micro_mode_equity_threshold,
                micro_mode_single_trade_loss_pct=micro_mode_single_trade_loss_pct,
                micro_mode_cash_reserve_pct=micro_mode_cash_reserve_pct,
                micro_mode_max_spread_bps=micro_mode_max_spread_bps,
                etf_investing_mode_enabled=etf_investing_mode_enabled,
                etf_investing_auto_enabled=etf_investing_auto_enabled,
                etf_investing_core_dca_pct=etf_investing_core_dca_pct,
                etf_investing_active_sleeve_pct=etf_investing_active_sleeve_pct,
                etf_investing_max_trades_per_day=etf_investing_max_trades_per_day,
                etf_investing_max_concurrent_positions=etf_investing_max_concurrent_positions,
                etf_investing_max_symbol_exposure_pct=etf_investing_max_symbol_exposure_pct,
                etf_investing_max_total_exposure_pct=etf_investing_max_total_exposure_pct,
                etf_investing_single_position_equity_threshold=etf_investing_single_position_equity_threshold,
                etf_investing_daily_loss_limit_pct=etf_investing_daily_loss_limit_pct,
                etf_investing_weekly_loss_limit_pct=etf_investing_weekly_loss_limit_pct,
            )
            
            # Create runner
            self.runner = StrategyRunner(
                broker=active_broker,
                storage_service=storage,
                tick_interval=tick_interval,
                order_execution_service=execution_service,
                streaming_enabled=streaming_enabled,
            )
        else:
            self.runner.tick_interval = tick_interval
            self.runner.streaming_enabled = streaming_enabled
            if self.runner.order_execution_service:
                self.runner.order_execution_service.max_position_size = max_position_size
                self.runner.order_execution_service.risk_limit_daily = risk_limit_daily
                self.runner.order_execution_service.micro_mode_enabled = bool(micro_mode_enabled)
                self.runner.order_execution_service.micro_mode_auto_enabled = bool(micro_mode_auto_enabled)
                self.runner.order_execution_service.micro_mode_equity_threshold = float(micro_mode_equity_threshold)
                self.runner.order_execution_service.micro_mode_single_trade_loss_pct = float(micro_mode_single_trade_loss_pct)
                self.runner.order_execution_service.micro_mode_cash_reserve_pct = float(micro_mode_cash_reserve_pct)
                self.runner.order_execution_service.micro_mode_max_spread_bps = float(micro_mode_max_spread_bps)
                self.runner.order_execution_service.etf_investing_mode_enabled = bool(etf_investing_mode_enabled)
                self.runner.order_execution_service.etf_investing_auto_enabled = bool(etf_investing_auto_enabled)
                self.runner.order_execution_service.etf_investing_core_dca_pct = float(etf_investing_core_dca_pct)
                self.runner.order_execution_service.etf_investing_active_sleeve_pct = float(etf_investing_active_sleeve_pct)
                self.runner.order_execution_service.etf_investing_max_trades_per_day = int(etf_investing_max_trades_per_day)
                self.runner.order_execution_service.etf_investing_max_concurrent_positions = int(etf_investing_max_concurrent_positions)
                self.runner.order_execution_service.etf_investing_max_symbol_exposure_pct = float(etf_investing_max_symbol_exposure_pct)
                self.runner.order_execution_service.etf_investing_max_total_exposure_pct = float(etf_investing_max_total_exposure_pct)
                self.runner.order_execution_service.etf_investing_single_position_equity_threshold = float(etf_investing_single_position_equity_threshold)
                self.runner.order_execution_service.etf_investing_daily_loss_limit_pct = float(etf_investing_daily_loss_limit_pct)
                self.runner.order_execution_service.etf_investing_weekly_loss_limit_pct = float(etf_investing_weekly_loss_limit_pct)
        
        return self.runner
    
    def start_runner(
        self,
        db: Optional[Session] = None,
        broker: Optional[Any] = None,
        max_position_size: float = 10000.0,
        risk_limit_daily: float = 500.0,
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
        tick_interval: float = 60.0,
        streaming_enabled: bool = False,
        alpaca_client: Optional[Dict[str, str]] = None,
        require_real_data: bool = False,
        symbol_universe_override: Optional[list[str]] = None,
        symbol_universe_overrides: Optional[Dict[str, list[str]]] = None,
    ) -> Dict[str, Any]:
        """
        Start the strategy runner.
        
        Idempotent - safe to call multiple times.
        
        Returns:
            Dict with status and message
        """
        with self._lock:
            # Recreate stopped runner when broker implementation changes.
            if self.runner is not None and self.runner.status == StrategyStatus.STOPPED and broker is not None:
                if self.runner.broker.__class__ != broker.__class__:
                    self.runner = None
            runner = self.get_or_create_runner(
                db=db,
                broker=broker,
                max_position_size=max_position_size,
                risk_limit_daily=risk_limit_daily,
                micro_mode_enabled=micro_mode_enabled,
                micro_mode_auto_enabled=micro_mode_auto_enabled,
                micro_mode_equity_threshold=micro_mode_equity_threshold,
                micro_mode_single_trade_loss_pct=micro_mode_single_trade_loss_pct,
                micro_mode_cash_reserve_pct=micro_mode_cash_reserve_pct,
                micro_mode_max_spread_bps=micro_mode_max_spread_bps,
                etf_investing_mode_enabled=etf_investing_mode_enabled,
                etf_investing_auto_enabled=etf_investing_auto_enabled,
                etf_investing_core_dca_pct=etf_investing_core_dca_pct,
                etf_investing_active_sleeve_pct=etf_investing_active_sleeve_pct,
                etf_investing_max_trades_per_day=etf_investing_max_trades_per_day,
                etf_investing_max_concurrent_positions=etf_investing_max_concurrent_positions,
                etf_investing_max_symbol_exposure_pct=etf_investing_max_symbol_exposure_pct,
                etf_investing_max_total_exposure_pct=etf_investing_max_total_exposure_pct,
                etf_investing_single_position_equity_threshold=etf_investing_single_position_equity_threshold,
                etf_investing_daily_loss_limit_pct=etf_investing_daily_loss_limit_pct,
                etf_investing_weekly_loss_limit_pct=etf_investing_weekly_loss_limit_pct,
                tick_interval=tick_interval,
                streaming_enabled=streaming_enabled,
            )
            
            self._normalize_stale_runner_state(runner)
            if runner.status in (StrategyStatus.RUNNING, StrategyStatus.SLEEPING) and self._runner_thread_alive(runner):
                return {
                    "success": False,
                    "message": f"Runner already active ({runner.status.value})",
                    "status": runner.status.value
                }

            # Always rebuild loaded strategies from DB for deterministic behavior.
            runner.strategies = {}
            
            # Load active strategies from database
            owns_session = db is None
            session = db or SessionLocal()
            try:
                storage = StorageService(session)
                active_strategies = storage.get_active_strategies()
                strategy_count = len(active_strategies)
                prefs_raw = storage.config.get_by_key("trading_preferences")
                prefs = {}
                if prefs_raw and prefs_raw.value:
                    try:
                        prefs = json.loads(prefs_raw.value)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        prefs = {}
                
                if strategy_count == 0:
                    return {
                        "success": False,
                        "message": "No active strategies to run",
                        "status": runner.status.value
                    }

                # Load active DB strategies into runner before start using metrics-driven logic.
                skipped_invalid = []
                allowed_params = set(
                    self._strategy_param_defaults_from_prefs(
                        {"asset_type": "etf", "etf_preset": "balanced"}
                    ).keys()
                )
                account_info: Dict[str, Any] = {}
                try:
                    account_info = runner.broker.get_account_info()
                except (RuntimeError, ValueError, TypeError):
                    account_info = {}
                account_equity = self._safe_float(account_info.get("equity", account_info.get("portfolio_value", 0.0)), 0.0)
                account_buying_power = self._safe_float(account_info.get("buying_power", 0.0), 0.0)
                weekly_budget = self._safe_float(prefs.get("weekly_budget", 50.0), 50.0)
                budget_tracker = get_budget_tracker(weekly_budget)
                budget_tracker.set_weekly_budget(weekly_budget)
                remaining_weekly_budget = self._safe_float(
                    budget_tracker.get_budget_status().get("remaining_budget", weekly_budget),
                    weekly_budget,
                )
                existing_positions = storage.get_open_positions()
                existing_position_count = len(existing_positions)
                override_symbols = self._normalize_symbols(symbol_universe_override or [])
                per_strategy_override_symbols: Dict[str, list[str]] = {}
                for strategy_id, symbols in (symbol_universe_overrides or {}).items():
                    normalized_override = self._normalize_symbols(symbols or [])
                    if normalized_override:
                        per_strategy_override_symbols[str(strategy_id)] = normalized_override
                for db_strategy in active_strategies:
                    config = db_strategy.config or {}
                    raw_symbols = config.get("symbols", [])
                    strategy_specific_override = per_strategy_override_symbols.get(str(db_strategy.id), [])
                    workspace_override_active = bool(strategy_specific_override or override_symbols)
                    symbols = (
                        list(strategy_specific_override)
                        if strategy_specific_override
                        else (list(override_symbols) if override_symbols else self._normalize_symbols(
                            raw_symbols if isinstance(raw_symbols, list) else []
                        ))
                    )
                    if not symbols:
                        skipped_invalid.append(db_strategy.name)
                        continue
                    saved_params = config.get("parameters", {}) if isinstance(config.get("parameters"), dict) else {}
                    baseline_params = config.get("baseline_parameters", {}) if isinstance(config.get("baseline_parameters"), dict) else {}
                    preset_defaults = self._strategy_param_defaults_from_config(config, prefs)
                    raw_param_source = baseline_params if workspace_override_active else saved_params
                    validated_params = self._validated_strategy_params(raw_param_source, allowed_params)
                    merged_params = {**preset_defaults, **validated_params}
                    dynamic_position_size = self._dynamic_position_size(
                        requested_position_size=float(merged_params.get("position_size", 1000.0)),
                        symbol_count=max(1, len(symbols)),
                        existing_position_count=existing_position_count,
                        remaining_weekly_budget=remaining_weekly_budget,
                        buying_power=account_buying_power,
                        equity=account_equity,
                        risk_per_trade_pct=float(merged_params.get("risk_per_trade", 1.0)),
                        stop_loss_pct=float(merged_params.get("stop_loss_pct", 2.0)),
                    )
                    try:
                        strategy = MetricsDrivenStrategy({
                            "name": db_strategy.name,
                            "strategy_id": db_strategy.id,
                            "symbols": symbols,
                            "position_size": dynamic_position_size,
                            "risk_per_trade": float(merged_params.get("risk_per_trade", 1.0)),
                            "stop_loss_pct": float(merged_params.get("stop_loss_pct", 2.0)),
                            "take_profit_pct": float(merged_params.get("take_profit_pct", 5.0)),
                            "trailing_stop_pct": float(merged_params.get("trailing_stop_pct", 2.5)),
                            "atr_stop_mult": float(merged_params.get("atr_stop_mult", 2.0)),
                            "zscore_entry_threshold": float(merged_params.get("zscore_entry_threshold", -1.2)),
                            "dip_buy_threshold_pct": float(merged_params.get("dip_buy_threshold_pct", 1.5)),
                            "pullback_rsi_threshold": float(merged_params.get("pullback_rsi_threshold", 45.0)),
                            "pullback_sma_tolerance": float(merged_params.get("pullback_sma_tolerance", 1.01)),
                            "max_hold_days": int(merged_params.get("max_hold_days", 10)),
                            "dca_tranches": int(merged_params.get("dca_tranches", 1)),
                            "alpaca_client": alpaca_client,
                            "require_real_data": require_real_data,
                        })
                    except RuntimeError:
                        skipped_invalid.append(f"{db_strategy.name} (market data unavailable)")
                        continue
                    runner.load_strategy(strategy)

                if not runner.strategies:
                    return {
                        "success": False,
                        "message": "No valid active strategies to run. Ensure each active strategy has at least one valid symbol.",
                        "status": runner.status.value,
                    }
                
                # Create audit log
                storage.create_audit_log(
                    event_type='runner_started',
                    description=f'Strategy runner started with {strategy_count} strategies',
                    details={
                        'strategy_count': strategy_count,
                        'loaded_count': len(runner.strategies),
                        'skipped_invalid': skipped_invalid,
                        'account_equity': account_equity,
                        'account_buying_power': account_buying_power,
                        'remaining_weekly_budget': remaining_weekly_budget,
                        'existing_position_count': existing_position_count,
                        'workspace_universe_override': bool(override_symbols or per_strategy_override_symbols),
                        'workspace_override_symbol_count': (
                            len(override_symbols)
                            if override_symbols
                            else sum(len(symbols) for symbols in per_strategy_override_symbols.values())
                        ),
                        'workspace_override_strategy_count': (
                            1
                            if override_symbols
                            else len(per_strategy_override_symbols)
                        ),
                    }
                )
            finally:
                if owns_session:
                    session.close()
            
            # Start runner
            success = runner.start()

            if success:
                self._crash_detected_at = None
                self._start_watchdog()
                override_message = ""
                if symbol_universe_override:
                    override_message = f" using workspace universe override ({len(symbol_universe_override)} symbols)"
                elif symbol_universe_overrides:
                    override_strategy_count = len([1 for symbols in symbol_universe_overrides.values() if symbols])
                    override_symbol_count = sum(len(symbols) for symbols in symbol_universe_overrides.values() if symbols)
                    override_message = (
                        f" using workspace universe override on {override_strategy_count} strategy(ies)"
                        f" ({override_symbol_count} symbols)"
                    )
                return {
                    "success": True,
                    "message": (
                        f"Runner started with {strategy_count} strategies"
                        + override_message
                    ),
                    "status": runner.status.value
                }
            else:
                return {
                    "success": False,
                    "message": "Failed to start runner",
                    "status": runner.status.value
                }

    def _strategy_param_defaults_from_prefs(self, prefs: Dict[str, Any]) -> Dict[str, float]:
        """Preset-based defaults used when strategy-specific parameters are not set."""
        asset_type = str(prefs.get("asset_type", "etf"))
        etf_preset = str(prefs.get("etf_preset", "balanced"))

        etf_defaults = {
            "conservative": {
                "position_size": 500,
                "risk_per_trade": 0.5,
                "stop_loss_pct": 3.0,
                "take_profit_pct": 6.0,
                "trailing_stop_pct": 3.0,
                "atr_stop_mult": 1.6,
                "zscore_entry_threshold": -0.7,
                "dip_buy_threshold_pct": 0.8,
                "pullback_rsi_threshold": 45.0,
                "pullback_sma_tolerance": 1.01,
                "max_hold_days": 20,
                "dca_tranches": 1,
                "max_consecutive_losses": 2,
                "max_drawdown_pct": 12.0,
            },
            "balanced": {
                "position_size": 800,
                "risk_per_trade": 0.5,
                "stop_loss_pct": 3.0,
                "take_profit_pct": 6.5,
                "trailing_stop_pct": 3.0,
                "atr_stop_mult": 1.8,
                "zscore_entry_threshold": -0.8,
                "dip_buy_threshold_pct": 1.0,
                "pullback_rsi_threshold": 45.0,
                "pullback_sma_tolerance": 1.01,
                "max_hold_days": 18,
                "dca_tranches": 1,
                "max_consecutive_losses": 2,
                "max_drawdown_pct": 12.0,
            },
            "aggressive": {
                "position_size": 1000,
                "risk_per_trade": 0.5,
                "stop_loss_pct": 3.0,
                "take_profit_pct": 8.0,
                "trailing_stop_pct": 3.5,
                "atr_stop_mult": 2.0,
                "zscore_entry_threshold": -1.0,
                "dip_buy_threshold_pct": 1.2,
                "pullback_rsi_threshold": 45.0,
                "pullback_sma_tolerance": 1.01,
                "max_hold_days": 15,
                "dca_tranches": 1,
                "max_consecutive_losses": 2,
                "max_drawdown_pct": 14.0,
            },
        }
        # Pivot behavior: use ETF presets as canonical defaults for runner/backtests.
        # Any non-ETF asset_type falls back to ETF balanced so legacy rows remain executable.
        if asset_type == "etf":
            return etf_defaults.get(etf_preset, etf_defaults["balanced"])
        return etf_defaults["balanced"]

    def _strategy_param_defaults_from_config(
        self,
        strategy_config: Dict[str, Any],
        fallback_prefs: Dict[str, Any],
    ) -> Dict[str, float]:
        """Resolve per-strategy defaults, preferring persisted baseline profile."""
        profile = strategy_config.get("baseline_profile", {})
        if isinstance(profile, dict):
            asset_type = str(profile.get("asset_type", "")).strip().lower()
            etf_preset = str(profile.get("etf_preset", "")).strip().lower()
            if asset_type in {"stock", "etf"}:
                return self._strategy_param_defaults_from_prefs(
                    {
                        "asset_type": "etf" if asset_type != "etf" else asset_type,
                        "etf_preset": etf_preset or "balanced",
                    }
                )
        return self._strategy_param_defaults_from_prefs(fallback_prefs)

    def _validated_strategy_params(self, raw_params: Any, allowed_params: set[str]) -> Dict[str, float]:
        """Parse finite numeric strategy params and discard unknown keys."""
        source = raw_params if isinstance(raw_params, dict) else {}
        validated_params: Dict[str, float] = {}
        for key, value in source.items():
            if key not in allowed_params:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric):
                validated_params[key] = numeric
        return validated_params

    def _normalize_symbols(self, raw_symbols: list[Any]) -> list[str]:
        """Normalize symbol list and keep only valid unique symbols."""
        normalized: list[str] = []
        seen = set()
        for raw_symbol in raw_symbols:
            symbol = str(raw_symbol).strip().upper()
            if not symbol:
                continue
            if not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", symbol):
                continue
            if symbol in seen:
                continue
            normalized.append(symbol)
            seen.add(symbol)
        return normalized

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        """Best-effort finite float conversion."""
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(parsed):
            return default
        return parsed

    def _dynamic_position_size(
        self,
        requested_position_size: float,
        symbol_count: int,
        existing_position_count: int,
        remaining_weekly_budget: float,
        buying_power: float,
        equity: float,
        risk_per_trade_pct: float = 1.0,
        stop_loss_pct: float = 2.0,
    ) -> float:
        """
        Compute portfolio-adaptive per-trade position size.

        Uses proper risk-based sizing: position = (equity × risk%) / stop_loss%.
        The goal is to keep strategy defaults intact while preventing oversizing
        relative to available buying power, equity, and remaining weekly budget.
        """
        position_size = max(25.0, self._safe_float(requested_position_size, 1000.0))
        planned_slots = max(1, int(symbol_count))
        active_slots = max(0, int(existing_position_count))
        slots_denominator = max(1, planned_slots + min(active_slots, planned_slots))

        caps: list[float] = [position_size]
        if remaining_weekly_budget > 0:
            caps.append(max(50.0, remaining_weekly_budget / slots_denominator))
        if buying_power > 0:
            caps.append(max(75.0, buying_power * 0.25))
        if equity > 0:
            caps.append(max(75.0, equity * 0.10))
            # Risk-based position sizing: position = risk_dollars / stop_loss_pct.
            # This sizes positions so that a full stop-loss hit equals the
            # intended risk-per-trade dollar amount.
            risk_pct = max(0.1, min(5.0, self._safe_float(risk_per_trade_pct, 1.0)))
            sl_pct = max(0.5, min(10.0, self._safe_float(stop_loss_pct, 2.0)))
            risk_dollars = equity * (risk_pct / 100.0)
            position_from_risk = risk_dollars / (sl_pct / 100.0)
            caps.append(max(50.0, position_from_risk))

        sized = min(caps)
        if active_slots >= 6:
            sized *= 0.85
        elif active_slots >= 3:
            sized *= 0.93

        return max(50.0, round(sized, 2))
    
    def stop_runner(self, db: Optional[Session] = None) -> Dict[str, Any]:
        """
        Stop the strategy runner.
        
        Idempotent - safe to call multiple times.
        
        Returns:
            Dict with status and message
        """
        with self._lock:
            if self.runner is None:
                return {
                    "success": True,
                    "message": "Runner already stopped",
                    "status": "stopped"
                }
            
            if self.runner.status == StrategyStatus.STOPPED:
                return {
                    "success": True,
                    "message": "Runner already stopped",
                    "status": self.runner.status.value
                }
            
            # Create audit log
            owns_session = db is None
            session = db or SessionLocal()
            try:
                storage = StorageService(session)
                storage.create_audit_log(
                    event_type='runner_stopped',
                    description='Strategy runner stopped',
                    details={}
                )
            finally:
                if owns_session:
                    session.close()
            
            # Stop watchdog before stopping runner
            self._stop_watchdog()

            # Stop runner
            success = self.runner.stop()

            if success:
                return {
                    "success": True,
                    "message": "Runner stopped",
                    "status": self.runner.status.value
                }
            else:
                return {
                    "success": False,
                    "message": "Failed to stop runner",
                    "status": self.runner.status.value
                }

    def remove_strategy_by_name(self, strategy_name: str) -> bool:
        """
        Remove a loaded strategy from in-memory runner state.
        Safe to call whether runner exists or not.
        """
        with self._lock:
            if self.runner is None:
                return False
            if strategy_name in self.runner.strategies:
                del self.runner.strategies[strategy_name]
                return True
            return False

    def set_tick_interval(self, tick_interval: float) -> None:
        """Update runner polling interval when config changes."""
        with self._lock:
            if self.runner is not None:
                self.runner.tick_interval = tick_interval

    def set_streaming_enabled(self, enabled: bool) -> None:
        """Enable/disable broker stream assist on an existing runner."""
        with self._lock:
            if self.runner is None:
                return
            self.runner.streaming_enabled = enabled
            if self.runner.status == StrategyStatus.RUNNING:
                try:
                    if enabled:
                        self.runner.broker.start_trade_update_stream(self.runner._on_broker_trade_update)  # noqa: SLF001
                    else:
                        self.runner.broker.stop_trade_update_stream()
                except RuntimeError:
                    pass
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get the current runner status.
        
        Returns:
            Dict with status information
        """
        with self._lock:
            if self.runner is None:
                persisted = self._load_persisted_runtime_state()
                return {
                    "status": "stopped",
                    "strategies": [],
                    "tick_interval": 60.0,
                    "broker_connected": bool(persisted.get("broker_connected", False)),
                    "runner_thread_alive": False,
                    "poll_success_count": int(persisted.get("poll_success_count", 0)),
                    "poll_error_count": int(persisted.get("poll_error_count", 0)),
                    "last_poll_error": str(persisted.get("last_poll_error") or ""),
                    "last_poll_at": persisted.get("last_poll_at"),
                    "last_successful_poll_at": persisted.get("last_successful_poll_at"),
                    "last_reconciliation_at": persisted.get("last_reconciliation_at"),
                    "last_reconciliation_discrepancies": int(persisted.get("last_reconciliation_discrepancies", 0)),
                    "sleeping": False,
                    "sleep_since": None,
                    "next_market_open_at": None,
                    "last_resume_at": persisted.get("last_resume_at"),
                    "last_catchup_at": persisted.get("last_catchup_at"),
                    "resume_count": int(persisted.get("resume_count", 0)),
                    "market_session_open": persisted.get("market_session_open"),
                    "last_state_persisted_at": persisted.get("persisted_at"),
                    "runner_crash_detected_at": self._crash_detected_at,
                    "auto_restart_count": self._auto_restart_count,
                }

            self._normalize_stale_runner_state(self.runner)
            status = self.runner.get_status()
            status["runner_thread_alive"] = self._runner_thread_alive(self.runner)
            status["runner_crash_detected_at"] = self._crash_detected_at
            status["auto_restart_count"] = self._auto_restart_count
            return status


# Global singleton instance
runner_manager = RunnerManager()
