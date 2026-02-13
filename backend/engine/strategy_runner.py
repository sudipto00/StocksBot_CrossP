"""
Strategy Runner Module.
Scheduler/runner loop for executing trading strategies.
"""

from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timezone
from enum import Enum
import threading
import time
import logging
import json

from engine.strategy_interface import StrategyInterface
from services.broker import BrokerInterface, OrderSide, OrderType
from services.order_execution import OrderExecutionService

logger = logging.getLogger(__name__)


class StrategyStatus(Enum):
    """Strategy execution status."""
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    SLEEPING = "sleeping"
    ERROR = "error"


class StrategyRunner:
    """
    Strategy execution engine with scheduler/runner loop.
    
    Responsible for:
    - Loading and initializing trading strategies
    - Managing strategy lifecycle (start/stop/pause)
    - Running scheduler loop on tick interval
    - Processing market data and generating signals
    - Executing paper trades through broker abstraction
    - Recording results in storage
    """
    
    def __init__(
        self,
        broker: BrokerInterface,
        storage_service: Optional[Any] = None,
        tick_interval: float = 60.0,
        order_execution_service: Optional[OrderExecutionService] = None,
        streaming_enabled: bool = False,
    ):
        """
        Initialize strategy runner.
        
        Args:
            broker: Broker instance for order execution
            storage_service: Storage service for recording trades (optional)
            tick_interval: Interval between ticks in seconds (default: 60s)
        """
        self.broker = broker
        self.storage = storage_service
        self.tick_interval = tick_interval
        self.order_execution_service = order_execution_service
        self.streaming_enabled = streaming_enabled
        
        self.strategies: Dict[str, StrategyInterface] = {}
        self.status = StrategyStatus.STOPPED
        
        # Scheduler loop control
        self._runner_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stream_update_event = threading.Event()
        self.poll_success_count = 0
        self.poll_error_count = 0
        self.last_poll_error = ""
        self.last_poll_at: Optional[datetime] = None
        self.last_successful_poll_at: Optional[datetime] = None
        self._last_error_audit_at: Optional[datetime] = None
        self.last_reconciliation_at: Optional[datetime] = None
        self.last_reconciliation_discrepancies: int = 0
        self._last_reconciliation_ts = 0.0
        self.sleeping = False
        self.sleep_since: Optional[datetime] = None
        self.next_market_open_at: Optional[datetime] = None
        self.last_resume_at: Optional[datetime] = None
        self.last_catchup_at: Optional[datetime] = None
        self.resume_count: int = 0
        self.market_session_open: Optional[bool] = None
        self.off_hours_poll_interval = max(15.0, float(self.tick_interval))
        self._sleep_state_key = "runner_sleep_state"
        self._restore_sleep_state()
        
        # Callbacks
        self.on_signal_callback: Optional[Callable] = None
    
    def load_strategy(self, strategy: StrategyInterface) -> bool:
        """
        Load a trading strategy instance.
        
        Args:
            strategy: Strategy instance implementing StrategyInterface
            
        Returns:
            True if loaded successfully
        """
        strategy_name = strategy.get_name()
        self.strategies[strategy_name] = strategy
        print(f"[StrategyRunner] Loaded strategy: {strategy_name}")
        return True
    
    def start(self) -> bool:
        """
        Start the strategy runner.
        
        Starts all loaded strategies and begins the scheduler loop.
        
        Returns:
            True if started successfully
        """
        if self._runner_thread and self._runner_thread.is_alive() and not self._stop_event.is_set():
            print(f"[StrategyRunner] Already active ({self.status.value})")
            return False
        
        if not self.strategies:
            print("[StrategyRunner] No strategies loaded")
            return False
        
        # Connect broker
        if not self.broker.is_connected():
            if not self.broker.connect():
                print("[StrategyRunner] Failed to connect to broker")
                return False

        # Optional websocket trade update stream (hybrid with polling fallback).
        if self.streaming_enabled:
            try:
                started_stream = self.broker.start_trade_update_stream(self._on_broker_trade_update)
                if started_stream:
                    print("[StrategyRunner] Broker trade update stream enabled")
                else:
                    print("[StrategyRunner] Broker trade update stream unavailable, using polling fallback")
            except Exception as e:
                print(f"[StrategyRunner] Failed to start trade update stream: {e}")
        
        # Start all strategies
        for name, strategy in self.strategies.items():
            try:
                strategy.on_start()
                print(f"[StrategyRunner] Started strategy: {name}")
            except Exception as e:
                print(f"[StrategyRunner] Error starting strategy {name}: {e}")
                return False
        
        # Mark running before launching thread; loop may immediately transition to SLEEPING.
        self.status = StrategyStatus.RUNNING

        # Start scheduler loop
        self._stop_event.clear()
        self._runner_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._runner_thread.start()

        print(f"[StrategyRunner] Runner started with {len(self.strategies)} strategies")
        return True
    
    def stop(self) -> bool:
        """
        Stop the strategy runner.
        
        Stops all strategies and the scheduler loop.
        
        Returns:
            True if stopped successfully
        """
        if self.status == StrategyStatus.STOPPED:
            print("[StrategyRunner] Already stopped")
            return False
        
        # Signal the loop to stop
        self._stop_event.set()
        
        # Wait for runner thread to finish
        if self._runner_thread and self._runner_thread.is_alive():
            self._runner_thread.join(timeout=5.0)
        
        # Stop all strategies
        for name, strategy in self.strategies.items():
            try:
                strategy.on_stop()
                print(f"[StrategyRunner] Stopped strategy: {name}")
            except Exception as e:
                print(f"[StrategyRunner] Error stopping strategy {name}: {e}")
        
        # Disconnect broker
        if self.streaming_enabled:
            try:
                self.broker.stop_trade_update_stream()
            except Exception as e:
                print(f"[StrategyRunner] Error stopping trade update stream: {e}")
        if self.broker.is_connected():
            self.broker.disconnect()
        
        self.sleeping = False
        self.sleep_since = None
        self.next_market_open_at = None
        self.status = StrategyStatus.STOPPED
        self._persist_sleep_state()
        print("[StrategyRunner] Runner stopped")
        return True
    
    def _run_loop(self) -> None:
        """
        Main scheduler loop.
        
        Runs on tick interval, fetches market data, and calls strategies.
        """
        print(f"[StrategyRunner] Scheduler loop started (interval: {self.tick_interval}s)")
        
        while not self._stop_event.is_set():
            self.last_poll_at = datetime.now(timezone.utc)
            try:
                if not self.broker.is_connected():
                    if not self.broker.connect():
                        raise RuntimeError("Broker reconnect failed")
                    logger.info("Broker reconnected in strategy runner loop")

                self.market_session_open = bool(self.broker.is_market_open())
                if not self.market_session_open:
                    self._enter_sleep_mode()
                    self.poll_success_count += 1
                    self.last_successful_poll_at = datetime.now(timezone.utc)
                    self._sleep_wait(self.off_hours_poll_interval)
                    continue

                if self.sleeping:
                    self._resume_from_sleep()
                # Fetch market data for all symbols
                market_data = self._fetch_market_data()
                
                # Process each strategy
                for name, strategy in self.strategies.items():
                    try:
                        # Call strategy's on_tick
                        signals = strategy.on_tick(market_data)
                        
                        # Execute signals
                        if signals:
                            self._execute_signals(strategy, signals)
                    
                    except Exception as e:
                        self.poll_error_count += 1
                        self.last_poll_error = f"strategy:{name} -> {e}"
                        print(f"[StrategyRunner] Error in strategy {name}: {e}")
                        logger.exception("Strategy tick failed for %s", name)
                        self._audit_poll_error(self.last_poll_error)
                self.poll_success_count += 1
                self.last_successful_poll_at = datetime.now(timezone.utc)
                
            except Exception as e:
                self.poll_error_count += 1
                self.last_poll_error = str(e)
                print(f"[StrategyRunner] Error in scheduler loop: {e}")
                logger.exception("Strategy runner scheduler loop error")
                self._audit_poll_error(self.last_poll_error)

            # Keep local order/trade/position state synchronized with broker fills.
            try:
                self._reconcile_open_orders()
            except Exception as e:
                print(f"[StrategyRunner] Error reconciling open orders: {e}")

            # Periodic local-vs-broker position reconciliation.
            try:
                self._maybe_reconcile_positions_with_broker()
            except Exception as e:
                print(f"[StrategyRunner] Error during position reconciliation: {e}")
            
            # Wait for next tick, but wake early on broker trade updates.
            self._sleep_wait(self.tick_interval)
        
        print("[StrategyRunner] Scheduler loop exited")

    def _sleep_wait(self, seconds: float) -> None:
        """Wait loop that can wake early on stream updates or stop requests."""
        end_time = time.time() + max(0.1, seconds)
        while not self._stop_event.is_set():
            remaining = max(0.0, end_time - time.time())
            if remaining <= 0:
                break
            wait_slice = min(0.5, remaining)
            if self._stream_update_event.wait(timeout=wait_slice):
                self._stream_update_event.clear()
                break

    def _enter_sleep_mode(self) -> None:
        """Transition runner into off-hours sleep mode."""
        if self.sleeping:
            # Keep next-open forecast refreshed for status UI.
            self.next_market_open_at = self._safe_next_market_open()
            self._persist_sleep_state()
            return
        self.sleeping = True
        self.sleep_since = datetime.now(timezone.utc)
        self.next_market_open_at = self._safe_next_market_open()
        self.status = StrategyStatus.SLEEPING
        self._persist_sleep_state()
        if self.storage:
            try:
                self.storage.create_audit_log(
                    event_type="config_updated",
                    description="Runner entered off-hours sleep mode",
                    details={
                        "sleep_since": self.sleep_since.isoformat(),
                        "next_market_open_at": self.next_market_open_at.isoformat() if self.next_market_open_at else None,
                    },
                )
            except Exception:
                pass

    def _resume_from_sleep(self) -> None:
        """Resume active processing after off-hours sleep."""
        self.sleeping = False
        self.last_resume_at = datetime.now(timezone.utc)
        self.last_catchup_at = self.last_resume_at
        self.resume_count += 1
        self.sleep_since = None
        self.next_market_open_at = None
        self.status = StrategyStatus.RUNNING
        # Warm market-data cache immediately after open so charts/strategies pick up continuity quickly.
        try:
            _ = self._fetch_market_data()
        except Exception:
            pass
        self._persist_sleep_state()
        if self.storage:
            try:
                self.storage.create_audit_log(
                    event_type="config_updated",
                    description="Runner resumed after market open",
                    details={
                        "resume_at": self.last_resume_at.isoformat(),
                        "resume_count": self.resume_count,
                    },
                )
            except Exception:
                pass

    def _safe_next_market_open(self) -> Optional[datetime]:
        """Best-effort next market-open timestamp from broker."""
        try:
            next_open = self.broker.get_next_market_open()
            if not next_open:
                return None
            if next_open.tzinfo is None:
                return next_open.replace(tzinfo=timezone.utc)
            return next_open.astimezone(timezone.utc)
        except Exception:
            return None

    def _persist_sleep_state(self) -> None:
        """Persist sleep/resume checkpoint to DB config for continuity across restarts."""
        if not self.storage:
            return
        try:
            payload = {
                "sleeping": self.sleeping,
                "sleep_since": self.sleep_since.isoformat() if self.sleep_since else None,
                "next_market_open_at": self.next_market_open_at.isoformat() if self.next_market_open_at else None,
                "last_resume_at": self.last_resume_at.isoformat() if self.last_resume_at else None,
                "last_catchup_at": self.last_catchup_at.isoformat() if self.last_catchup_at else None,
                "resume_count": self.resume_count,
            }
            self.storage.config.upsert(
                key=self._sleep_state_key,
                value=json.dumps(payload),
                value_type="json",
                description="Runner sleep/resume continuity checkpoint",
            )
        except Exception:
            pass

    def _restore_sleep_state(self) -> None:
        """Load prior sleep/resume checkpoint from DB config, if present."""
        if not self.storage:
            return
        try:
            entry = self.storage.config.get_by_key(self._sleep_state_key)
            if not entry or not entry.value:
                return
            payload = json.loads(entry.value)
            self.sleeping = bool(payload.get("sleeping", False))
            self.sleep_since = self._parse_iso(payload.get("sleep_since"))
            self.next_market_open_at = self._parse_iso(payload.get("next_market_open_at"))
            self.last_resume_at = self._parse_iso(payload.get("last_resume_at"))
            self.last_catchup_at = self._parse_iso(payload.get("last_catchup_at"))
            self.resume_count = int(payload.get("resume_count", 0))
            if self.sleeping:
                self.status = StrategyStatus.SLEEPING
        except Exception:
            pass

    def _parse_iso(self, value: Any) -> Optional[datetime]:
        """Parse optional ISO datetime safely."""
        if not value or not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None

    def _reconcile_open_orders(self) -> None:
        """Poll broker status for open local orders and process newly filled trades."""
        if not self.order_execution_service or not self.storage:
            return
        open_orders = self.storage.get_open_orders(limit=500)
        for order in open_orders:
            try:
                self.order_execution_service.update_order_status(order)
            except Exception as e:
                print(f"[StrategyRunner] Failed to reconcile order {order.id}: {e}")
                logger.exception("Failed to reconcile order %s", order.id)

    def _on_broker_trade_update(self, update: Dict[str, Any]) -> None:
        """
        Trade update callback from broker stream.
        Signals runner loop to reconcile orders immediately.
        """
        self._stream_update_event.set()

    def _maybe_reconcile_positions_with_broker(self) -> None:
        """Run position reconciliation every 5 minutes."""
        if not self.storage:
            return
        # In-memory sqlite sessions in tests are not thread-safe for runner thread usage.
        try:
            bind_url = str(self.storage.db.get_bind().url)
            if bind_url.startswith("sqlite:///:memory:"):
                return
        except Exception:
            pass
        now = time.time()
        if now - self._last_reconciliation_ts < 300:
            return
        self._last_reconciliation_ts = now
        broker_positions = self.broker.get_positions()
        local_positions = self.storage.get_open_positions()
        broker_qty: Dict[str, float] = {}
        local_qty: Dict[str, float] = {}
        for row in broker_positions:
            sym = str(row.get("symbol", "")).upper()
            if not sym:
                continue
            broker_qty[sym] = broker_qty.get(sym, 0.0) + float(row.get("quantity", 0.0))
        for row in local_positions:
            sym = str(row.symbol).upper()
            local_qty[sym] = local_qty.get(sym, 0.0) + float(row.quantity or 0.0)
        discrepancies = 0
        for sym in set(broker_qty.keys()) | set(local_qty.keys()):
            if abs(float(broker_qty.get(sym, 0.0)) - float(local_qty.get(sym, 0.0))) > 1e-6:
                discrepancies += 1
        self.last_reconciliation_at = datetime.now(timezone.utc)
        self.last_reconciliation_discrepancies = discrepancies
        if discrepancies > 0:
            self.storage.create_audit_log(
                event_type="error",
                description=f"Runner reconciliation found {discrepancies} discrepancy(ies)",
                details={"source": "strategy_runner_reconciliation"},
            )

    def _audit_poll_error(self, message: str) -> None:
        """Write poll errors into audit trail with basic throttling."""
        if not self.storage:
            return
        now = datetime.now(timezone.utc)
        if self._last_error_audit_at and (now - self._last_error_audit_at).total_seconds() < 30:
            return
        self._last_error_audit_at = now
        try:
            self.storage.create_audit_log(
                event_type="error",
                description=f"Runner poll error: {message}",
                details={"source": "strategy_runner_poll"},
            )
        except Exception:
            pass
    
    def _fetch_market_data(self) -> Dict[str, Dict[str, Any]]:
        """
        Fetch current market data for all tracked symbols.
        
        Returns:
            Dictionary mapping symbols to market data
        """
        # Collect all symbols from all strategies
        symbols = set()
        for strategy in self.strategies.values():
            symbols.update(strategy.get_symbols())
        
        # Fetch data from broker
        market_data = {}
        for symbol in symbols:
            try:
                data = self.broker.get_market_data(symbol)
                market_data[symbol] = data
            except Exception as e:
                print(f"[StrategyRunner] Error fetching data for {symbol}: {e}")
        
        return market_data
    
    def _execute_signals(self, strategy: StrategyInterface, signals: List[Dict[str, Any]]) -> None:
        """
        Execute trading signals through paper broker.
        
        Args:
            strategy: Strategy that generated signals
            signals: List of signal dictionaries
        """
        for signal_data in signals:
            try:
                symbol = signal_data.get("symbol")
                signal = signal_data.get("signal")
                quantity = signal_data.get("quantity", 0)
                order_type = signal_data.get("order_type", "market")
                price = signal_data.get("price")
                reason = signal_data.get("reason", "")
                
                # Convert signal to order side
                if signal.value in ["buy"]:
                    side = OrderSide.BUY
                elif signal.value in ["sell", "close"]:
                    side = OrderSide.SELL
                else:
                    continue  # HOLD or unknown signal
                
                # Convert order type
                if order_type == "limit":
                    otype = OrderType.LIMIT
                elif order_type == "stop":
                    otype = OrderType.STOP
                else:
                    otype = OrderType.MARKET
                
                # Submit order through broker
                if self.order_execution_service:
                    strategy_id = strategy.config.get("strategy_id")
                    submitted = self.order_execution_service.submit_order(
                        symbol=symbol,
                        side=side.value,
                        order_type=otype.value,
                        quantity=quantity,
                        price=price,
                        strategy_id=strategy_id,
                    )
                    order = {
                        "id": submitted.external_id or str(submitted.id),
                        "status": submitted.status.value,
                        "symbol": submitted.symbol,
                        "filled_quantity": submitted.filled_quantity,
                        "avg_fill_price": submitted.avg_fill_price,
                    }
                else:
                    order = self.broker.submit_order(
                        symbol=symbol,
                        side=side,
                        order_type=otype,
                        quantity=quantity,
                        price=price
                    )
                
                print(f"[StrategyRunner] Executed {signal.value} order for {symbol}: {order}")
                
                # Record in storage if available and execution service is not used.
                if self.storage and not self.order_execution_service:
                    try:
                        fill_price = price or order.get("avg_fill_price") or order.get("price") or 100.0
                        db_order = self.storage.create_order(
                            symbol=symbol,
                            side=side.value,
                            order_type=otype.value,
                            quantity=quantity,
                            price=price
                        )
                        
                        # For paper trading, immediately fill the order
                        self.storage.update_order_status(
                            order_id=db_order.id,
                            status="filled",
                            filled_quantity=quantity,
                            avg_fill_price=fill_price
                        )
                        
                        # Record trade
                        self.storage.record_trade(
                            order_id=db_order.id,
                            symbol=symbol,
                            side=side.value,
                            quantity=quantity,
                            price=fill_price
                        )
                        
                        print(f"[StrategyRunner] Recorded order and trade in storage")
                    except Exception as e:
                        print(f"[StrategyRunner] Error recording in storage: {e}")
                
                # Call callback if set
                if self.on_signal_callback:
                    self.on_signal_callback(strategy, signal_data, order)
            
            except Exception as e:
                print(f"[StrategyRunner] Error executing signal: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get runner status.
        
        Returns:
            Status dictionary
        """
        return {
            "status": self.status.value,
            "strategies": [s.get_state() for s in self.strategies.values()],
            "tick_interval": self.tick_interval,
            "broker_connected": self.broker.is_connected(),
            "poll_success_count": self.poll_success_count,
            "poll_error_count": self.poll_error_count,
            "last_poll_error": self.last_poll_error,
            "last_poll_at": self.last_poll_at.isoformat() if self.last_poll_at else None,
            "last_successful_poll_at": self.last_successful_poll_at.isoformat() if self.last_successful_poll_at else None,
            "last_reconciliation_at": self.last_reconciliation_at.isoformat() if self.last_reconciliation_at else None,
            "last_reconciliation_discrepancies": self.last_reconciliation_discrepancies,
            "sleeping": self.sleeping,
            "sleep_since": self.sleep_since.isoformat() if self.sleep_since else None,
            "next_market_open_at": self.next_market_open_at.isoformat() if self.next_market_open_at else None,
            "last_resume_at": self.last_resume_at.isoformat() if self.last_resume_at else None,
            "last_catchup_at": self.last_catchup_at.isoformat() if self.last_catchup_at else None,
            "resume_count": self.resume_count,
            "market_session_open": self.market_session_open,
        }
    
    def get_strategies(self) -> List[StrategyInterface]:
        """
        Get list of loaded strategies.
        
        Returns:
            List of strategy instances
        """
        return list(self.strategies.values())
