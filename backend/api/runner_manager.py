"""
Strategy Runner Manager - Singleton instance for managing strategy runner lifecycle.
"""
from typing import Optional, Dict, Any
import threading

from engine.strategy_runner import StrategyRunner, StrategyStatus
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
    
    def get_or_create_runner(self) -> StrategyRunner:
        """
        Get the runner instance, creating it if necessary.
        
        Returns:
            StrategyRunner instance
        """
        if self.runner is None:
            # Create broker instance
            broker = PaperBroker(starting_balance=100000.0)
            
            # Create storage service
            db = SessionLocal()
            storage = StorageService(db)
            
            # Create runner
            self.runner = StrategyRunner(
                broker=broker,
                storage_service=storage,
                tick_interval=60.0
            )
        
        return self.runner
    
    def start_runner(self) -> Dict[str, Any]:
        """
        Start the strategy runner.
        
        Idempotent - safe to call multiple times.
        
        Returns:
            Dict with status and message
        """
        with self._lock:
            runner = self.get_or_create_runner()
            
            if runner.status == StrategyStatus.RUNNING:
                return {
                    "success": False,
                    "message": "Runner already running",
                    "status": runner.status.value
                }
            
            # Load active strategies from database
            db = SessionLocal()
            try:
                storage = StorageService(db)
                active_strategies = storage.get_active_strategies()
                
                # TODO: Instantiate actual strategy classes from DB config
                # For now, we'll just track the count
                strategy_count = len(active_strategies)
                
                if strategy_count == 0:
                    return {
                        "success": False,
                        "message": "No active strategies to run",
                        "status": runner.status.value
                    }
                
                # Create audit log
                storage.create_audit_log(
                    event_type='runner_started',
                    description=f'Strategy runner started with {strategy_count} strategies',
                    details={'strategy_count': strategy_count}
                )
            finally:
                db.close()
            
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
    
    def stop_runner(self) -> Dict[str, Any]:
        """
        Stop the strategy runner.
        
        Idempotent - safe to call multiple times.
        
        Returns:
            Dict with status and message
        """
        with self._lock:
            if self.runner is None:
                return {
                    "success": False,
                    "message": "Runner not initialized",
                    "status": "stopped"
                }
            
            if self.runner.status == StrategyStatus.STOPPED:
                return {
                    "success": False,
                    "message": "Runner already stopped",
                    "status": self.runner.status.value
                }
            
            # Create audit log
            db = SessionLocal()
            try:
                storage = StorageService(db)
                storage.create_audit_log(
                    event_type='runner_stopped',
                    description='Strategy runner stopped',
                    details={}
                )
            finally:
                db.close()
            
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
