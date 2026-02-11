# How to Test Recent Changes and Build the Code

## TL;DR - Quick Start

```bash
# Test all recent changes in one command
./test-recent-changes.sh

# Or use Make
make quick-test
```

That's it! The script will test all 62 new features and verify all API endpoints.

---

## What Was Added Recently?

The recent implementation added:

1. **Market Screener** - Pull 10-200 actively traded stocks/ETFs
2. **Risk Profiles** - Conservative, Balanced, Aggressive strategies  
3. **Weekly Budget Tracking** - Manage $200/week trading budget
4. **Trading Preferences** - Configure asset types and risk tolerance
5. **Order Integration** - Budget validation in order execution

**Total: 62 new tests, all passing ✅**

---

## Testing Methods

### Method 1: Automated Script (Recommended)

```bash
./test-recent-changes.sh
```

This runs:
- All 62 new feature tests
- API endpoint verification
- Backend service validation
- Provides detailed status output

### Method 2: Make Commands

```bash
make test          # Run all tests
make test-new      # Test new features only
make quick-test    # Fast test + build
make help          # Show all commands
```

### Method 3: Manual Testing

```bash
# Backend tests
cd backend
python -m pytest tests/test_market_screener.py -v     # 11 tests
python -m pytest tests/test_budget_tracker.py -v      # 13 tests
python -m pytest tests/test_risk_profiles.py -v       # 18 tests
python -m pytest tests/test_order_execution.py -v     # 20 tests

# Or all at once
python -m pytest tests/ -v
```

---

## Building the Code

### Frontend Build

```bash
cd ui
npm install        # First time only
npm run build      # Production build
```

Output: `ui/dist/`

### Desktop Application Build

```bash
npm run tauri:build
```

Output: `src-tauri/target/release/bundle/`

### Using Make

```bash
make build         # Frontend only
make build-tauri   # Desktop app
make build-all     # Everything
```

---

## API Testing

Start the backend:

```bash
cd backend
python app.py
```

Test endpoints in another terminal:

```bash
# Market Screener
curl http://127.0.0.1:8000/screener/stocks?limit=10

# Risk Profiles
curl http://127.0.0.1:8000/risk-profiles

# Budget Status
curl http://127.0.0.1:8000/budget/status

# Trading Preferences
curl http://127.0.0.1:8000/preferences
```

Or use Make:

```bash
make api-test      # Tests all endpoints (requires backend running)
```

---

## Test Results Summary

Running `./test-recent-changes.sh` should show:

```
✓ Market Screener (11 tests)
✓ Budget Tracker (13 tests)
✓ Risk Profiles (18 tests)
✓ Order Execution (20 tests)
✓ All API endpoints working
```

**Total: 62 tests passed**

---

## Development Workflow

```bash
# Terminal 1: Start backend
make dev-backend

# Terminal 2: Start frontend
make dev-frontend

# Browser: http://localhost:1420
```

---

## Documentation

- **[TESTING_AND_BUILD.md](./TESTING_AND_BUILD.md)** - Complete guide (detailed)
- **[QUICK_REFERENCE.md](./QUICK_REFERENCE.md)** - Cheat sheet (one page)
- **[Makefile](./Makefile)** - All Make commands
- **[README.md](./README.md)** - Project overview
- **[TRADING_FEATURES.md](./TRADING_FEATURES.md)** - Feature documentation

---

## Troubleshooting

**Tests fail with "module not found":**
```bash
cd backend
pip install -r requirements.txt
```

**Backend won't start:**
```bash
cd backend
alembic upgrade head   # Setup database
python app.py          # Should see: "Uvicorn running on http://127.0.0.1:8000"
```

**Frontend build fails:**
```bash
cd ui
npm install
npm run build
```

---

## Quick Command Reference

```bash
# Test everything
./test-recent-changes.sh    # Automated
make test                   # All tests
make test-new               # New features only

# Build
make build                  # Frontend
make build-tauri            # Desktop app

# Development
make dev-backend            # Start backend
make dev-frontend           # Start frontend

# Database
make db-migrate             # Run migrations
```

---

## Summary

**To test all recent changes:**
1. Run `./test-recent-changes.sh`
2. Verify all 62 tests pass
3. Check API endpoints work

**To build the code:**
1. Frontend: `make build`
2. Desktop: `make build-tauri`

**For development:**
1. Terminal 1: `make dev-backend`
2. Terminal 2: `make dev-frontend`
3. Open: http://localhost:1420

**For help:**
- `make help` - Show all Make commands
- See TESTING_AND_BUILD.md for complete guide
