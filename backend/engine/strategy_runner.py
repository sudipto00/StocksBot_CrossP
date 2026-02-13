"""
Strategy Runner Module.
Scheduler/runner loop for executing trading strategies.
"""

from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from enum import Enum
import threading
import time

from engine.strategy_interface import StrategyInterface
from services.broker import BrokerInterface, OrderSide, OrderType
from services.order_execution import OrderExecutionService


class StrategyStatus(Enum):
    """Strategy execution status."""
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
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
        
        self.strategies: Dict[str, StrategyInterface] = {}
        self.status = StrategyStatus.STOPPED
        
        # Scheduler loop control
        self._runner_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
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
        if self.status == StrategyStatus.RUNNING:
            print("[StrategyRunner] Already running")
            return False
        
        if not self.strategies:
            print("[StrategyRunner] No strategies loaded")
            return False
        
        # Connect broker
        if not self.broker.is_connected():
            if not self.broker.connect():
                print("[StrategyRunner] Failed to connect to broker")
                return False
        
        # Start all strategies
        for name, strategy in self.strategies.items():
            try:
                strategy.on_start()
                print(f"[StrategyRunner] Started strategy: {name}")
            except Exception as e:
                print(f"[StrategyRunner] Error starting strategy {name}: {e}")
                return False
        
        # Start scheduler loop
        self._stop_event.clear()
        self._runner_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._runner_thread.start()
        
        self.status = StrategyStatus.RUNNING
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
        if self.broker.is_connected():
            self.broker.disconnect()
        
        self.status = StrategyStatus.STOPPED
        print("[StrategyRunner] Runner stopped")
        return True
    
    def _run_loop(self) -> None:
        """
        Main scheduler loop.
        
        Runs on tick interval, fetches market data, and calls strategies.
        """
        print(f"[StrategyRunner] Scheduler loop started (interval: {self.tick_interval}s)")
        
        while not self._stop_event.is_set():
            try:
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
                        print(f"[StrategyRunner] Error in strategy {name}: {e}")
                
            except Exception as e:
                print(f"[StrategyRunner] Error in scheduler loop: {e}")
            
            # Wait for next tick
            self._stop_event.wait(timeout=self.tick_interval)
        
        print("[StrategyRunner] Scheduler loop exited")
    
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
            "broker_connected": self.broker.is_connected()
        }
    
    def get_strategies(self) -> List[StrategyInterface]:
        """
        Get list of loaded strategies.
        
        Returns:
            List of strategy instances
        """
        return list(self.strategies.values())
