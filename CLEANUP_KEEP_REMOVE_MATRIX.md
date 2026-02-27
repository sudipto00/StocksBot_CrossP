# Cleanup Keep/Remove Matrix (ETF Pivot)

## Backend

| Area | Decision | Risk | Rationale | Status |
|---|---|---|---|---|
| `seed_only` request compatibility field (`RunnerStartRequest`, `BacktestRequest`, `StrategyOptimizationRequest`) | Remove | Low | `preset_universe_mode` already fully expresses universe selection and is used by current UI. | Removed |
| `/screener/all?seed_only=...` query alias | Remove | Low | Legacy alias duplicates `preset_universe_mode=seed_only`. | Removed |
| `/screener/preset?seed_only=...` query alias | Remove | Low | Same behavior available via `preset_universe_mode`. | Removed |
| `/preferences` write-time global `screener_limit` fan-out | Remove | Medium | Global write path caused hidden side effects across scoped limits. | Removed |
| Legacy screener endpoints `/screener/stocks`, `/screener/etfs` | Remove | Medium | Superseded by `/screener/all` and `/screener/preset`; not used by current UI. | Removed |
| `screener_limit` effective field in preferences response | Keep | Low | Current UI summary and runner/backtest UX still consume this derived value. | Kept |
| Read-time fallback from persisted `screener_limit` to scoped limits | Keep (temporary) | Medium | Prevents silent reset for existing DB rows created by older builds. | Kept |

## Frontend

| Area | Decision | Risk | Rationale | Status |
|---|---|---|---|---|
| `seedOnly` option in `getScreenerAssets` API client | Remove | Low | Replaced by explicit `presetUniverseMode`. | Removed |
| Legacy localStorage key `stocksbot.screener.preset.seedOnly` | Remove | Low | Redundant after `preset_universe_mode` key. | Removed |
| Workspace snapshot `seed_only_preset` compatibility field | Remove | Medium | Snapshot now stores only canonical `preset_universe_mode`. | Removed |
| Legacy strategy analysis universe single-key fallback (`stocksbot.strategy.analysis.universeMode`) | Remove | Medium | Replaced by per-strategy map key `stocksbot.strategy.analysis.universeModes`. | Removed |
| `screener_limit` in preference update payload | Remove | Low | Backend no longer accepts global limit updates; scoped limits only. | Removed |
| Effective `screener_limit` display/use in UI | Keep | Low | Still useful as active context limit derived from scoped limits. | Kept |

## Validation Plan

- Backend: run `venv/bin/python -m pytest -q backend/tests`
- Frontend: run `npm run lint` and `npm run build` in `ui/`
- Regression checks:
  - Strategy start/backtest/optimizer workspace-universe flows
  - Screener preset modes (`seed_only`, `seed_guardrail_blend`, `guardrail_only`)
  - Settings/Strategy summaries showing effective limit
