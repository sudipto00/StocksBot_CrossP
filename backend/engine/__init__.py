"""
Trading engine module.

Core components:
- Strategy interface and implementations
- Strategy runner with scheduler
- Risk management
- Order management
"""

from engine.strategy_interface import StrategyInterface, Signal
from engine.strategies import MovingAverageCrossoverStrategy, BuyAndHoldStrategy
from engine.strategy_runner import StrategyRunner, StrategyStatus

__all__ = [
    "StrategyInterface",
    "Signal",
    "MovingAverageCrossoverStrategy",
    "BuyAndHoldStrategy",
    "StrategyRunner",
    "StrategyStatus",
]
