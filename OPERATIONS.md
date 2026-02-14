# Operations Runbook

This runbook describes how StocksBot behaves at runtime and how to operate/maintain it safely.

## 1) Runtime Execution Model

- Strategy execution is driven by the backend `StrategyRunner`.
- Runner loop polls every `tick_interval_seconds` (`/config`).
- Optional stream-assist can be enabled (`streaming_enabled`) for faster state updates when broker support exists.
- Polling remains the baseline/fallback mechanism.

## 2) Market Off-Hours Sleep/Resume

Runner automatically transitions based on broker market-session checks:

- When market is closed:
  - runner enters `sleeping` state
  - saves `sleep_since` and `next_market_open_at`
- When market reopens:
  - runner resumes `running`
  - records `last_resume_at` and increments `resume_count`

Sleep continuity is persisted in DB config key `runner_sleep_state`, so restart/relaunch can recover continuity metadata.

## 3) Sync and Health Telemetry

`GET /runner/status` and `WS /ws/system-health` expose:

- runner state (`running/stopped/sleeping`)
- broker connectivity
- `poll_success_count` / `poll_error_count`
- last poll/reconciliation markers
- sleep/resume state markers

WebSocket emits a snapshot approximately every 5 seconds.

## 4) Failure Recovery

- Temporary broker/network failures increment poll error counters and keep runner alive.
- When dependencies recover, successful polls continue without requiring full state reset.
- Reconciliation can be triggered manually with `POST /reconciliation/run`.

## 5) Data Persistence and Continuity

Persisted in SQLite:

- strategies and strategy config
- orders/trades/positions
- runtime config
- trading preferences
- summary notification preferences
- runner sleep checkpoint
- audit events

Not persisted to DB:

- Alpaca API keys (runtime credentials held in memory; desktop stores keys in OS Keychain)

## 6) Storage Paths and Retention

Config fields (`GET/POST /config`):

- `log_directory`
- `audit_export_directory`
- `log_retention_days`
- `audit_retention_days`

`GET /maintenance/storage` returns resolved paths plus quick file inventory.

Housekeeping:

- periodic cleanup runs at most once per hour
- forced cleanup via `POST /maintenance/cleanup`
- cleanup includes old audit rows + old files in log/audit export directories

## 7) Test-Cycle Reset

Use `POST /maintenance/reset-audit-data` for one-click test cleanup:

- optional flags for event rows, trade rows, log files, export files
- endpoint refuses while runner is `running` or `sleeping`

## 8) Safety Operations

- `POST /safety/kill-switch?active=true|false`
  - blocks or allows new order submissions
- `POST /safety/panic-stop`
  - enables kill switch
  - stops runner
  - liquidates open positions
- `POST /portfolio/selloff`
  - explicit liquidation without full panic workflow

## 9) Suggested Operating Procedure

1. Verify `GET /broker/account` is connected in expected paper/live mode.
2. Verify `GET /runner/status` before and after start.
3. Monitor poll success/error counters during sessions.
4. Keep kill switch accessible for emergency blocks.
5. Run cleanup/reset only with runner stopped.

## 10) Known Operational Gaps

- `GET /orders` is still a stub list endpoint.
- Summary email/SMS transport is placeholder queue logic (not guaranteed external delivery transport yet).

---

Last Updated: `2026-02-13`
