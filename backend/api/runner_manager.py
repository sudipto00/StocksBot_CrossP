"""
Strategy Runner Manager - Singleton instance for managing strategy runner lifecycle.
"""
from typing import Optional, Dict, Any
import threading
from sqlalchemy.orm import Session

from engine.strategy_runner import StrategyRunner, StrategyStatus
from engine.strategies import BuyAndHoldStrategy
from services.broker import PaperBroker
from storage.database import SessionLocal
from storage.service import StorageService


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
    
    def get_or_create_runner(self, db: Optional[Session] = None) -> StrategyRunner:
        """
        Get the runner instance, creating it if necessary.
        
        Returns:
            StrategyRunner instance
        """
        if self.runner is None:
            # Create broker instance
            broker = PaperBroker(starting_balance=100000.0)
            
            # Create dedicated storage session for runner lifetime.
            # Do not reuse request-scoped sessions.
            db_session = SessionLocal()
            storage = StorageService(db_session)
            
            # Create runner
            self.runner = StrategyRunner(
                broker=broker,
                storage_service=storage,
                tick_interval=60.0
            )
        
        return self.runner
    
    def start_runner(self, db: Optional[Session] = None) -> Dict[str, Any]:
        """
        Start the strategy runner.
        
        Idempotent - safe to call multiple times.
        
        Returns:
            Dict with status and message
        """
        with self._lock:
            runner = self.get_or_create_runner(db=db)
            
            if runner.status == StrategyStatus.RUNNING:
                return {
                    "success": False,
                    "message": "Runner already running",
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
                
                if strategy_count == 0:
                    return {
                        "success": False,
                        "message": "No active strategies to run",
                        "status": runner.status.value
                    }

                # Load active DB strategies into runner before start.
                # Current implementation maps all DB strategies to BuyAndHoldStrategy.
                for db_strategy in active_strategies:
                    config = db_strategy.config or {}
                    strategy = BuyAndHoldStrategy({
                        "name": db_strategy.name,
                        "symbols": config.get("symbols", []),
                        "position_size": config.get("position_size", 100),
                        "sell_on_stop": config.get("sell_on_stop", False),
                    })
                    runner.load_strategy(strategy)
                
                # Create audit log
                storage.create_audit_log(
                    event_type='runner_started',
                    description=f'Strategy runner started with {strategy_count} strategies',
                    details={'strategy_count': strategy_count}
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
                "broker_connected": False
            }
        
        return self.runner.get_status()


# Global singleton instance
runner_manager = RunnerManager()
