#!/usr/bin/env python
"""
Example: Run a trading strategy with paper trading.

This script demonstrates how to run a trading strategy locally
using the strategy runner and paper broker.

Usage:
    python run_strategy_example.py
"""

import time
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from engine import StrategyRunner, BuyAndHoldStrategy, MovingAverageCrossoverStrategy
from services.broker import PaperBroker
from storage import get_db, StorageService


def main():
    """Run a simple buy and hold strategy."""
    print("=" * 60)
    print("StocksBot Strategy Runner Example")
    print("=" * 60)
    
    # Setup paper broker with $100,000 starting balance
    print("\n1. Setting up paper broker...")
    broker = PaperBroker(starting_balance=100000.0)
    print(f"   Starting balance: ${broker.balance:,.2f}")
    
    # Setup storage (optional)
    print("\n2. Setting up storage...")
    storage = None  # Storage is optional
    # Note: To enable storage, run database migrations first:
    #   cd backend && alembic upgrade head
    # Then uncomment the following:
    # try:
    #     db = next(get_db())
    #     storage = StorageService(db)
    #     print("   Storage enabled (trades will be recorded)")
    # except Exception as e:
    #     print(f"   Storage not available: {e}")
    #     storage = None
    print("   Running without storage (for demo purposes)")
    
    # Create strategy runner
    print("\n3. Creating strategy runner...")
    runner = StrategyRunner(
        broker=broker,
        storage_service=storage,
        tick_interval=5.0  # Tick every 5 seconds
    )
    print("   Tick interval: 5 seconds")
    
    # Configure and load strategy
    print("\n4. Configuring strategy...")
    config = {
        "name": "Buy and Hold Example",
        "symbols": ["AAPL", "MSFT"],
        "position_size": 10,
        "sell_on_stop": False
    }
    
    strategy = BuyAndHoldStrategy(config)
    runner.load_strategy(strategy)
    
    print(f"   Strategy: {config['name']}")
    print(f"   Symbols: {config['symbols']}")
    print(f"   Position size: {config['position_size']} shares")
    
    # Setup signal callback to monitor execution
    def on_signal(strategy, signal_data, order):
        print(f"\n   📊 Signal executed!")
        print(f"      Strategy: {strategy.get_name()}")
        print(f"      Symbol: {signal_data['symbol']}")
        print(f"      Action: {signal_data['signal'].value.upper()}")
        print(f"      Quantity: {signal_data['quantity']}")
        print(f"      Order ID: {order['id']}")
    
    runner.on_signal_callback = on_signal
    
    # Start the runner
    print("\n5. Starting strategy runner...")
    print("   (Press Ctrl+C to stop)")
    print("-" * 60)
    
    success = runner.start()
    if not success:
        print("❌ Failed to start runner")
        return
    
    print("✅ Runner started successfully")
    
    try:
        # Run for 30 seconds
        duration = 30
        print(f"\n   Running for {duration} seconds...")
        
        for i in range(duration):
            time.sleep(1)
            if (i + 1) % 5 == 0:
                print(f"   ... {i + 1}s elapsed")
        
        print(f"\n   {duration}s complete")
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    
    finally:
        # Stop the runner
        print("\n6. Stopping strategy runner...")
        runner.stop()
        print("✅ Runner stopped")
        
        # Show summary
        print("\n" + "=" * 60)
        print("Summary")
        print("=" * 60)
        
        # Show broker orders
        orders = broker.get_orders()
        print(f"\nOrders executed: {len(orders)}")
        for order in orders:
            print(f"  - {order['symbol']}: {order['side'].upper()} {order['quantity']} @ {order['type']}")
        
        # Show account info
        account = broker.get_account_info()
        print(f"\nAccount balance: ${account['cash']:,.2f}")
        print(f"Account equity: ${account['equity']:,.2f}")
        
        print("\n" + "=" * 60)
        print("Done!")
        print("=" * 60)


if __name__ == "__main__":
    main()
