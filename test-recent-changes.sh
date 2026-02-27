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
FAILURES=0

echo -e "${YELLOW}Step 1: Installing backend dependencies...${NC}"
cd backend
../venv/bin/pip install -q -r requirements.txt
echo -e "${GREEN}✓ Backend dependencies installed${NC}"
echo ""

echo -e "${YELLOW}Step 2: Running backend tests...${NC}"
echo ""
echo "Testing Market Screener (11 tests)..."
../venv/bin/python -m pytest tests/test_market_screener.py -v --tb=short || exit 1
echo ""

echo "Testing Budget Tracker (13 tests)..."
../venv/bin/python -m pytest tests/test_budget_tracker.py -v --tb=short || exit 1
echo ""

echo "Testing Order Execution Integration (20 tests)..."
../venv/bin/python -m pytest tests/test_order_execution.py -v --tb=short || exit 1
echo ""

echo -e "${GREEN}✓ All backend tests passed${NC}"
echo ""

echo -e "${YELLOW}Step 3: Testing API endpoints...${NC}"
echo "Starting backend server in background..."
STOCKSBOT_API_KEY_AUTH_ENABLED=false STOCKSBOT_API_KEY="" ../venv/bin/python app.py > /tmp/stocksbot-backend.log 2>&1 &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"

# Wait for backend to start
READY=0
for _ in {1..30}; do
    STATUS_CODE=$(curl -sS -o /tmp/stocksbot-status.json -w "%{http_code}" http://127.0.0.1:8000/status || true)
    if [ "$STATUS_CODE" = "200" ]; then
        READY=1
        break
    fi
    sleep 1
done

check_endpoint() {
    local label="$1"
    local url="$2"
    local expected="${3:-200}"
    local code
    code=$(curl -sS -o /tmp/stocksbot-endpoint-check.json -w "%{http_code}" "$url" || true)
    if [ "$code" = "$expected" ]; then
        echo -e "${GREEN}✓ ${label} endpoint working (${code})${NC}"
    else
        echo -e "${RED}✗ ${label} endpoint failed (${code})${NC}"
        FAILURES=$((FAILURES + 1))
    fi
}

if [ "$READY" = "1" ]; then
    check_endpoint "/status" "http://127.0.0.1:8000/status"
    check_endpoint "/preferences" "http://127.0.0.1:8000/preferences"
    check_endpoint "/budget/status" "http://127.0.0.1:8000/budget/status"
    check_endpoint "/optimizer/health" "http://127.0.0.1:8000/optimizer/health"
    check_endpoint "/screener/all" "http://127.0.0.1:8000/screener/all?asset_type=etf&screener_mode=preset&limit=25"
else
    echo -e "${RED}✗ Backend did not become ready within 30s${NC}"
    FAILURES=$((FAILURES + 1))
fi

# Stop backend
kill $BACKEND_PID 2>/dev/null || true
wait $BACKEND_PID 2>/dev/null || true
echo ""

cd ..

echo -e "${YELLOW}Step 4: Checking frontend...${NC}"
cd ui

if [ -f "package.json" ]; then
    echo "Frontend package.json found"
    if [ -d "node_modules" ]; then
        echo "Running frontend lint..."
        if ! npm run lint; then
            FAILURES=$((FAILURES + 1))
        fi
    else
        echo "Frontend dependencies not installed (run 'npm install' in ui/)"
        FAILURES=$((FAILURES + 1))
    fi
else
    echo "No frontend package.json found"
    FAILURES=$((FAILURES + 1))
fi

cd ..

echo ""
echo "================================================"
echo -e "${GREEN}Testing Complete!${NC}"
echo "================================================"
echo ""
if [ "$FAILURES" -eq 0 ]; then
    echo "Summary:"
    echo "  ✓ Backend ETF workflow tests passed"
    echo "  ✓ API endpoint smoke checks passed"
    echo "  ✓ Frontend lint passed"
    echo ""
    echo "For full documentation, see TESTING_AND_BUILD.md"
    echo ""
    exit 0
fi

echo -e "${RED}Summary: ${FAILURES} check(s) failed.${NC}"
echo ""
echo "For full documentation, see TESTING_AND_BUILD.md"
echo ""
exit 1
