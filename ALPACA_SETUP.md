# Alpaca Integration Setup Guide

This guide covers the current Alpaca integration flow for StocksBot.

## What is Supported

- Alpaca authentication for paper and live modes
- Account snapshot (`cash`, `equity`, `buying_power`)
- Position retrieval
- Order submission via backend execution path:
  - `market`
  - `limit`
  - `stop`
  - `stop_limit`
- Order status polling / reconciliation hooks
- Screener data and symbol chart pull with runtime credentials when available

## Recommended Setup (Desktop Keychain Flow)

The desktop app is Keychain-first.

1. Open **Settings** in StocksBot.
2. Save Paper and/or Live Alpaca keys.
3. Use **Load Keys from Keychain**.
4. Choose **Paper** or **Live** mode.
5. Save settings.
6. Verify broker connectivity from Dashboard/Settings (or `GET /broker/account`).

How it works:

- Tauri stores keys in Keychain service: `com.stocksbot.alpaca`
- Backend receives runtime credentials via `POST /broker/credentials`
- Backend uses runtime credentials first, then environment fallback

## Environment Variable Setup (Fallback / Headless)

Use this when running backend without desktop credential sync.

```bash
# backend/.env
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
ALPACA_PAPER=true   # false for live mode
```

Then run:

```bash
cd backend
python app.py
```

## Verifying Integration

1. `GET /broker/credentials/status`
   - Confirms paper/live key availability and active mode
2. `GET /broker/account`
   - Confirms broker connectivity and balance snapshot
3. `GET /positions`
   - Reads broker positions (falls back to local positions if broker unavailable)
4. `POST /orders`
   - Submits a test paper order

Example order request:

```json
{
  "symbol": "AAPL",
  "side": "buy",
  "type": "limit",
  "quantity": 1,
  "price": 150.0
}
```

## Paper vs Live Guidance

- Start with paper mode until strategy + risk behavior is validated.
- Keep distinct key pairs for paper and live.
- Confirm the selected mode matches the loaded key set.
- Enable kill switch/panic stop familiarity before live sessions.

## Troubleshooting

### 1) “Broker account unavailable”

- Check current mode (paper/live) matches saved keys.
- Re-load keys from Keychain.
- Verify backend is running.
- Verify Alpaca credentials are active in Alpaca dashboard.

### 2) Keychain prompt loops / popups

- Remove stale StocksBot items in Keychain Access:
  - service `com.stocksbot.alpaca`
  - accounts like `paper_api_key`, `paper_secret_key`, `live_api_key`, `live_secret_key`
- Re-save keys from Settings.

### 3) Screener shows load errors

- Confirm backend is running and reachable.
- Confirm valid runtime/env Alpaca keys in selected mode.
- Check `GET /broker/account` first, then refresh Screener.

### 4) Order rejected / validation error

- Market closed or symbol not tradable
- Insufficient buying power
- Price missing for `limit` / `stop` / `stop_limit`
- Kill switch enabled

## Related Docs

- API contract: `API.md`
- Security/auth hardening: `SECURITY.md`
- Runtime operations and maintenance: `OPERATIONS.md`

---

Last Updated: `2026-02-13`
