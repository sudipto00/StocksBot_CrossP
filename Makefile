# Makefile for StocksBot - Testing and Building
.PHONY: help test test-backend test-frontend build clean install setup

# Default target
help:
	@echo "StocksBot - Testing and Build Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install          - Install all dependencies"
	@echo "  make setup            - Full setup (install + database)"
	@echo ""
	@echo "Testing:"
	@echo "  make test             - Run all tests"
	@echo "  make test-backend     - Run backend tests only"
	@echo "  make test-new         - Run tests for new features"
	@echo "  make test-coverage    - Run backend tests with coverage"
	@echo "  make lint             - Run frontend linter"
	@echo ""
	@echo "Development:"
	@echo "  make dev-backend      - Start backend dev server"
	@echo "  make dev-frontend     - Start frontend dev server"
	@echo "  make dev              - Start both (use 2 terminals)"
	@echo ""
	@echo "Building:"
	@echo "  make build            - Build frontend for production"
	@echo "  make build-tauri      - Build Tauri desktop app"
	@echo "  make build-all        - Build everything"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean            - Clean build artifacts"
	@echo "  make db-migrate       - Run database migrations"
	@echo "  make api-test         - Test API endpoints (requires running backend)"

# Installation
install:
	@echo "Installing backend dependencies..."
	cd backend && pip install -r requirements.txt
	@echo "Installing frontend dependencies..."
	cd ui && npm install
	@echo "Installing Tauri CLI..."
	npm install
	@echo "Installation complete!"

setup: install
	@echo "Setting up database..."
	cd backend && alembic upgrade head
	@echo "Setup complete!"

# Testing
test: test-backend lint
	@echo "All tests completed!"

test-backend:
	@echo "Running backend tests..."
	cd backend && python -m pytest tests/ -v

test-new:
	@echo "Running tests for new features (market screener, budget, risk profiles)..."
	cd backend && python -m pytest tests/test_market_screener.py tests/test_budget_tracker.py tests/test_risk_profiles.py tests/test_order_execution.py -v

test-coverage:
	@echo "Running backend tests with coverage..."
	cd backend && python -m pytest tests/ --cov=. --cov-report=html --cov-report=term
	@echo "Coverage report generated in backend/htmlcov/index.html"

lint:
	@echo "Running frontend linter..."
	cd ui && npm run lint

# Development
dev-backend:
	@echo "Starting backend development server..."
	cd backend && python app.py

dev-frontend:
	@echo "Starting frontend development server..."
	cd ui && npm run dev

dev:
	@echo "To run both servers:"
	@echo "  Terminal 1: make dev-backend"
	@echo "  Terminal 2: make dev-frontend"

# Building
build:
	@echo "Building frontend..."
	cd ui && npm run build
	@echo "Frontend build complete! Output in ui/dist/"

build-tauri:
	@echo "Building Tauri desktop application..."
	npm run tauri:build
	@echo "Tauri build complete! Check src-tauri/target/release/bundle/"

build-all: build
	@echo "Building complete application..."
	npm run tauri:build
	@echo "All builds complete!"

# Database
db-migrate:
	@echo "Running database migrations..."
	cd backend && alembic upgrade head
	@echo "Database migrations complete!"

db-status:
	@echo "Checking database status..."
	cd backend && alembic current

# API Testing
api-test:
	@echo "Testing API endpoints (backend must be running)..."
	@echo "\n=== Market Screener ==="
	curl -s http://127.0.0.1:8000/screener/stocks?limit=5 | python -m json.tool || echo "Backend not running"
	@echo "\n=== Risk Profiles ==="
	curl -s http://127.0.0.1:8000/risk-profiles | python -m json.tool || echo "Backend not running"
	@echo "\n=== Budget Status ==="
	curl -s http://127.0.0.1:8000/budget/status | python -m json.tool || echo "Backend not running"
	@echo "\n=== Preferences ==="
	curl -s http://127.0.0.1:8000/preferences | python -m json.tool || echo "Backend not running"

# Cleaning
clean:
	@echo "Cleaning build artifacts..."
	rm -rf ui/dist
	rm -rf ui/node_modules/.vite
	rm -rf backend/__pycache__
	rm -rf backend/**/__pycache__
	rm -rf backend/.pytest_cache
	rm -rf backend/htmlcov
	rm -rf backend/.coverage
	@echo "Clean complete!"

# Quick test for recent changes
quick-test:
	@echo "Quick test of recent changes..."
	@echo "1. Running new feature tests..."
	cd backend && python -m pytest tests/test_market_screener.py tests/test_budget_tracker.py tests/test_risk_profiles.py -v --tb=short
	@echo "2. Linting frontend..."
	cd ui && npm run lint
	@echo "3. Building frontend..."
	cd ui && npm run build
	@echo "\nQuick test complete! ✓"
