#!/bin/bash
# StocksBot - Quick Start Script

set -e

echo "🚀 StocksBot Quick Start"
echo "========================"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.9 or later."
    exit 1
fi

# Check if Node is installed
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js 18 or later."
    exit 1
fi

echo "✅ Python and Node.js are installed"
echo ""

# Install backend dependencies
echo "📦 Installing backend dependencies..."
cd backend
pip install -q -r requirements.txt
cd ..
echo "✅ Backend dependencies installed"
echo ""

# Install UI dependencies
echo "📦 Installing UI dependencies..."
cd ui
npm install --silent
cd ..
echo "✅ UI dependencies installed"
echo ""

# Install Tauri CLI
echo "📦 Installing Tauri CLI..."
npm install --silent
echo "✅ Tauri CLI installed"
echo ""

echo "✅ Setup complete!"
echo ""
echo "To run the application:"
echo ""
echo "Terminal 1 (Backend):"
echo "  cd backend && python app.py"
echo ""
echo "Terminal 2 (Frontend):"
echo "  cd ui && npm run dev"
echo ""
echo "Then open: http://localhost:1420"
echo ""
