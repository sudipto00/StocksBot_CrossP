"""
Strategy Runner Manager - Singleton instance for managing strategy runner lifecycle.
"""
from typing import Optional, Dict, Any
import threading
import math
import re
from sqlalchemy.orm import Session

from engine.strategy_runner import StrategyRunner, StrategyStatus
from engine.strategies import MetricsDrivenStrategy
from services.broker import PaperBroker
from services.order_execution import OrderExecutionService
from storage.database import SessionLocal
from storage.service import StorageService
import json


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
    
    def get_or_create_runner(
        self,
        db: Optional[Session] = None,
        broker: Optional[Any] = None,
        max_position_size: float = 10000.0,
        risk_limit_daily: float = 500.0,
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
        
        return self.runner
    
    def start_runner(
        self,
        db: Optional[Session] = None,
        broker: Optional[Any] = None,
        max_position_size: float = 10000.0,
        risk_limit_daily: float = 500.0,
        tick_interval: float = 60.0,
        streaming_enabled: bool = False,
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
                tick_interval=tick_interval,
                streaming_enabled=streaming_enabled,
            )
            
            if runner.status in (StrategyStatus.RUNNING, StrategyStatus.SLEEPING):
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
                    except Exception:
                        prefs = {}
                
                if strategy_count == 0:
                    return {
                        "success": False,
                        "message": "No active strategies to run",
                        "status": runner.status.value
                    }

                # Load active DB strategies into runner before start using metrics-driven logic.
                skipped_invalid = []
                allowed_params = set(self._strategy_param_defaults_from_prefs({"asset_type": "stock", "stock_preset": "weekly_optimized"}).keys())
                for db_strategy in active_strategies:
                    config = db_strategy.config or {}
                    raw_symbols = config.get("symbols", [])
                    symbols = self._normalize_symbols(raw_symbols if isinstance(raw_symbols, list) else [])
                    if not symbols:
                        skipped_invalid.append(db_strategy.name)
                        continue
                    params = config.get("parameters", {}) if isinstance(config.get("parameters", {}), dict) else {}
                    preset_defaults = self._strategy_param_defaults_from_prefs(prefs)
                    validated_params: Dict[str, float] = {}
                    for key, value in params.items():
                        if key not in allowed_params:
                            continue
                        try:
                            numeric = float(value)
                        except (TypeError, ValueError):
                            continue
                        if math.isfinite(numeric):
                            validated_params[key] = numeric
                    merged_params = {**preset_defaults, **validated_params}
                    strategy = MetricsDrivenStrategy({
                        "name": db_strategy.name,
                        "strategy_id": db_strategy.id,
                        "symbols": symbols,
                        "position_size": float(merged_params.get("position_size", 1000.0)),
                        "stop_loss_pct": float(merged_params.get("stop_loss_pct", 2.0)),
                        "take_profit_pct": float(merged_params.get("take_profit_pct", 5.0)),
                        "trailing_stop_pct": float(merged_params.get("trailing_stop_pct", 2.5)),
                        "atr_stop_mult": float(merged_params.get("atr_stop_mult", 1.8)),
                        "zscore_entry_threshold": float(merged_params.get("zscore_entry_threshold", -1.5)),
                        "dip_buy_threshold_pct": float(merged_params.get("dip_buy_threshold_pct", 2.0)),
                    })
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
                    details={'strategy_count': strategy_count, 'loaded_count': len(runner.strategies), 'skipped_invalid': skipped_invalid}
                )
            finally:
                if owns_session:
                    session.close()
            
            # Start runner
            success = runner.start()
            
            if success:
                return {
                    "success": True,
                    "message": f"Runner started with {strategy_count} strategies",
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
        asset_type = str(prefs.get("asset_type", "stock"))
        stock_preset = str(prefs.get("stock_preset", "weekly_optimized"))
        etf_preset = str(prefs.get("etf_preset", "balanced"))

        stock_defaults = {
            "weekly_optimized": {"position_size": 1200, "stop_loss_pct": 2.5, "take_profit_pct": 6.0, "trailing_stop_pct": 2.0, "atr_stop_mult": 1.7, "zscore_entry_threshold": -1.4, "dip_buy_threshold_pct": 1.8},
            "three_to_five_weekly": {"position_size": 1000, "stop_loss_pct": 3.0, "take_profit_pct": 5.5, "trailing_stop_pct": 2.5, "atr_stop_mult": 1.9, "zscore_entry_threshold": -1.5, "dip_buy_threshold_pct": 2.2},
            "monthly_optimized": {"position_size": 900, "stop_loss_pct": 4.0, "take_profit_pct": 8.0, "trailing_stop_pct": 3.2, "atr_stop_mult": 2.2, "zscore_entry_threshold": -1.8, "dip_buy_threshold_pct": 2.8},
            "small_budget_weekly": {"position_size": 500, "stop_loss_pct": 3.2, "take_profit_pct": 4.8, "trailing_stop_pct": 2.2, "atr_stop_mult": 1.6, "zscore_entry_threshold": -1.4, "dip_buy_threshold_pct": 2.0},
        }
        etf_defaults = {
            "conservative": {"position_size": 800, "stop_loss_pct": 2.5, "take_profit_pct": 4.0, "trailing_stop_pct": 2.0, "atr_stop_mult": 1.4, "zscore_entry_threshold": -1.3, "dip_buy_threshold_pct": 1.6},
            "balanced": {"position_size": 1000, "stop_loss_pct": 3.0, "take_profit_pct": 5.0, "trailing_stop_pct": 2.4, "atr_stop_mult": 1.7, "zscore_entry_threshold": -1.5, "dip_buy_threshold_pct": 2.0},
            "aggressive": {"position_size": 1300, "stop_loss_pct": 4.0, "take_profit_pct": 7.0, "trailing_stop_pct": 3.0, "atr_stop_mult": 2.0, "zscore_entry_threshold": -1.8, "dip_buy_threshold_pct": 2.6},
        }
        if asset_type == "etf":
            return etf_defaults.get(etf_preset, etf_defaults["balanced"])
        return stock_defaults.get(stock_preset, stock_defaults["weekly_optimized"])

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
                except Exception:
                    pass
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get the current runner status.
        
        Returns:
            Dict with status information
        """
        if self.runner is None:
            return {
                "status": "stopped",
                "strategies": [],
                "tick_interval": 60.0,
                "broker_connected": False,
                "poll_success_count": 0,
                "poll_error_count": 0,
                "last_poll_error": "",
                "last_poll_at": None,
                "last_successful_poll_at": None,
                "last_reconciliation_at": None,
                "last_reconciliation_discrepancies": 0,
                "sleeping": False,
                "sleep_since": None,
                "next_market_open_at": None,
                "last_resume_at": None,
                "last_catchup_at": None,
                "resume_count": 0,
                "market_session_open": None,
            }
        
        return self.runner.get_status()


# Global singleton instance
runner_manager = RunnerManager()
