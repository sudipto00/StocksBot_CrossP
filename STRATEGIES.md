# Strategy Development Guide

This guide explains how to create and run trading strategies in StocksBot.

## Table of Contents

- [Overview](#overview)
- [Strategy Interface](#strategy-interface)
- [Creating a Strategy](#creating-a-strategy)
- [Running Strategies](#running-strategies)
- [Sample Strategies](#sample-strategies)
- [Best Practices](#best-practices)

## Overview

StocksBot uses a plugin-based strategy system. All strategies implement the `StrategyInterface` abstract base class, which provides:

- **Lifecycle Management**: `on_start()`, `on_tick()`, `on_stop()`
- **Market Data Access**: Receive current market data on each tick
- **Signal Generation**: Return buy/sell signals for execution
- **Paper Trading**: Execute trades through a simulated broker
- **State Management**: Maintain strategy state between ticks

## Strategy Interface

All strategies must implement the `StrategyInterface`:

```python
from engine.strategy_interface import StrategyInterface, Signal

class MyStrategy(StrategyInterface):
    def on_start(self) -> None:
        """Called when strategy starts."""
        pass
    
    def on_tick(self, market_data: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Called on each scheduler tick with current market data."""
        return []  # Return list of signals
    
    def on_stop(self) -> None:
        """Called when strategy stops."""
        pass
```

### Lifecycle Methods

#### `__init__(config: Dict[str, Any])`

Initialize your strategy with configuration:

```python
def __init__(self, config: Dict[str, Any]):
    super().__init__(config)
    
    # Extract configuration
    self.short_window = config.get("short_window", 10)
    self.long_window = config.get("long_window", 50)
    
    # Initialize state
    self.state = {
        "price_history": {},
        "positions": {}
    }
```

#### `on_start() -> None`

Called once when the strategy starts. Use this to:
- Initialize data structures
- Load historical data
- Set up indicators
- Prepare strategy state

```python
def on_start(self) -> None:
    print(f"[{self.name}] Starting strategy")
    
    for symbol in self.symbols:
        self.state["price_history"][symbol] = []
    
    self.is_running = True
```

#### `on_tick(market_data) -> List[Dict]`

Called on each scheduler tick with current market data. This is where your strategy logic lives.

**Input**: Market data dictionary
```python
{
    "AAPL": {
        "price": 150.0,
        "volume": 1000000,
        "timestamp": "2026-02-09T12:00:00"
    },
    "MSFT": {
        "price": 300.0,
        "volume": 500000,
        "timestamp": "2026-02-09T12:00:00"
    }
}
```

**Output**: List of signals
```python
[
    {
        "symbol": "AAPL",
        "signal": Signal.BUY,
        "quantity": 100,
        "order_type": "market",  # or "limit"
        "price": 150.0,  # optional, for limit orders
        "reason": "Moving average crossover"  # optional
    }
]
```

#### `on_stop() -> None`

Called when the strategy stops. Use this to:
- Close open positions (if configured)
- Save strategy state
- Clean up resources

```python
def on_stop(self) -> None:
    print(f"[{self.name}] Stopping strategy")
    
    # Optionally close positions
    # for symbol in self.state["positions"]:
    #     signals.append(close_signal)
    
    self.is_running = False
```

## Creating a Strategy

### Step 1: Create Strategy Class

Create a new Python file in `backend/engine/strategies.py` or a separate module:

```python
from typing import Dict, List, Any
from engine.strategy_interface import StrategyInterface, Signal


class MyCustomStrategy(StrategyInterface):
    """
    My custom trading strategy.
    
    Strategy Logic:
    - Describe your strategy logic here
    - Entry conditions
    - Exit conditions
    - Risk management
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        # Extract config
        self.threshold = config.get("threshold", 0.02)
        self.position_size = config.get("position_size", 100)
        
        # Initialize state
        self.state = {}
    
    def on_start(self) -> None:
        """Initialize strategy."""
        self.is_running = True
    
    def on_tick(self, market_data: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process market data and generate signals."""
        signals = []
        
        for symbol in self.symbols:
            if symbol not in market_data:
                continue
            
            data = market_data[symbol]
            price = data.get("price", 0)
            
            # YOUR STRATEGY LOGIC HERE
            # Example: Simple threshold-based strategy
            # if price > some_value:
            #     signals.append({
            #         "symbol": symbol,
            #         "signal": Signal.BUY,
            #         "quantity": self.position_size,
            #         "order_type": "market"
            #     })
        
        return signals
    
    def on_stop(self) -> None:
        """Clean up when stopping."""
        self.is_running = False
```

### Step 2: Register Strategy (Optional)

Export your strategy in `backend/engine/__init__.py`:

```python
from engine.strategies import MyCustomStrategy

__all__ = [
    # ... existing exports
    "MyCustomStrategy",
]
```

## Running Strategies

### Using Python Code

```python
from engine import StrategyRunner, MyCustomStrategy
from services.broker import PaperBroker
from storage import get_db, StorageService

# Setup
broker = PaperBroker(starting_balance=100000.0)
db = next(get_db())
storage = StorageService(db)

# Create runner
runner = StrategyRunner(
    broker=broker,
    storage_service=storage,
    tick_interval=60.0  # 60 seconds between ticks
)

# Create and load strategy
config = {
    "name": "My Strategy",
    "symbols": ["AAPL", "MSFT"],
    "threshold": 0.02,
    "position_size": 100
}
strategy = MyCustomStrategy(config)
runner.load_strategy(strategy)

# Start runner
runner.start()

# ... let it run ...

# Stop runner
runner.stop()
```

### Configuration Options

**Runner Configuration:**
- `tick_interval`: Seconds between strategy ticks (default: 60.0)
- `broker`: Broker instance (use `PaperBroker` for simulation)
- `storage_service`: Optional storage for recording trades

**Strategy Configuration:**
- `name`: Strategy name (required)
- `symbols`: List of symbols to trade (required)
- Custom parameters specific to your strategy

### Running from CLI (Example)

Create a script like `run_strategy.py`:

```python
#!/usr/bin/env python
"""
Run a trading strategy.
"""
import time
from engine import StrategyRunner, BuyAndHoldStrategy
from services.broker import PaperBroker

def main():
    # Create paper broker
    broker = PaperBroker(starting_balance=100000.0)
    
    # Create runner
    runner = StrategyRunner(broker=broker, tick_interval=5.0)
    
    # Configure strategy
    config = {
        "name": "Buy and Hold",
        "symbols": ["AAPL", "MSFT"],
        "position_size": 50
    }
    
    # Load strategy
    strategy = BuyAndHoldStrategy(config)
    runner.load_strategy(strategy)
    
    # Start runner
    print("Starting strategy runner...")
    runner.start()
    
    try:
        # Run for 60 seconds
        time.sleep(60)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        runner.stop()
        print("Runner stopped")

if __name__ == "__main__":
    main()
```

Run it:
```bash
cd backend
python run_strategy.py
```

## Sample Strategies

### 1. Buy and Hold Strategy

Simple strategy that buys symbols once and holds them:

```python
from engine.strategies import BuyAndHoldStrategy

config = {
    "name": "Buy and Hold",
    "symbols": ["AAPL", "MSFT", "GOOGL"],
    "position_size": 100,
    "sell_on_stop": False  # Keep positions when stopped
}

strategy = BuyAndHoldStrategy(config)
```

### 2. Moving Average Crossover (Stub)

Example MA crossover strategy (implementation is TODO):

```python
from engine.strategies import MovingAverageCrossoverStrategy

config = {
    "name": "MA Crossover",
    "symbols": ["AAPL"],
    "short_window": 10,
    "long_window": 50,
    "position_size": 100
}

strategy = MovingAverageCrossoverStrategy(config)
```

**Note**: The MA Crossover strategy is a stub with TODOs. You need to implement:
- Price history tracking
- Moving average calculation
- Crossover detection
- Position management

## Best Practices

### 1. Strategy State Management

Store state in `self.state` dictionary:

```python
self.state = {
    "price_history": {},  # Historical data
    "positions": {},       # Current positions
    "indicators": {},      # Calculated indicators
    "signals": []          # Signal history
}
```

### 2. Error Handling

Always handle errors gracefully:

```python
def on_tick(self, market_data):
    signals = []
    
    try:
        # Your strategy logic
        pass
    except Exception as e:
        print(f"[{self.name}] Error: {e}")
        return []  # Return empty signals on error
    
    return signals
```

### 3. Position Tracking

Track your positions to avoid duplicate orders:

```python
if symbol not in self.state["positions"] or not self.state["positions"][symbol]:
    # No position yet, safe to buy
    signals.append(buy_signal)
    self.state["positions"][symbol] = True
```

### 4. Paper Trading

The runner automatically executes signals through the paper broker:
- Orders are simulated (no real money)
- Market data is simulated (placeholder prices)
- Trades are recorded in storage (if enabled)

### 5. Testing

Always test your strategy:

```python
import pytest
from engine.strategies import MyCustomStrategy

def test_my_strategy():
    config = {"name": "Test", "symbols": ["AAPL"]}
    strategy = MyCustomStrategy(config)
    
    # Test initialization
    assert strategy.name == "Test"
    
    # Test lifecycle
    strategy.on_start()
    assert strategy.is_running == True
    
    # Test tick
    market_data = {"AAPL": {"price": 150.0}}
    signals = strategy.on_tick(market_data)
    assert isinstance(signals, list)
    
    # Test stop
    strategy.on_stop()
    assert strategy.is_running == False
```

### 6. Logging

Use print statements for debugging (will be visible in console):

```python
print(f"[{self.name}] Generated {len(signals)} signals")
print(f"[{self.name}] Current price for {symbol}: {price}")
```

## Advanced Topics

### Multiple Strategies

Run multiple strategies simultaneously:

```python
runner = StrategyRunner(broker=broker)

# Load multiple strategies
runner.load_strategy(strategy1)
runner.load_strategy(strategy2)
runner.load_strategy(strategy3)

# All will run on same tick interval
runner.start()
```

### Signal Callbacks

Register a callback to monitor signal execution:

```python
def on_signal(strategy, signal_data, order):
    print(f"Strategy {strategy.name} generated signal: {signal_data}")
    print(f"Executed order: {order}")

runner.on_signal_callback = on_signal
```

### Custom Tick Intervals

Different strategies can use different runners with different tick intervals:

```python
# Fast runner for day trading
fast_runner = StrategyRunner(broker=broker, tick_interval=5.0)
fast_runner.load_strategy(day_trading_strategy)

# Slow runner for swing trading
slow_runner = StrategyRunner(broker=broker, tick_interval=300.0)
slow_runner.load_strategy(swing_strategy)

fast_runner.start()
slow_runner.start()
```

## Troubleshooting

### Strategy Not Executing

1. Check that strategy is loaded: `runner.get_status()`
2. Verify broker is connected: `broker.is_connected()`
3. Check symbols are in market data
4. Add debug prints in `on_tick()`

### No Signals Generated

1. Verify strategy logic is correct
2. Check market data is being received
3. Ensure conditions for signals are met
4. Add logging to see intermediate values

### Orders Not Executing

1. Check signal format is correct
2. Verify order type is valid ("market", "limit")
3. Check quantity is positive
4. Review broker logs/errors

## Next Steps

1. **Implement Strategy Logic**: Fill in TODOs in sample strategies
2. **Add Real Market Data**: Integrate with market data provider
3. **Implement Position Tracking**: Track positions via broker/storage
4. **Add Risk Management**: Implement risk limits and position sizing
5. **Backtesting**: Add backtesting capabilities
6. **Live Trading**: Connect to real broker (when ready)

## Resources

- `backend/engine/strategy_interface.py` - Strategy interface definition
- `backend/engine/strategies.py` - Sample strategy implementations
- `backend/engine/strategy_runner.py` - Runner implementation
- `backend/tests/test_strategy_runner.py` - Strategy tests
- `backend/services/broker.py` - Broker interface

## Support

For questions or issues:
1. Review test cases in `tests/test_strategy_runner.py`
2. Check existing strategies in `engine/strategies.py`
3. Open an issue on GitHub
