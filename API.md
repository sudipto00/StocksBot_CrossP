# StocksBot API Documentation

This document describes the REST API endpoints provided by the StocksBot backend service.

## Base URL

- Development: `http://127.0.0.1:8000`
- Production: Configured via environment variables

## Authentication

TODO: Authentication not yet implemented. All endpoints are currently open.

---

## Health & Status

### GET /

Root endpoint.

**Response:**
```json
{
  "message": "StocksBot API"
}
```

### GET /status

Health check endpoint. Returns the current status of the backend service.

**Response:**
```json
{
  "status": "running",
  "service": "StocksBot Backend",
  "version": "0.1.0"
}
```

---

## Configuration

### GET /config

Get the current application configuration.

**Response:**
```json
{
  "environment": "development",
  "trading_enabled": false,
  "paper_trading": true,
  "max_position_size": 10000.0,
  "risk_limit_daily": 500.0,
  "broker": "paper"
}
```

**Fields:**
- `environment` (string): Current environment (development/staging/production)
- `trading_enabled` (boolean): Whether trading is enabled
- `paper_trading` (boolean): Whether in paper trading mode
- `max_position_size` (number): Maximum position size in dollars
- `risk_limit_daily` (number): Daily risk limit in dollars
- `broker` (string): Broker name

### POST /config

Update application configuration.

**Request Body:**
```json
{
  "trading_enabled": true,
  "paper_trading": false,
  "max_position_size": 15000.0,
  "risk_limit_daily": 1000.0
}
```

All fields are optional. Only provided fields will be updated.

**Response:**
Returns the updated configuration (same format as GET /config).

---

## Positions

### GET /positions

Get current portfolio positions.

**Response:**
```json
{
  "positions": [
    {
      "symbol": "AAPL",
      "side": "long",
      "quantity": 100,
      "avg_entry_price": 150.00,
      "current_price": 155.00,
      "unrealized_pnl": 500.00,
      "unrealized_pnl_percent": 3.33,
      "cost_basis": 15000.00,
      "market_value": 15500.00
    }
  ],
  "total_value": 31000.00,
  "total_pnl": 1000.00,
  "total_pnl_percent": 3.33
}
```

**Fields:**
- `positions` (array): List of position objects
  - `symbol` (string): Stock ticker symbol
  - `side` (string): Position side ("long" or "short")
  - `quantity` (number): Number of shares
  - `avg_entry_price` (number): Average entry price per share
  - `current_price` (number): Current market price
  - `unrealized_pnl` (number): Unrealized profit/loss
  - `unrealized_pnl_percent` (number): P&L as percentage
  - `cost_basis` (number): Total cost basis
  - `market_value` (number): Current market value
- `total_value` (number): Total portfolio value
- `total_pnl` (number): Total unrealized P&L
- `total_pnl_percent` (number): Total P&L percentage

**Status:** Currently returns stub data. Real integration pending.

---

## Orders

### GET /orders

Get order history and active orders.

**Response:**
```json
{
  "orders": [
    {
      "id": "order-001",
      "symbol": "AAPL",
      "side": "buy",
      "type": "limit",
      "quantity": 100,
      "price": 150.00,
      "status": "filled",
      "filled_quantity": 100,
      "avg_fill_price": 150.00,
      "created_at": "2024-01-01T12:00:00Z",
      "updated_at": "2024-01-01T12:01:00Z"
    }
  ],
  "total_count": 2
}
```

**Fields:**
- `orders` (array): List of order objects
  - `id` (string): Order ID
  - `symbol` (string): Stock ticker symbol
  - `side` (string): Order side ("buy" or "sell")
  - `type` (string): Order type ("market", "limit", "stop", "stop_limit")
  - `quantity` (number): Order quantity
  - `price` (number, optional): Limit/stop price
  - `status` (string): Order status (pending/submitted/filled/partially_filled/cancelled/rejected)
  - `filled_quantity` (number): Filled quantity
  - `avg_fill_price` (number, optional): Average fill price
  - `created_at` (string): ISO datetime of creation
  - `updated_at` (string): ISO datetime of last update
- `total_count` (number): Total order count

**Status:** Currently returns stub data. Real integration pending.

### POST /orders

Create a new order.

**Request Body:**
```json
{
  "symbol": "AAPL",
  "side": "buy",
  "type": "limit",
  "quantity": 100,
  "price": 150.00
}
```

**Fields:**
- `symbol` (string, required): Stock ticker symbol (1-10 characters)
- `side` (string, required): Order side ("buy" or "sell")
- `type` (string, required): Order type ("market", "limit", "stop", "stop_limit")
- `quantity` (number, required): Order quantity (> 0)
- `price` (number, optional): Limit/stop price (required for limit/stop orders, > 0)

**Response:**
```json
{
  "message": "Order placeholder created for 100 shares of AAPL",
  "note": "This is a stub endpoint. Real order execution not implemented."
}
```

**Status:** Placeholder endpoint. Does not execute real trades.

---

## Notifications

### POST /notifications

Request a notification to be sent to the user.

**Request Body:**
```json
{
  "title": "Trade Executed",
  "message": "Bought 100 shares of AAPL at $150.00",
  "severity": "success"
}
```

**Fields:**
- `title` (string, required): Notification title (max 100 characters)
- `message` (string, required): Notification message (max 500 characters)
- `severity` (string, optional): Severity level ("info", "warning", "error", "success"). Default: "info"

**Response:**
```json
{
  "success": true,
  "message": "Notification queued (placeholder)"
}
```

**Status:** Placeholder endpoint. Notifications not yet wired to system tray.

---

## Error Responses

All endpoints may return error responses in the following format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

Common HTTP status codes:
- `200` - Success
- `400` - Bad Request (invalid input)
- `404` - Not Found
- `422` - Validation Error (Pydantic validation failed)
- `500` - Internal Server Error

---

## Data Models

### Enumerations

**OrderSide:**
- `buy`
- `sell`

**OrderType:**
- `market`
- `limit`
- `stop`
- `stop_limit`

**OrderStatus:**
- `pending`
- `submitted`
- `filled`
- `partially_filled`
- `cancelled`
- `rejected`

**PositionSide:**
- `long`
- `short`

**NotificationSeverity:**
- `info`
- `warning`
- `error`
- `success`

---

## Future Endpoints (Planned)

The following endpoints are planned for future implementation:

- `GET /strategies` - List available trading strategies
- `POST /strategies/{id}/start` - Start a strategy
- `POST /strategies/{id}/stop` - Stop a strategy
- `GET /audit` - Get audit logs
- `GET /analytics` - Get portfolio analytics
- `GET /market-data/{symbol}` - Get real-time market data
- `WebSocket /ws` - Real-time updates

---

## Notes

- All timestamps are in ISO 8601 format (UTC)
- Numeric values use standard JSON number format
- All responses use `application/json` content type
- CORS is enabled for `http://localhost:1420` and `tauri://localhost`

---

**Version:** 0.1.0  
**Last Updated:** 2024
