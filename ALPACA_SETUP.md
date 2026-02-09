# Alpaca Integration Setup Guide

This guide explains how to set up and use the Alpaca Markets broker integration with StocksBot.

## What is Alpaca?

[Alpaca](https://alpaca.markets/) is a commission-free trading API that allows algorithmic trading of stocks. It offers both paper trading (simulation with fake money) and live trading with real money.

## Prerequisites

1. **Create an Alpaca Account**
   - Go to https://alpaca.markets/
   - Sign up for a free account
   - Complete account verification (required for live trading, not for paper trading)

2. **Get API Keys**
   - For **Paper Trading** (recommended for testing):
     - Navigate to https://app.alpaca.markets/paper/dashboard/overview
     - Click "View" next to "Your API Keys"
     - Copy your API Key and Secret Key
   
   - For **Live Trading** (use with caution):
     - Navigate to https://app.alpaca.markets/live/dashboard/overview
     - Generate live API keys (requires account funding)
     - Copy your API Key and Secret Key

## Configuration

### Option 1: Environment Variables (Recommended)

1. Navigate to the `backend/` directory
2. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

3. Edit `.env` and add your Alpaca credentials:
   ```bash
   # For Paper Trading
   ALPACA_API_KEY=your_paper_api_key_here
   ALPACA_SECRET_KEY=your_paper_secret_key_here
   ALPACA_PAPER=true
   
   # For Live Trading (USE WITH CAUTION!)
   # ALPACA_API_KEY=your_live_api_key_here
   # ALPACA_SECRET_KEY=your_live_secret_key_here
   # ALPACA_PAPER=false
   ```

### Option 2: Direct Configuration in Code

You can also configure Alpaca credentials directly in your code:

```python
from integrations.alpaca_broker import AlpacaBroker

broker = AlpacaBroker(
    api_key="your_api_key",
    secret_key="your_secret_key",
    paper=True  # Set to False for live trading
)
```

## Using the Alpaca Broker

### Basic Usage

```python
from integrations.alpaca_broker import AlpacaBroker
from config import get_settings

# Load settings from environment
settings = get_settings()

# Initialize broker
broker = AlpacaBroker(
    api_key=settings.alpaca_api_key,
    secret_key=settings.alpaca_secret_key,
    paper=settings.alpaca_paper
)

# Connect to Alpaca
if broker.connect():
    print("Connected to Alpaca!")
    
    # Get account information
    account = broker.get_account_info()
    print(f"Buying Power: ${account['buying_power']}")
    
    # Get current positions
    positions = broker.get_positions()
    for pos in positions:
        print(f"{pos['symbol']}: {pos['quantity']} shares")
    
    # Submit a market order (paper trading)
    from services.broker import OrderSide, OrderType
    
    order = broker.submit_order(
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=1
    )
    print(f"Order submitted: {order['id']}")
    
    # Disconnect
    broker.disconnect()
```

### Integration with Strategy Runner

```python
from engine.strategy_runner import StrategyRunner
from integrations.alpaca_broker import AlpacaBroker
from config import get_settings

settings = get_settings()

# Initialize Alpaca broker
broker = AlpacaBroker(
    api_key=settings.alpaca_api_key,
    secret_key=settings.alpaca_secret_key,
    paper=settings.alpaca_paper
)
broker.connect()

# Create strategy runner with Alpaca
runner = StrategyRunner(
    broker=broker,
    tick_interval=60.0  # Run every 60 seconds
)

# Load your strategies
from engine.strategies import BuyAndHoldStrategy

strategy = BuyAndHoldStrategy({
    "name": "AAPL Buy and Hold",
    "symbols": ["AAPL"],
    "position_size": 1
})

runner.load_strategy(strategy)
runner.start()

# Let it run...
# runner.stop() when done
```

## Supported Features

### ✅ Implemented
- Authentication (paper & live)
- Account information retrieval
- Position tracking
- Market data (latest quotes)
- Market order submission
- Limit order submission
- Order status tracking
- Order cancellation

### 🚧 Planned (TODOs in code)
- Stop orders and stop-limit orders
- Advanced order types (bracket, trailing stop, etc.)
- Historical bars/candles data
- Real-time streaming market data
- Fractional shares
- Extended hours trading
- Position reconciliation
- Advanced risk checks

## Security Best Practices

1. **Never commit API keys to git**
   - `.env` file is already in `.gitignore`
   - Use environment variables for production

2. **Start with Paper Trading**
   - Always test strategies with paper trading first
   - Verify behavior before switching to live

3. **Use Live Trading Carefully**
   - Start with small position sizes
   - Monitor closely when going live
   - Set appropriate risk limits

4. **Rotate Keys Regularly**
   - Alpaca allows regenerating API keys
   - Rotate keys if they might be compromised

## Testing

The Alpaca integration includes comprehensive tests with mocked API responses:

```bash
cd backend
pytest tests/test_alpaca_integration.py -v
```

These tests verify:
- Connection handling
- Account info retrieval
- Position management
- Order submission and tracking
- Market data fetching
- Error handling

## Troubleshooting

### "Not connected to Alpaca" Error
- Make sure you called `broker.connect()` before using other methods
- Check that your API keys are correct
- Verify your internet connection

### Authentication Failures
- Verify API keys are correct (no extra spaces)
- Make sure you're using paper keys with `paper=True`
- Check that your Alpaca account is active

### Market Data Issues
- Some symbols may not have quote data outside market hours
- Check that the symbol exists and is supported by Alpaca
- Alpaca provides data for US equities only

### Order Submission Errors
- Verify account has sufficient buying power
- Check that markets are open (or use extended hours)
- Some order types may not be supported yet (see TODOs)

## Resources

- [Alpaca Documentation](https://alpaca.markets/docs/)
- [Alpaca Python SDK](https://github.com/alpacahq/alpaca-py)
- [Alpaca API Reference](https://alpaca.markets/docs/api-references/trading-api/)
- [Paper Trading Dashboard](https://app.alpaca.markets/paper/dashboard/overview)

## Support

For issues related to:
- **Alpaca API**: Contact Alpaca support at https://alpaca.markets/support
- **StocksBot Integration**: Open an issue on GitHub
