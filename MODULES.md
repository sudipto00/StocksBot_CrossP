# Backend Modules Documentation

This document describes the core backend modules for engine and services.

## Engine Modules

### Strategy Runner (`engine/strategy_runner.py`)

The Strategy Runner manages trading strategy execution and lifecycle.

**Responsibilities:**
- Loading and initializing trading strategies
- Managing strategy lifecycle (start/stop/pause)
- Processing market data and generating signals
- Coordinating with risk manager and order service

**Key Classes:**
- `StrategyRunner`: Main strategy execution engine
- `StrategyStatus`: Enum for strategy status (STOPPED, RUNNING, PAUSED, ERROR)

**Usage Example:**
```python
from engine.strategy_runner import StrategyRunner

runner = StrategyRunner()
runner.load_strategy("my-strategy", {"param1": "value1"})
runner.start_strategy("my-strategy")
# ... later ...
runner.stop_strategy("my-strategy")
```

**TODO Items:**
- Implement strategy loading from config/file
- Add market data integration
- Implement signal generation logic
- Add position management integration

---

### Risk Manager (`engine/risk_manager.py`)

The Risk Manager handles all trading risk management and position limits.

**Responsibilities:**
- Validating trade requests against risk limits
- Monitoring portfolio exposure
- Tracking drawdown and losses
- Enforcing position limits
- Emergency shutdown (circuit breaker)

**Key Classes:**
- `RiskManager`: Main risk management system

**Usage Example:**
```python
from engine.risk_manager import RiskManager

risk_mgr = RiskManager(
    max_position_size=10000.0,
    daily_loss_limit=500.0,
    max_portfolio_exposure=100000.0
)

# Validate an order
is_valid, error = risk_mgr.validate_order("AAPL", 100, 150.0, current_positions)
if is_valid:
    # Submit order
    pass
else:
    print(f"Order rejected: {error}")
```

**TODO Items:**
- Implement comprehensive order validation
- Add portfolio exposure tracking
- Implement volatility-based position sizing
- Add real-time risk metrics calculation

---

## Services Modules

### Portfolio Service (`services/portfolio.py`)

The Portfolio Service manages portfolio state, positions, and P&L tracking.

**Responsibilities:**
- Tracking current positions
- Calculating P&L (realized and unrealized)
- Portfolio value calculations
- Position history
- Performance analytics

**Key Classes:**
- `PortfolioService`: Main portfolio management service

**Usage Example:**
```python
from services.portfolio import PortfolioService

portfolio = PortfolioService()

# Update a position
portfolio.update_position("AAPL", 100, 150.0, "long")

# Get all positions
positions = portfolio.get_positions()

# Calculate portfolio value
current_prices = {"AAPL": 155.0, "MSFT": 310.0}
total_value = portfolio.calculate_portfolio_value(current_prices)

# Get summary
summary = portfolio.get_portfolio_summary(current_prices)
```

**TODO Items:**
- Integrate with broker API for real positions
- Implement persistent storage (database)
- Add real-time market data for valuations
- Implement realized P&L tracking

---

### Broker Service (`services/broker.py`)

The Broker Service provides an abstract interface for broker integrations.

**Responsibilities:**
- Connecting to broker APIs
- Submitting and managing orders
- Fetching positions and account info
- Getting market data

**Key Classes:**
- `BrokerInterface`: Abstract base class for all broker implementations
- `PaperBroker`: Paper trading implementation (no real money)
- `OrderSide`, `OrderType`, `OrderStatus`: Enums for order management

**Usage Example:**
```python
from services.broker import PaperBroker, OrderSide, OrderType

# Create paper broker
broker = PaperBroker(starting_balance=100000.0)
broker.connect()

# Get account info
account = broker.get_account_info()
print(f"Cash: ${account['cash']}")

# Submit an order
order = broker.submit_order(
    symbol="AAPL",
    side=OrderSide.BUY,
    order_type=OrderType.MARKET,
    quantity=100
)

# Get positions
positions = broker.get_positions()

# Get orders
orders = broker.get_orders()

# Cancel an order
broker.cancel_order(order['id'])
```

**Implementing a New Broker:**

To add a new broker (e.g., Alpaca, Interactive Brokers), create a class that inherits from `BrokerInterface`:

```python
from services.broker import BrokerInterface

class AlpacaBroker(BrokerInterface):
    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        # ... initialize Alpaca client
    
    def connect(self) -> bool:
        # Implement connection logic
        pass
    
    # Implement all other abstract methods
    # ...
```

**TODO Items:**
- Implement Alpaca API integration
- Implement Interactive Brokers integration
- Add margin requirements support
- Add historical data fetching
- Improve paper trading simulation

---

## Module Interactions

```
┌─────────────────┐
│ Strategy Runner │
└────────┬────────┘
         │
         ├──> Market Data Processing
         │
         v
    ┌────────────────┐      ┌──────────────┐
    │  Risk Manager  │<────>│   Portfolio  │
    └────────┬───────┘      └──────────────┘
             │
             v
    ┌────────────────┐
    │     Broker     │
    └────────────────┘
```

**Flow:**
1. Strategy Runner processes market data and generates signals
2. Signal triggers order validation through Risk Manager
3. Risk Manager checks against portfolio state and limits
4. If approved, order is submitted via Broker interface
5. Portfolio is updated when order fills

---

## Testing

All modules have comprehensive unit tests in `tests/test_engine_services.py`.

Run tests:
```bash
cd backend
pytest tests/test_engine_services.py -v
```

Current test coverage:
- Strategy Runner: 3 tests
- Risk Manager: 4 tests
- Portfolio Service: 5 tests
- Broker Interface: 8 tests

**Total: 20 module tests (all passing)**

---

## Future Enhancements

1. **Strategy Runner:**
   - Strategy hot-reloading
   - Multiple strategy instances
   - Strategy performance metrics
   - Backtesting integration

2. **Risk Manager:**
   - Real-time VaR calculation
   - Correlation-based limits
   - Scenario analysis
   - Stress testing

3. **Portfolio Service:**
   - Multi-account support
   - Options and derivatives
   - Tax lot tracking
   - Performance attribution

4. **Broker Service:**
   - WebSocket streaming data
   - Options trading support
   - Fractional shares
   - Crypto trading

---

**Last Updated:** 2024
