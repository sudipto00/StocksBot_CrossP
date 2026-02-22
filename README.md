# StocksBot - Cross-Platform Trading Desktop Application

StocksBot is a desktop trading app built with Tauri (Rust), React/TypeScript, and a FastAPI backend. It supports paper/live Alpaca credentials via macOS Keychain, strategy-driven execution, stock/ETF screeners, chart overlays, audit trails, and system health monitoring.

## Highlights

- Desktop-first architecture: React UI + Python backend sidecar
- Alpaca credential flow: Keychain-first (paper/live), runtime sync to backend
- Universe controls:
  - Stocks: Most Active (10-200) or Stock Presets
  - ETFs: Preset-driven (Conservative/Balanced/Aggressive)
- Symbol charts with `SMA50` and `SMA250`, plus strategy metric overlays
- Strategy runner with configurable poll interval and optional stream assist
- Off-hours sleep/resume continuity with persisted runner checkpoint state
- Audit + trade history views, CSV/PDF UI exports, maintenance reset/cleanup APIs
- System health visibility (runner/broker/poll error state) and tray summary

## Architecture

```
Tauri App (Rust)
  ├─ React UI (TypeScript)
  ├─ Native integrations (Keychain, notifications, tray)
  └─ FastAPI backend sidecar (Python)
       ├─ strategy runtime
       ├─ broker integration (paper + Alpaca)
       ├─ persistence (SQLite + Alembic)
       └─ audit, screener, analytics APIs
```

## Prerequisites

- Node.js `18+`
- Python `3.10+` (3.12 tested)
- Rust toolchain (`rustup`, cargo)
- Tauri OS prerequisites:
  - macOS: `xcode-select --install`
  - Linux/Windows: see official Tauri prerequisites

## Quick Start

1. Install dependencies

```bash
# from repo root
npm run install:all
```

2. Initialize backend database

```bash
cd backend
cp .env.example .env
alembic upgrade head
```

3. Run in development

```bash
# terminal 1
cd backend
python app.py

# terminal 2 (repo root)
npm run tauri:dev
```

4. In app Settings:
- Save Alpaca Paper and/or Live credentials to Keychain
- Load keys from Keychain
- Pick Paper or Live mode
- Keep Backend Hot Reload OFF for long-running optimizer stability (enable only for backend dev)
- Save settings

## Backend Sidecar Behavior

When you run `npm run tauri:dev`, Tauri attempts to auto-launch `backend/app.py` if backend is not already reachable on `127.0.0.1:8000`. If backend is already running, sidecar launch is skipped.

Production packaging keeps the same sidecar pattern (desktop app + backend process).

## Credentials and Trading Mode

- Desktop app stores Alpaca credentials in Keychain service `com.stocksbot.alpaca`
- Backend uses runtime credentials pushed from desktop flow first
- Backend falls back to env vars (`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_PAPER`) when runtime creds are unavailable
- Paper/Live mode is controlled by app settings (`paper_trading`)

## Optional API-Key Authentication

API auth is optional and disabled by default for local desktop use.

Enable it in backend environment:

```bash
STOCKSBOT_API_KEY_AUTH_ENABLED=true
STOCKSBOT_API_KEY=your-strong-key
```

Then send either header:

- `X-API-Key: <key>`
- `Authorization: Bearer <key>`

Auth is enforced on most endpoints and `/ws/system-health`; public routes (`/`, `/status`, docs/openapi endpoints) remain open.

## Running Checks

Backend tests:

```bash
cd backend
python -m pytest tests/ -q
```

Frontend lint/build:

```bash
cd ui
npm run lint
npm run build
```

Tauri/Rust compile check:

```bash
cd src-tauri
cargo check
```

## Key Runtime Endpoints

- Health: `GET /`, `GET /status`
- Config: `GET /config`, `POST /config`
- Broker: `GET /broker/credentials/status`, `POST /broker/credentials`, `GET /broker/account`
- Trading: `GET /positions`, `GET /orders`, `POST /orders`
- Runner: `GET /runner/status`, `POST /runner/start`, `POST /runner/stop`
- Safety: `GET /safety/status`, `POST /safety/kill-switch`, `POST /safety/panic-stop`
- Screener: `GET /screener/all`, `GET /screener/preset`, `GET /screener/chart/{symbol}`
- Audit: `GET /audit/logs`, `GET /audit/trades`
- Maintenance: `GET /maintenance/storage`, `POST /maintenance/cleanup`, `POST /maintenance/reset-audit-data`
- Realtime: `WS /ws/system-health`

## Background/Tray Behavior

- Closing the main window hides the app (does not quit)
- Tray/menu item allows Show/Hide/Runner toggle/Quit
- Tray summary reflects runner status, broker health, poll errors, and active strategy/universe

## Documentation Index

- API reference: `API.md`
- Alpaca setup details: `ALPACA_SETUP.md`
- Security hardening and auth: `SECURITY.md`
- Runtime operations and maintenance: `OPERATIONS.md`
- Testing/build reference: `TESTING_AND_BUILD.md`
- In-app guided help: Help page inside UI
