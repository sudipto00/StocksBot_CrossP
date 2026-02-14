# Notifications Guide

This guide describes the current notification flow in StocksBot.

## Current Notification Channels

1. Desktop system notifications (implemented via Tauri plugin)
2. Summary notifications:
   - manual `send-now` delivery
   - automatic scheduler delivery for completed daily/weekly windows

## Desktop Notification Flow

`ui/src/utils/notifications.ts` invokes Tauri commands in `src-tauri/src/main.rs`:

- `show_notification`
- `get_notification_permission`
- `request_notification_permission`

Severity values:

- `info`
- `warning`
- `error`
- `success`

Behavior:

- UI checks permission first
- If not granted, UI requests permission
- On grant, OS notification is shown

## Summary Notification Preferences (Backend)

Endpoints:

- `GET /notifications/summary/preferences`
- `POST /notifications/summary/preferences`
- `POST /notifications/summary/send-now`

Supported config:

- `enabled` (`true|false`)
- `frequency` (`daily|weekly`)
- `channel` (`email|sms`)
- `recipient` (email address or E.164-like phone)

Validation:

- Recipient required when enabled
- Email channel validates email format
- SMS channel validates phone-like format

### Important

`POST /notifications/summary/send-now` performs real delivery:

- `channel=email` uses SMTP (`smtplib`)
- `channel=sms` uses Twilio REST API

If transport credentials are missing/invalid, the endpoint returns `success=false` with an actionable message and writes an audit error entry.

Automatic scheduler behavior:

- Runs in backend background thread (startup/shutdown managed by FastAPI lifecycle)
- Sends once per completed period and persists checkpoint state to avoid duplicates after restarts
- Daily: sends previous UTC day summary
- Weekly: sends previous UTC week summary
- Failed sends use retry backoff before retrying the same period again

### Required Backend Environment Variables

Enable transport toggle:

- `STOCKSBOT_SUMMARY_NOTIFICATIONS_ENABLED=true` (default `true`)
- `STOCKSBOT_SUMMARY_SCHEDULER_ENABLED=true` (default `true`)
- `STOCKSBOT_SUMMARY_SCHEDULER_POLL_SECONDS=60` (default `60`, minimum effectively `15`)
- `STOCKSBOT_SUMMARY_SCHEDULER_RETRY_SECONDS=1800` (default `1800`)

For email (SMTP):

- `STOCKSBOT_SMTP_HOST`
- `STOCKSBOT_SMTP_PORT` (default `587`)
- `STOCKSBOT_SMTP_USERNAME`
- `STOCKSBOT_SMTP_PASSWORD`
- `STOCKSBOT_SMTP_FROM_EMAIL`
- Optional: `STOCKSBOT_SMTP_USE_TLS` (default `true`), `STOCKSBOT_SMTP_USE_SSL` (default `false`), `STOCKSBOT_SMTP_TIMEOUT_SECONDS`

For SMS (Twilio):

- `STOCKSBOT_TWILIO_ACCOUNT_SID`
- `STOCKSBOT_TWILIO_AUTH_TOKEN`
- `STOCKSBOT_TWILIO_FROM_NUMBER`
- Optional: `STOCKSBOT_TWILIO_TIMEOUT_SECONDS`

## Backend `/notifications` Endpoint

`POST /notifications` exists for request/queue semantics and returns success response, but does not currently push real-time events to UI over websocket.

## Example (Frontend)

```typescript
import { showSuccessNotification } from '../utils/notifications';

await showSuccessNotification(
  'Order Filled',
  'Buy order for AAPL filled successfully'
);
```

## Example (Summary Preferences API)

```json
{
  "enabled": true,
  "frequency": "weekly",
  "channel": "email",
  "recipient": "trading-alerts@example.com"
}
```

## Troubleshooting

### Notifications not appearing

- Confirm OS notification permission for StocksBot
- Verify `get_notification_permission` returns `granted`
- On macOS, check System Settings > Notifications > StocksBot

### Summary send-now says disabled

- Enable summary preferences first via `POST /notifications/summary/preferences`

### Summary recipient validation errors

- Use a valid email for `channel=email`
- Use E.164-like number for `channel=sms` (e.g. `+14155550123`)

## Known Gaps

- `POST /notifications` is still a local placeholder endpoint (not an external push channel)
- No persistent in-app notification center/history UI yet

---

Last Updated: `2026-02-13`
Version: `0.1.0`
