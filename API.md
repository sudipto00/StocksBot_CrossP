# StocksBot API Documentation

This document describes the backend HTTP/WebSocket contract currently implemented by `backend/app.py` + `backend/api/routes.py`.

## Base URL

- Development: `http://127.0.0.1:8000`
- OpenAPI schema: `GET /openapi.json`
- Interactive docs: `GET /docs`

## Authentication

API-key auth is optional and disabled by default.

### Enable auth

Set backend env vars:

```bash
STOCKSBOT_API_KEY_AUTH_ENABLED=true
STOCKSBOT_API_KEY=replace-with-strong-key
```

### Send credentials

Use one of:

- `X-API-Key: <key>`
- `Authorization: Bearer <key>`

### Auth behavior

- If auth is enabled and key is missing/mismatched: `401 Unauthorized`
- If auth is enabled but no key configured server-side: `503`
- Public routes that stay open:
  - `GET /`
  - `GET /status`
  - docs/openapi routes (`/docs`, `/redoc`, `/openapi.json`)
- WebSocket `GET /ws/system-health` also enforces API key when auth is enabled (unauthorized close code `4401`).

## Idempotency Support

These endpoints support `X-Idempotency-Key`:

- `POST /config`
- `POST /runner/start`
- `POST /runner/stop`
- `POST /portfolio/selloff`
- `POST /safety/kill-switch`
- `POST /safety/panic-stop`

## Endpoint Catalog

### Health

- `GET /` - root info
- `GET /status` - service health

### Config and Broker

- `GET /config`
- `POST /config`
- `GET /broker/credentials/status`
- `POST /broker/credentials`
- `GET /broker/account`

### Trading

- `GET /positions`
- `GET /orders`
- `POST /orders`

### Notifications

- `POST /notifications`
- `GET /notifications/summary/preferences`
- `POST /notifications/summary/preferences`
- `POST /notifications/summary/send-now`

### Strategy

- `GET /strategies`
- `POST /strategies`
- `GET /strategies/{strategy_id}`
- `PUT /strategies/{strategy_id}`
- `DELETE /strategies/{strategy_id}`
- `GET /strategies/{strategy_id}/config`
- `PUT /strategies/{strategy_id}/config`
- `GET /strategies/{strategy_id}/metrics`
- `POST /strategies/{strategy_id}/backtest`
- `POST /strategies/{strategy_id}/tune`

### Runner, Safety, Reconciliation

- `GET /runner/status`
- `POST /runner/start`
- `POST /runner/stop`
- `POST /portfolio/selloff`
- `GET /safety/status`
- `GET /safety/preflight`
- `POST /safety/kill-switch`
- `POST /safety/panic-stop`
- `POST /reconciliation/run`

### Audit and Maintenance

- `GET /audit/logs`
- `GET /audit/trades`
- `GET /maintenance/storage`
- `POST /maintenance/cleanup`
- `POST /maintenance/reset-audit-data`

### Analytics

- `GET /analytics/portfolio`
- `GET /analytics/summary`

### Screener, Preferences, Budget

- `GET /screener/stocks`
- `GET /screener/etfs`
- `GET /screener/all`
- `GET /screener/preset`
- `GET /screener/chart/{symbol}`
- `GET /risk-profiles`
- `GET /preferences`
- `POST /preferences`
- `GET /preferences/recommendation`
- `GET /budget/status`
- `POST /budget/update`

### WebSocket

- `WS /ws/system-health`

## Important Behavior Notes

### `GET /positions`

- Not static stub data.
- Tries live broker positions first.
- Falls back to local persisted open positions if broker is unavailable.

### `GET /orders`

- Currently returns development stub orders.
- This endpoint is not yet wired to full broker/history retrieval.

### `POST /orders`

- Real execution path.
- Validates symbol/order params, broker connectivity, market-open state, kill switch, tradability, buying power, and balance-adjusted risk limits.
- Supports order types: `market`, `limit`, `stop`, `stop_limit`.

### Notification endpoints

