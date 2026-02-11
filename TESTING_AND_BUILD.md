# Testing and Build Guide

This guide explains how to test all recent changes and build the StocksBot application.

## Table of Contents
- [Quick Start](#quick-start)
- [Backend Testing](#backend-testing)
- [Frontend Testing](#frontend-testing)
- [Building the Application](#building-the-application)
- [Testing Recent Changes](#testing-recent-changes)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

### Prerequisites Check

Verify you have all required tools installed:

```bash
# Check Node.js (should be v18+)
node --version

# Check Python (should be 3.9+)
python --version

# Check Rust (should be 1.70+)
rustc --version

# Check Cargo (Rust package manager)
cargo --version
```

### Initial Setup

If this is your first time, install all dependencies:

```bash
# From the root directory
cd /home/runner/work/StocksBot_CrossP/StocksBot_CrossP

# Install backend dependencies
cd backend
pip install -r requirements.txt

# Setup database (first time only)
alembic upgrade head

# Install frontend dependencies
cd ../ui
npm install

# Install Tauri CLI
cd ..
npm install
```

---

## Backend Testing

### Run All Backend Tests

```bash
cd backend

# Run all tests with verbose output
python -m pytest tests/ -v

# Run tests with coverage report
python -m pytest tests/ --cov=. --cov-report=html

# Run specific test file
python -m pytest tests/test_market_screener.py -v

# Run tests matching a pattern
python -m pytest tests/ -k "budget" -v
```

### Run Tests for Recent Features

The recent implementation added market screener, budget tracking, and risk profiles. Test these specifically:

```bash
cd backend

# Test market screener service (11 tests)
python -m pytest tests/test_market_screener.py -v

# Test budget tracking (13 tests)
python -m pytest tests/test_budget_tracker.py -v

# Test risk profiles (18 tests)
python -m pytest tests/test_risk_profiles.py -v

# Test order execution with budget integration (20 tests)
python -m pytest tests/test_order_execution.py -v

# Run all new feature tests together (62 tests)
python -m pytest tests/test_market_screener.py tests/test_budget_tracker.py tests/test_risk_profiles.py tests/test_order_execution.py -v
```

### Test API Endpoints Manually

Start the backend server and test the new endpoints:

```bash
# Terminal 1: Start backend server
cd backend
python app.py

# Terminal 2: Test endpoints
# Market screener
curl http://127.0.0.1:8000/screener/stocks?limit=10
curl http://127.0.0.1:8000/screener/etfs?limit=10
curl http://127.0.0.1:8000/screener/all?asset_type=both&limit=20

# Risk profiles
curl http://127.0.0.1:8000/risk-profiles

# Trading preferences
curl http://127.0.0.1:8000/preferences

# Budget status
curl http://127.0.0.1:8000/budget/status

# Update preferences
curl -X POST http://127.0.0.1:8000/preferences \
  -H "Content-Type: application/json" \
  -d '{"asset_type": "both", "risk_profile": "balanced", "weekly_budget": 200.0}'
```

### Test Database Operations

```bash
cd backend

# Check database status
alembic current

# Run migrations
alembic upgrade head

# Test database connectivity
python -c "from storage.database import get_db; next(get_db()); print('Database connection OK')"
```

---

## Frontend Testing

### Lint Frontend Code

```bash
cd ui

# Run ESLint
npm run lint

# Fix linting issues automatically
npm run lint -- --fix
```

### Build Frontend (Development)

```bash
cd ui

# Start development server (with hot reload)
npm run dev

# The app will be available at http://localhost:1420
```

### Build Frontend (Production)

```bash
cd ui

# TypeScript compilation + Vite production build
npm run build

# Preview production build
npm run preview
```

### Test Frontend Manually

1. Start the backend server:
   ```bash
   cd backend
   python app.py
   ```

2. Start the frontend dev server:
   ```bash
   cd ui
   npm run dev
   ```

3. Open browser to http://localhost:1420

4. Test the new Screener page:
   - Navigate to the Screener page (if added to navigation)
   - Check budget status widget displays correctly
   - Test asset type filtering (stocks/ETFs/both)
   - Test risk profile selector
   - Verify table displays active securities
   - Test refresh functionality

5. Test Settings page:
   - Check for new feature highlights
   - Verify all settings save correctly

---

## Building the Application

### Build Backend for Production

For production deployment, the backend runs as-is with Python:

```bash
cd backend

# Ensure all dependencies are installed
pip install -r requirements.txt

# Run with production settings
uvicorn app:app --host 0.0.0.0 --port 8000

# Or with the app.py entry point
python app.py
```

### Build Tauri Desktop Application

Build the complete desktop application with bundled backend:

```bash
# From root directory

# Development build with hot reload
npm run tauri:dev

# Production build (creates installers)
npm run tauri:build
```

The built application will be in `src-tauri/target/release/bundle/`:
- **Windows**: `.msi` installer
- **macOS**: `.dmg` disk image  
- **Linux**: `.AppImage` or `.deb` package

### Build All Components

To build everything from scratch:

```bash
# From root directory

# 1. Build backend (ensure dependencies installed)
cd backend
pip install -r requirements.txt
cd ..

# 2. Build frontend
cd ui
npm install
npm run build
cd ..

# 3. Build Tauri application
npm run tauri:build
```

---

## Testing Recent Changes

The recent implementation added the following features. Here's how to test each:

### 1. Market Screener Service

**Backend Tests:**
```bash
cd backend
python -m pytest tests/test_market_screener.py -v
```

**Manual API Test:**
```bash
# Start backend
cd backend
python app.py

# In another terminal, test endpoints
curl http://127.0.0.1:8000/screener/stocks?limit=25 | python -m json.tool
curl http://127.0.0.1:8000/screener/etfs?limit=25 | python -m json.tool
```

**Expected Results:**
- Should return 25 stocks/ETFs with symbol, name, price, volume
- Data should include AAPL, TSLA, NVDA for stocks
- Data should include SPY, QQQ, IWM for ETFs

### 2. Budget Tracking

**Backend Tests:**
```bash
cd backend
python -m pytest tests/test_budget_tracker.py -v
```

**Manual API Test:**
```bash
# Get budget status
curl http://127.0.0.1:8000/budget/status | python -m json.tool

# Update weekly budget
curl -X POST http://127.0.0.1:8000/budget/update \
  -H "Content-Type: application/json" \
  -d '{"weekly_budget": 300.0}' | python -m json.tool
```

**Expected Results:**
- Status should show weekly_budget, used_budget, remaining_budget
- Week should reset every Monday at 00:00
- Used percentage should be calculated correctly

### 3. Risk Profiles

**Backend Tests:**
```bash
cd backend
python -m pytest tests/test_risk_profiles.py -v
```

**Manual API Test:**
```bash
curl http://127.0.0.1:8000/risk-profiles | python -m json.tool
```

**Expected Results:**
- Should return conservative, balanced, and aggressive profiles
- Each profile should have max_position_size, max_positions, stop_loss_percent
- Conservative: max_position_size = $50
- Balanced: max_position_size = $80
- Aggressive: max_position_size = $120

### 4. Order Execution with Budget Validation

**Backend Tests:**
```bash
cd backend
python -m pytest tests/test_order_execution.py -v
```

**Manual Test:**
```bash
# Enable trading (to activate budget tracking)
curl -X POST http://127.0.0.1:8000/config \
  -H "Content-Type: application/json" \
  -d '{"trading_enabled": true}'

# Try to place an order (should validate against budget)
curl -X POST http://127.0.0.1:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"symbol": "AAPL", "side": "buy", "type": "market", "quantity": 1}'
```

**Expected Results:**
- With trading_enabled=false, order should be validated but not check budget
- With trading_enabled=true, order should validate against weekly budget
- Order exceeding budget should be rejected with appropriate error message

### 5. UI Screener Page

**Manual Test:**
```bash
# Start backend
cd backend
python app.py

# Start frontend (in another terminal)
cd ui
npm run dev

# Open browser to http://localhost:1420
```

**UI Verification:**
1. Navigate to Screener page (or view the ScreenerPage.tsx component)
2. Verify budget status card displays:
   - Weekly budget amount
   - Remaining budget
   - Used percentage with progress bar
   - Weekly P&L
3. Verify filter controls work:
   - Asset type selector (stock/ETF/both)
   - Risk profile selector
   - Result limit selector
   - Weekly budget input
4. Verify asset table shows:
   - Symbol, name, type badge
   - Current price
   - Change percentage (colored green/red)
   - Volume
5. Click "Refresh" button and verify table updates

---

## Test Commands Cheat Sheet

```bash
# Backend - Run all tests
cd backend && python -m pytest tests/ -v

# Backend - Run specific feature tests
cd backend && python -m pytest tests/test_market_screener.py tests/test_budget_tracker.py tests/test_risk_profiles.py -v

# Backend - Run with coverage
cd backend && python -m pytest tests/ --cov=. --cov-report=html

# Backend - Start dev server
cd backend && python app.py

# Frontend - Lint
cd ui && npm run lint

# Frontend - Dev server
cd ui && npm run dev

# Frontend - Build
cd ui && npm run build

# Tauri - Dev mode
npm run tauri:dev

# Tauri - Production build
npm run tauri:build

# Database - Run migrations
cd backend && alembic upgrade head

# Database - Check status
cd backend && alembic current
```

---

## Continuous Integration Testing

To test as CI/CD would:

```bash
# Full test sequence
cd /home/runner/work/StocksBot_CrossP/StocksBot_CrossP

# 1. Backend tests
cd backend
pip install -q -r requirements.txt
python -m pytest tests/ -v --tb=short

# 2. Frontend lint
cd ../ui
npm install
npm run lint

# 3. Frontend build
npm run build

# 4. Check for build artifacts
ls -la dist/

# Success if all steps pass!
```

---

## Troubleshooting

### Backend Tests Failing

**Issue:** Import errors or module not found
```bash
# Solution: Ensure you're in the backend directory and dependencies are installed
cd backend
pip install -r requirements.txt
python -m pytest tests/ -v
```

**Issue:** Database errors
```bash
# Solution: Run migrations
cd backend
alembic upgrade head
```

### Frontend Build Failing

**Issue:** TypeScript errors
```bash
# Solution: Check for type errors
cd ui
npm run build
# Fix any TypeScript errors shown
```

**Issue:** ESLint errors
```bash
# Solution: Auto-fix linting issues
cd ui
npm run lint -- --fix
```

### API Endpoints Not Responding

**Issue:** Backend not running
```bash
# Solution: Start backend server
cd backend
python app.py
# Should see: "Uvicorn running on http://127.0.0.1:8000"
```

**Issue:** Port already in use
```bash
# Solution: Kill existing process
# Linux/Mac:
lsof -ti:8000 | xargs kill -9

# Or change port in app.py
```

### Budget Tracking Not Working

**Issue:** Budget validation not applying to orders
```bash
# Solution: Enable trading in config
curl -X POST http://127.0.0.1:8000/config \
  -H "Content-Type: application/json" \
  -d '{"trading_enabled": true}'
```

---

## Additional Resources

- **README.md** - Project overview and setup
- **DEVELOPMENT.md** - Development workflow
- **TRADING_FEATURES.md** - Complete feature documentation
- **API.md** - API endpoint documentation
- **DATABASE_SETUP.md** - Database configuration

---

## Summary

To test all recent changes:

1. **Run backend tests:** `cd backend && python -m pytest tests/ -v`
2. **Test new features:** `python -m pytest tests/test_market_screener.py tests/test_budget_tracker.py tests/test_risk_profiles.py -v`
3. **Manual API testing:** Start backend (`python app.py`) and test endpoints with curl
4. **UI testing:** Start both backend and frontend, test in browser
5. **Build verification:** `cd ui && npm run build`

All 62 new tests should pass, and all API endpoints should respond correctly.
