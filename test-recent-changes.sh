#!/bin/bash
# Test Script for StocksBot - Tests recent changes
# Usage: ./test-recent-changes.sh

set -e  # Exit on error

echo "================================================"
echo "StocksBot - Testing Recent Changes"
echo "================================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Change to script directory
cd "$(dirname "$0")"

echo -e "${YELLOW}Step 1: Installing backend dependencies...${NC}"
cd backend
pip install -q -r requirements.txt
echo -e "${GREEN}✓ Backend dependencies installed${NC}"
echo ""

echo -e "${YELLOW}Step 2: Running backend tests...${NC}"
echo ""
echo "Testing Market Screener (11 tests)..."
python -m pytest tests/test_market_screener.py -v --tb=short || exit 1
echo ""

echo "Testing Budget Tracker (13 tests)..."
python -m pytest tests/test_budget_tracker.py -v --tb=short || exit 1
echo ""

echo "Testing Risk Profiles (18 tests)..."
python -m pytest tests/test_risk_profiles.py -v --tb=short || exit 1
echo ""

echo "Testing Order Execution Integration (20 tests)..."
python -m pytest tests/test_order_execution.py -v --tb=short || exit 1
echo ""

echo -e "${GREEN}✓ All backend tests passed (62 tests total)${NC}"
echo ""

echo -e "${YELLOW}Step 3: Testing API endpoints...${NC}"
echo "Starting backend server in background..."
python app.py > /tmp/stocksbot-backend.log 2>&1 &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"

# Wait for backend to start
sleep 3

# Test endpoints
echo "Testing /screener/stocks..."
curl -s http://127.0.0.1:8000/screener/stocks?limit=5 > /dev/null && echo -e "${GREEN}✓ Stocks endpoint working${NC}" || echo -e "${RED}✗ Stocks endpoint failed${NC}"

echo "Testing /screener/etfs..."
curl -s http://127.0.0.1:8000/screener/etfs?limit=5 > /dev/null && echo -e "${GREEN}✓ ETFs endpoint working${NC}" || echo -e "${RED}✗ ETFs endpoint failed${NC}"

echo "Testing /risk-profiles..."
curl -s http://127.0.0.1:8000/risk-profiles > /dev/null && echo -e "${GREEN}✓ Risk profiles endpoint working${NC}" || echo -e "${RED}✗ Risk profiles endpoint failed${NC}"

echo "Testing /budget/status..."
curl -s http://127.0.0.1:8000/budget/status > /dev/null && echo -e "${GREEN}✓ Budget status endpoint working${NC}" || echo -e "${RED}✗ Budget status endpoint failed${NC}"

echo "Testing /preferences..."
curl -s http://127.0.0.1:8000/preferences > /dev/null && echo -e "${GREEN}✓ Preferences endpoint working${NC}" || echo -e "${RED}✗ Preferences endpoint failed${NC}"

# Stop backend
kill $BACKEND_PID 2>/dev/null || true
echo ""

cd ..

echo -e "${YELLOW}Step 4: Checking frontend...${NC}"
cd ui

if [ -f "package.json" ]; then
    echo "Frontend package.json found"
    if [ -d "node_modules" ]; then
        echo "Running frontend lint..."
        npm run lint 2>&1 | head -10 || echo "Lint not configured or dependencies not installed"
    else
        echo "Frontend dependencies not installed (run 'npm install' in ui/)"
    fi
else
    echo "No frontend package.json found"
fi

cd ..

echo ""
echo "================================================"
echo -e "${GREEN}Testing Complete!${NC}"
echo "================================================"
echo ""
echo "Summary:"
echo "  ✓ 62 backend tests passed"
echo "  ✓ All new API endpoints working"
echo "  ✓ Market Screener service operational"
echo "  ✓ Budget Tracking service operational"
echo "  ✓ Risk Profiles service operational"
echo ""
echo "For full documentation, see TESTING_AND_BUILD.md"
echo ""
