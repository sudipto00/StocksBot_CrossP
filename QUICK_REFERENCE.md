# Quick Reference: Testing & Building

## Fast Testing Commands

```bash
# Test everything quickly
./test-recent-changes.sh

# Using Make
make quick-test        # Test + build (fast)
make test              # All tests
make test-new          # New features only
```

## Backend Testing

```bash
cd backend

# All tests
python -m pytest tests/ -v

# Specific tests
python -m pytest tests/test_market_screener.py -v    # 11 tests
python -m pytest tests/test_budget_tracker.py -v     # 13 tests
python -m pytest tests/test_risk_profiles.py -v      # 18 tests
python -m pytest tests/test_order_execution.py -v    # 20 tests

# With coverage
python -m pytest tests/ --cov=. --cov-report=html
```

## Frontend

```bash
cd ui
npm run lint           # Lint code
npm run build          # Production build
npm run dev            # Dev server
```

## API Testing

```bash
# Start backend first
cd backend && python app.py

# Test endpoints
curl http://127.0.0.1:8000/screener/stocks?limit=10
curl http://127.0.0.1:8000/screener/etfs?limit=10
curl http://127.0.0.1:8000/risk-profiles
curl http://127.0.0.1:8000/budget/status
curl http://127.0.0.1:8000/preferences
```

## Building

```bash
# Frontend
cd ui && npm run build

# Tauri Desktop App
npm run tauri:build

# Using Make
make build              # Frontend only
make build-tauri        # Desktop app
make build-all          # Everything
```

## Development

```bash
# Terminal 1
make dev-backend        # or: cd backend && python app.py

# Terminal 2
make dev-frontend       # or: cd ui && npm run dev
```

## Database

```bash
make db-migrate         # Run migrations
make db-status          # Check status

# Or manually:
cd backend
alembic upgrade head    # Migrate
alembic current         # Status
```

## Full Documentation

- **[TESTING_AND_BUILD.md](./TESTING_AND_BUILD.md)** - Complete testing guide
- **[README.md](./README.md)** - Project overview
- **[DEVELOPMENT.md](./DEVELOPMENT.md)** - Development workflow
- **[TRADING_FEATURES.md](./TRADING_FEATURES.md)** - New features documentation

## Recent Changes Summary

Latest features added:
- ✅ Market Screener (10-200 stocks/ETFs)
- ✅ Risk Profiles (Conservative/Balanced/Aggressive)
- ✅ Weekly Budget Tracking ($200 default)
- ✅ Trading Preferences API
- ✅ 62 new tests (all passing)

Test them: `./test-recent-changes.sh`
