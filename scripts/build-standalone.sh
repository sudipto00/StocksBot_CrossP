#!/bin/bash
# Run from App root path

set -e
source ~/.bash_profile
source .venv/bin/activate

echo "🚀 Building StocksBot Standalone Application"
echo "=============================================="

# Check prerequisites
command -v python3 >/dev/null 2>&1 || { echo "❌ Python 3 is required but not installed."; exit 1; }
command -v node >/dev/null 2>&1 || { echo "❌ Node.js is required but not installed."; exit 1; }
command -v cargo >/dev/null 2>&1 || { echo "❌ Rust/Cargo is required but not installed."; exit 1; }

echo ""
echo "📦 Step 1: Installing PyInstaller..."
pip install pyinstaller || { echo "❌ Failed to install PyInstaller"; exit 1; }

echo ""
echo "🐍 Step 2: Building Python backend executable..."
cd backend
pyinstaller build-backend.spec || { echo "❌ Failed to build backend"; exit 1; }
cd ..

echo ""
echo "✅ Backend executable created at: backend/dist/stocksbot-backend"

echo ""
echo "🧪 Step 3: Testing backend executable..."
# Start backend in background and test
backend/dist/stocksbot-backend &
BACKEND_PID=$!
sleep 3

# Check if backend is running
if curl -s http://127.0.0.1:8000/status > /dev/null; then
    echo "✅ Backend executable is working!"
    kill $BACKEND_PID 2>/dev/null || true
else
    echo "❌ Backend executable failed to start"
    kill $BACKEND_PID 2>/dev/null || true
    exit 1
fi

echo ""
echo "⚛️  Step 4: Building React frontend..."
cd ui
npm run build || { echo "❌ Failed to build frontend"; exit 1; }
cd ..

echo ""
echo "🦀 Step 5: Building Tauri application..."
npm run tauri build || { echo "❌ Failed to build Tauri app"; exit 1; }

echo ""
echo "🎉 Build Complete!"
echo "=================="
echo ""
echo "📦 Your installers are ready:"
echo ""

# Detect OS and show appropriate installer location
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "macOS DMG: src-tauri/target/release/bundle/dmg/"
    echo "macOS App: src-tauri/target/release/bundle/macos/StocksBot.app"
    echo ""
    echo "To test: open src-tauri/target/release/bundle/macos/StocksBot.app"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "Linux DEB: src-tauri/target/release/bundle/deb/"
    echo "Linux AppImage: src-tauri/target/release/bundle/appimage/"
    echo ""
    echo "To test: ./src-tauri/target/release/bundle/appimage/StocksBot_*.AppImage"
elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    echo "Windows MSI: src-tauri/target/release/bundle/msi/"
    echo "Windows NSIS: src-tauri/target/release/bundle/nsis/"
    echo ""
    echo "To test: Run the installer from the bundle directory"
fi

echo ""
echo "📚 For more details, see: BUILD_STANDALONE.md"
