"""
Sample Strategy Implementations.
Example strategies to demonstrate the strategy interface.
"""

from typing import Dict, List, Any
from engine.strategy_interface import StrategyInterface, Signal


class MovingAverageCrossoverStrategy(StrategyInterface):
    """
    Sample strategy: Moving Average Crossover.
    
    Strategy Logic (TODO):
    - Calculate short-term and long-term moving averages
    - BUY when short MA crosses above long MA
    - SELL when short MA crosses below long MA
    
    This is a STUB implementation with TODOs for demonstration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize MA Crossover strategy.
        
        Expected config:
            - symbols: List of symbols to trade
            - short_window: Short MA period (e.g., 10)
            - long_window: Long MA period (e.g., 50)
            - position_size: Number of shares per trade
        """
        super().__init__(config)
        self.short_window = config.get("short_window", 10)
        self.long_window = config.get("long_window", 50)
        self.position_size = config.get("position_size", 100)
        
        # State tracking
        self.state = {
            "price_history": {},  # symbol -> list of prices
            "positions": {},  # symbol -> position info
            "last_signal": {}  # symbol -> last signal
        }
    
    def on_start(self) -> None:
        """
        Initialize strategy on start.
        
        TODO:
        - Load historical price data for MA calculation
        - Initialize price history for each symbol
        - Set up any required indicators
        """
        print(f"[{self.name}] Starting MA Crossover Strategy")
        print(f"  Symbols: {self.symbols}")
        print(f"  Short MA: {self.short_window}, Long MA: {self.long_window}")
        
        # TODO: Initialize price history from market data provider
        for symbol in self.symbols:
            self.state["price_history"][symbol] = []
            self.state["positions"][symbol] = None
            self.state["last_signal"][symbol] = Signal.HOLD
        
        self.is_running = True
    
    def on_tick(self, market_data: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process market data and generate signals.
        
        TODO:
        - Update price history with new data
        - Calculate moving averages
        - Detect crossovers
        - Generate buy/sell signals
        - Implement position management
        """
        signals = []
        
        for symbol in self.symbols:
            if symbol not in market_data:
                continue
            
            data = market_data[symbol]
            current_price = data.get("price", 0)
            
            # TODO: Update price history
            # self.state["price_history"][symbol].append(current_price)
            # Keep only the required window
            # if len(self.state["price_history"][symbol]) > self.long_window:
            #     self.state["price_history"][symbol].pop(0)
            
            # TODO: Calculate moving averages
            # short_ma = self._calculate_ma(symbol, self.short_window)
            # long_ma = self._calculate_ma(symbol, self.long_window)
            
            # TODO: Detect crossover and generate signal
            # if short_ma > long_ma and self.state["last_signal"][symbol] != Signal.BUY:
            #     signals.append({
            #         "symbol": symbol,
            #         "signal": Signal.BUY,
            #         "quantity": self.position_size,
            #         "order_type": "market",
            #         "reason": f"MA crossover - short {short_ma:.2f} > long {long_ma:.2f}"
            #     })
            #     self.state["last_signal"][symbol] = Signal.BUY
            
            # Placeholder: Just hold for now
            pass
        
        return signals
    
    def on_stop(self) -> None:
        """
        Clean up when strategy stops.
        
        TODO:
        - Close any open positions if configured
        - Save strategy state
        - Clean up resources
        """
        print(f"[{self.name}] Stopping MA Crossover Strategy")
        
        # TODO: Implement position closing logic
        # for symbol, position in self.state["positions"].items():
        #     if position:
        #         # Generate close signal
        #         pass
        
        self.is_running = False
    
    def _calculate_ma(self, symbol: str, window: int) -> float:
        """
        Calculate moving average for a symbol.
        
        TODO: Implement actual moving average calculation
        
        Args:
            symbol: Stock symbol
            window: MA window size
            
        Returns:
            Moving average value
        """
        # TODO: Implement
        # prices = self.state["price_history"][symbol]
        # if len(prices) < window:
        #     return 0.0
        # return sum(prices[-window:]) / window
        return 0.0


class BuyAndHoldStrategy(StrategyInterface):
    """
    Sample strategy: Buy and Hold.
    
    Strategy Logic (TODO):
    - Buy specified symbols on start
    - Hold positions indefinitely
    - Optionally sell on stop
    
    This is a STUB implementation with TODOs for demonstration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Buy and Hold strategy.
        
        Expected config:
            - symbols: List of symbols to buy
            - position_size: Number of shares per symbol
            - sell_on_stop: Whether to sell when strategy stops
        """
        super().__init__(config)
        self.position_size = config.get("position_size", 100)
        self.sell_on_stop = config.get("sell_on_stop", False)
        
        self.state = {
            "bought": {}  # symbol -> bool
        }
    
    def on_start(self) -> None:
        """
        Buy symbols on strategy start.
        
        TODO:
        - Check if we already have positions
        - Generate buy orders for each symbol
        """
        print(f"[{self.name}] Starting Buy and Hold Strategy")
        print(f"  Symbols: {self.symbols}")
        
        for symbol in self.symbols:
            self.state["bought"][symbol] = False
        
        self.is_running = True
    
    def on_tick(self, market_data: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Buy symbols that haven't been bought yet.
        
        TODO:
        - Check current positions
        - Buy symbols we don't have yet
        - Track purchases
        """
        signals = []
        
        for symbol in self.symbols:
            if symbol not in market_data:
                continue
            
            # TODO: Check if we already have a position
            # TODO: If not, generate buy signal
            if not self.state["bought"][symbol]:
                signals.append({
                    "symbol": symbol,
                    "signal": Signal.BUY,
                    "quantity": self.position_size,
                    "order_type": "market",
                    "reason": "Buy and hold - initial purchase"
                })
                self.state["bought"][symbol] = True
        
        return signals
    
    def on_stop(self) -> None:
        """
        Optionally sell positions when strategy stops.
        
        TODO:
        - If sell_on_stop is True, generate sell signals
        - Close all positions
        """
        print(f"[{self.name}] Stopping Buy and Hold Strategy")
        
        # TODO: Implement sell logic if sell_on_stop is True
        # if self.sell_on_stop:
        #     for symbol in self.symbols:
        #         if self.state["bought"][symbol]:
        #             # Generate sell signal
        #             pass
        
        self.is_running = False
