"""
Strategy Plugin Interface.
Abstract base class that all trading strategies must implement.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from datetime import datetime
from enum import Enum


class Signal(Enum):
    """Trading signal types."""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CLOSE = "close"


class StrategyInterface(ABC):
    """
    Abstract base class for all trading strategies.
    
    All strategies must implement this interface to be compatible
    with the strategy runner.
    
    Lifecycle:
    1. __init__() - Strategy is instantiated with config
    2. on_start() - Called when strategy starts running
    3. on_tick() - Called on each scheduler tick
    4. on_stop() - Called when strategy is stopped
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize strategy with configuration.
        
        Args:
            config: Strategy configuration dictionary
        """
        self.config = config
        self.name = config.get("name", self.__class__.__name__)
        self.symbols = config.get("symbols", [])
        self.is_running = False
        self.state: Dict[str, Any] = {}
    
    @abstractmethod
    def on_start(self) -> None:
        """
        Called when strategy starts.
        
        Use this to initialize state, subscribe to data, etc.
        Must be implemented by concrete strategies.
        """
        pass
    
    @abstractmethod
    def on_tick(self, market_data: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Called on each scheduler tick with current market data.
        
        Args:
            market_data: Dictionary mapping symbols to market data
                Example: {
                    "AAPL": {"price": 150.0, "volume": 1000000, "timestamp": "..."},
                    "MSFT": {"price": 300.0, "volume": 500000, "timestamp": "..."}
                }
        
        Returns:
            List of signals/orders to execute
                Example: [
                    {
                        "symbol": "AAPL",
                        "signal": Signal.BUY,
                        "quantity": 100,
                        "order_type": "market",
                        "reason": "Moving average crossover"
                    }
                ]
        
        Must be implemented by concrete strategies.
        """
        pass
    
    @abstractmethod
    def on_stop(self) -> None:
        """
        Called when strategy stops.
        
        Use this to clean up resources, unsubscribe from data,
        close positions if needed, etc.
        Must be implemented by concrete strategies.
        """
        pass
    
    def get_state(self) -> Dict[str, Any]:
        """
        Get current strategy state.
        
        Returns:
            Dictionary containing strategy state information
        """
        return {
            "name": self.name,
            "is_running": self.is_running,
            "symbols": self.symbols,
            "state": self.state
        }
    
    def get_name(self) -> str:
        """Get strategy name."""
        return self.name
    
    def get_symbols(self) -> List[str]:
        """Get list of symbols this strategy trades."""
        return self.symbols