- `POST /notifications` is a placeholder queue/log response.
- Summary preferences endpoints persist settings and validate recipient format.
- `POST /notifications/summary/send-now` performs real delivery:
  - email via SMTP (`STOCKSBOT_SMTP_*` vars)
  - SMS via Twilio (`STOCKSBOT_TWILIO_*` vars)
  - returns `success=false` with explicit error text when transport config or provider call fails
- Automatic summary scheduler is enabled by default:
  - `STOCKSBOT_SUMMARY_SCHEDULER_ENABLED=true`
  - `STOCKSBOT_SUMMARY_SCHEDULER_POLL_SECONDS=60`
  - `STOCKSBOT_SUMMARY_SCHEDULER_RETRY_SECONDS=1800`
  - sends one summary per completed daily/weekly UTC period without duplicates across restart

## Core Request/Response Examples

### `GET /config`

```json
{
  "environment": "development",
  "trading_enabled": false,
  "paper_trading": true,
  "max_position_size": 10000.0,
  "risk_limit_daily": 500.0,
  "tick_interval_seconds": 60.0,
  "streaming_enabled": false,
  "log_directory": "./logs",
  "audit_export_directory": "./audit_exports",
  "log_retention_days": 30,
  "audit_retention_days": 90,
  "broker": "paper"
}
```

### `POST /broker/credentials`

```json
{
  "mode": "paper",
  "api_key": "YOUR_ALPACA_KEY",
  "secret_key": "YOUR_ALPACA_SECRET"
}
```

### `GET /broker/account`

```json
{
  "broker": "paper",
  "mode": "paper",
  "connected": true,
  "using_runtime_credentials": true,
  "currency": "USD",
  "cash": 100000.0,
  "equity": 100000.0,
  "buying_power": 200000.0,
  "message": "Account fetched successfully"
}
```

### `POST /orders`

```json
{
  "symbol": "AAPL",
  "side": "buy",
  "type": "stop_limit",
  "quantity": 5,
  "price": 185.0
}
```

Success response shape:

```json
{
  "id": "123",
  "symbol": "AAPL",
  "side": "buy",
  "type": "stop_limit",
  "quantity": 5.0,
  "price": 185.0,
  "status": "submitted",
  "filled_quantity": 0.0,
  "avg_fill_price": null,
  "created_at": "2026-02-13T18:12:00.000000",
  "updated_at": "2026-02-13T18:12:00.000000"
}
```

### `GET /screener/all`

Query params include:

- `asset_type`: `stock|etf|both`
- `screener_mode`: `most_active|preset`
- `limit`: `10..200`
- `page`, `page_size`
- guardrails:
  - `min_dollar_volume`
  - `max_spread_bps`
  - `max_sector_weight_pct`
  - `auto_regime_adjust`

Response includes pagination metadata and applied guardrails.

### `GET /screener/chart/{symbol}`

Returns historical points with SMA overlays and indicator levels.

Params:

- `days` (`30..1000`)
- `take_profit_pct`
- `trailing_stop_pct`
- `atr_stop_mult`
- `zscore_entry_threshold`
- `dip_buy_threshold_pct`

### `POST /maintenance/reset-audit-data`

Hard reset for test cycles.

Query flags:

- `clear_event_logs`
- `clear_trade_history`
- `clear_log_files`
- `clear_audit_export_files`

Returns row/file deletion counts. Refuses while runner is `running` or `sleeping`.

## WebSocket: `WS /ws/system-health`

Payload fields include:

- `runner_status`
- `broker_connected`
- `poll_success_count`
- `poll_error_count`
- `last_poll_error`
- `last_successful_poll_at`
- `sleeping`, `sleep_since`, `next_market_open_at`, `last_resume_at`
- `market_session_open`
- `kill_switch_active`
- `last_broker_sync_at`
- `timestamp`

Server pushes every ~5 seconds.

## Common Error Status Codes

- `400` invalid request/validation error
- `401` unauthorized (when API auth enabled)
- `404` resource not found
- `409` conflict (for safety/running state constraints)
- `422` schema validation error
- `500` internal error
- `503` upstream/broker unavailable or auth misconfiguration

## Notes

- Times are ISO-8601 strings.
- Numbers are JSON numeric values.
- CORS is configured for `http://localhost:1420` and `tauri://localhost`.

---

Version: `0.1.0`
Last Updated: `2026-02-13`
