# Real Trading Logic Implementation

This document describes the implementation of real trading logic execution for StocksBot.

## Overview

The real trading logic implementation replaces the stubbed order execution endpoints with fully functional order processing that:
- Validates orders against account and risk limits
- Submits orders to configured brokers (Paper or Alpaca)
- Persists orders, trades, and positions to the database
- Processes order fills and updates positions
- Maintains backward compatibility with existing API contracts

## Architecture

### Components Added

1. **OrderExecutionService** (`backend/services/order_execution.py`)
   - Core service orchestrating the order lifecycle
   - Validates orders against account limits and risk rules
   - Submits orders to broker interfaces
   - Processes fills and updates positions
   - Creates audit logs for all order events

2. **Enhanced PaperBroker** (`backend/services/broker.py`)
   - Market orders now fill immediately at simulated price
   - Proper fill tracking with `filled_quantity` and `avg_fill_price`
   - Balance tracking for paper trading account

3. **Updated API Endpoints** (`backend/api/routes.py`)
   - POST `/orders` now executes real trades
   - Proper error handling (400 for validation, 503 for broker errors)
   - Returns complete order response with status and fill information

### Order Execution Flow

```
Client Request (POST /orders)
       ↓
OrderExecutionService.submit_order()
       ↓
1. Validate Order
   - Check quantity > 0
   - Validate price for limit orders
   - Check broker connection
   - Verify buying power (for buy orders)
   - Check position size limits
   - Check risk limits
       ↓
2. Create Order Record (DB)
   - Symbol, side, type, quantity, price
   - Status: PENDING
   - Timestamps
       ↓
3. Submit to Broker
   - Map to broker order types
   - Submit via broker.submit_order()
   - Get broker response with external ID
       ↓
4. Update Order Record
   - Store external broker ID
   - Update status from broker
   - Set filled_quantity and avg_fill_price (if filled)
       ↓
5. Process Fills (if filled)
   - Create Trade record
   - Update or create Position
   - Calculate P&L for closes
   - Create audit log
       ↓
Return Order Response to Client
```

## Configuration

### Broker Selection

The broker is automatically selected based on environment variables:

**Paper Trading (Default)**:
```bash
# No configuration needed
# PaperBroker is used by default
```

**Alpaca Trading**:
```bash
export ALPACA_API_KEY="your-api-key"
export ALPACA_SECRET_KEY="your-secret-key"
export ALPACA_PAPER=true  # true for paper, false for live
```

### Risk Limits

Configure via the `/config` endpoint or in-memory config:
- `max_position_size`: Maximum position size in dollars (default: $10,000)
- `risk_limit_daily`: Daily risk limit in dollars (default: $500)

## API Changes

### POST /orders

**Before**: Returned stub message
```json
{
  "message": "Order placeholder created for 10 shares of AAPL",
  "note": "This is a stub endpoint. Real order execution not implemented."
}
```

**After**: Returns real order with status
```json
{
  "id": "1",
  "symbol": "AAPL",
  "side": "buy",
  "type": "market",
  "quantity": 10.0,
  "price": null,
  "status": "filled",
  "filled_quantity": 10.0,
  "avg_fill_price": 100.0,
  "created_at": "2024-01-01T12:00:00",
  "updated_at": "2024-01-01T12:00:00.123456"
}
```

### Error Handling

**Validation Errors (400)**:
```json
{
  "detail": "Order value $150000.00 exceeds maximum position size $10000.00"
}
```

**Broker Errors (503)**:
```json
{
  "detail": "Failed to submit order to broker: Not connected to broker"
}
```

## Database Schema

No schema changes were required. The existing models support all functionality:

- **Order**: Tracks orders with external broker IDs and fill information
- **Trade**: Records individual trade executions
- **Position**: Tracks current and historical positions with P&L

## Testing

### Unit Tests

Comprehensive test suite in `backend/tests/test_order_execution.py`:
- OrderExecutionService validation tests
- Order submission tests (market, limit orders)
- Position management tests
- Trade creation tests
- Error handling tests
- API endpoint integration tests

**Run tests**:
```bash
cd backend
pytest tests/test_order_execution.py -v
```

### Manual Testing

1. Start the server:
```bash
cd backend
python app.py
```

2. Submit a market order:
```bash
curl -X POST http://127.0.0.1:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "side": "buy",
    "type": "market",
    "quantity": 10
  }'
```

3. Submit a limit order:
```bash
curl -X POST http://127.0.0.1:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "MSFT",
    "side": "buy",
    "type": "limit",
    "quantity": 5,
    "price": 250.0
  }'
```

4. Test validation:
```bash
curl -X POST http://127.0.0.1:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "side": "buy",
    "type": "market",
    "quantity": 1000
  }'
# Returns: {"detail":"Order value $100000.00 exceeds maximum position size $10000.00"}
```

## Broker Implementations

### PaperBroker

- **Market Orders**: Fill immediately at $100 per share
- **Limit Orders**: Stay pending (fill simulation not implemented)
- **Balance**: Tracks paper balance, starts at $100,000
- **Positions**: Tracked in memory (not persisted between restarts)

### AlpacaBroker

- **Market Orders**: Submit to Alpaca API
- **Limit Orders**: Submit to Alpaca API
- **Stop Orders**: Not yet implemented (returns NotImplementedError)
- **Status**: Mapped from Alpaca status to internal status enum
- **Fills**: Retrieved from Alpaca API

## Future Enhancements

1. **Order Fill Polling**: Background task to poll broker for order status updates
2. **Stop/Stop-Limit Orders**: Implement full support in AlpacaBroker
3. **Fractional Shares**: Support for fractional share trading
4. **Extended Hours**: Support for pre-market and after-hours trading
5. **Advanced Validation**: More sophisticated risk checks and limits
6. **Fill Notifications**: Notify users when orders are filled
7. **Order Cancellation**: API endpoint to cancel pending orders
8. **Position Reconciliation**: Sync positions with broker

## Backward Compatibility

All changes maintain backward compatibility:
- API endpoint paths unchanged
- Request/response schemas compatible
- Existing tests pass (except pre-existing failures)
- No database migrations required

## Security Considerations

1. **API Keys**: Stored in environment variables, never in code
2. **Validation**: All orders validated before submission
3. **Error Handling**: Sensitive broker errors not exposed to clients
4. **Audit Logs**: All order events logged for compliance
5. **Position Limits**: Prevents excessive positions

## Deployment

1. Set environment variables (for Alpaca):
```bash
export ALPACA_API_KEY="your-key"
export ALPACA_SECRET_KEY="your-secret"
export ALPACA_PAPER=true
```

2. Initialize database:
```bash
cd backend
python -c "from storage.database import Base, engine; Base.metadata.create_all(bind=engine)"
```

3. Start the server:
```bash
python app.py
```

## Troubleshooting

### "Not connected to broker"
- Check Alpaca credentials are set correctly
- Verify broker connection in logs
- Ensure ALPACA_API_KEY and ALPACA_SECRET_KEY are not empty

### "Insufficient buying power"
- Check account balance
- Reduce order size
- For PaperBroker, balance starts at $100,000

### Order stays "pending"
- Limit orders in PaperBroker don't auto-fill (by design)
- For AlpacaBroker, check order status on Alpaca dashboard

## Metrics and Monitoring

All order events are logged to audit logs:
- `order_created`: Order submitted
- `order_filled`: Order filled
- `position_opened`: New position created
- `position_closed`: Position closed

Query audit logs:
```python
from storage.service import StorageService
storage = StorageService(db)
logs = storage.get_audit_logs(event_type="order_created")
```
