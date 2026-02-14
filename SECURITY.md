# Security Guide

This document summarizes the current security posture of StocksBot and recommended hardening steps for production-like use.

## Current Security Controls

### 1) Optional API-Key Authentication (Implemented)

Backend supports API-key auth middleware for HTTP + WebSocket:

- Env flags:
  - `STOCKSBOT_API_KEY_AUTH_ENABLED=true`
  - `STOCKSBOT_API_KEY=<strong-key>`
- Accepted headers:
  - `X-API-Key: <key>`
  - `Authorization: Bearer <key>`
- Applies to all non-public routes and `WS /ws/system-health`
- Public routes kept open: `/`, `/status`, docs/openapi endpoints

### 2) Credential Handling (Implemented)

- Desktop stores Alpaca credentials in OS Keychain (`com.stocksbot.alpaca`).
- Backend runtime credential endpoint keeps key material in memory and does not persist API secrets to DB.
- Environment variable fallback exists for headless/local backend operation.

### 3) Input Validation and Guardrails (Implemented)

- Pydantic request validation across API surface.
- Symbol/order parameter validation.
- Finite-number/range checks for risk/guardrail fields.
- Runtime execution checks (market open, tradable symbol, buying power, kill switch, etc.).

### 4) Safety Controls (Implemented)

- Global kill switch endpoints.
- Panic-stop endpoint that enables kill switch, stops runner, and liquidates positions.
- Reconciliation endpoint to compare local/broker position state.

### 5) Security-Conscious Logging (Implemented)

- Write-request middleware logs request metadata with sensitive fields redacted.
- Credentials/tokens are masked in structured log payload handling.

### 6) CORS and Desktop Scope (Implemented)

- CORS scoped to desktop development origins (`http://localhost:1420`, `tauri://localhost`).

## Recommended Hardening

1. Enable API-key auth outside local-only testing.
2. Use a long random API key and rotate it periodically.
3. Keep live trading keys separate from paper keys.
4. Restrict local machine access (desktop session + Keychain access).
5. Use least-privilege network exposure (avoid broad LAN/public exposure).
6. Keep dependencies up to date and run routine vulnerability scans.

## Known Limitations / Residual Risk

1. No multi-user identity model (desktop app is effectively single-user local trust model).
2. No built-in rate limiting/throttling at HTTP ingress layer.
3. Notification summary email/SMS transport is currently a queue/placeholder hook, not guaranteed external delivery.
4. `GET /orders` currently serves stub data (execution path itself is validated and persisted via `POST /orders`).

## Operational Security Checklist

- [ ] Set `STOCKSBOT_API_KEY_AUTH_ENABLED=true` in non-dev environments
- [ ] Set `STOCKSBOT_API_KEY` and verify unauthorized requests are rejected
- [ ] Store only active Alpaca keys in Keychain; remove old/unused keys
- [ ] Run in paper mode for validation before any live mode session
- [ ] Verify kill switch and panic-stop behavior regularly
- [ ] Configure log/audit retention settings and cleanup cadence
- [ ] Periodically run dependency audits (`pip-audit`, npm audit where appropriate)

## Reporting Security Issues

If you discover a vulnerability:

1. Do not disclose publicly first.
2. Provide impact, reproduction steps, and affected versions.
3. Coordinate a fix before public disclosure.

---

Last Updated: `2026-02-13`
