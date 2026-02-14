#!/bin/bash
set -e

echo "🧪 StocksBot Standalone App Test Suite"
echo "======================================"

# Find the app based on OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    APP_PATH="src-tauri/target/release/bundle/macos/StocksBot.app"
    APP_EXEC="$APP_PATH/Contents/MacOS/StocksBot"
    echo "Platform: macOS"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    APP_PATH=$(find src-tauri/target/release/bundle/appimage -name "*.AppImage" -type f 2>/dev/null | head -1)
    APP_EXEC="$APP_PATH"
    echo "Platform: Linux"
else
    echo "❌ This test script is for macOS/Linux. For Windows, test manually."
    exit 1
fi

if [ ! -e "$APP_PATH" ]; then
    echo "❌ App not found at: $APP_PATH"
    echo "Build the app first: ./scripts/build-standalone.sh"
    exit 1
fi

echo "✅ Found app: $APP_PATH"
echo ""

# Test 1: Check if backend executable exists
echo "Test 1: Backend executable exists"
if [ -f "backend/dist/stocksbot-backend" ]; then
    echo "✅ Backend executable found"
else
    echo "❌ Backend executable not found"
    exit 1
fi

# Test 2: Frontend build exists
echo ""
echo "Test 2: Frontend build exists"
if [ -d "ui/dist" ] && [ -f "ui/dist/index.html" ]; then
    echo "✅ Frontend build found"
else
    echo "❌ Frontend build not found"
    exit 1
fi

# Test 3: Try to launch app (in background)
echo ""
echo "Test 3: Launch standalone app"
echo "Starting app in background..."

if [[ "$OSTYPE" == "darwin"* ]]; then
    open "$APP_PATH" &
    APP_PID=$!
else
    chmod +x "$APP_PATH"
    "$APP_PATH" &
    APP_PID=$!
fi

echo "✅ App launched (PID: $APP_PID)"
echo "Waiting 5 seconds for backend to start..."
sleep 5

# Test 4: Check if backend is responding
echo ""
echo "Test 4: Backend health check"
if curl -s http://127.0.0.1:8000/status | grep -q "ok"; then
    echo "✅ Backend is responding correctly"
else
    echo "⚠️  Backend not responding (may take longer to start)"
    echo "Try accessing http://127.0.0.1:8000/status manually"
fi

# Test 5: Check if app window is open
echo ""
echo "Test 5: UI accessibility"
echo "Check if the StocksBot window is visible on your screen"
echo "Press Enter to continue after verifying..."
read

# Clean up
echo ""
echo "Cleaning up test..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    osascript -e 'quit app "StocksBot"' 2>/dev/null || true
else
    kill $APP_PID 2>/dev/null || true
fi

echo ""
echo "🎉 Standalone app tests complete!"
echo ""
echo "Manual testing checklist:"
echo "========================="
echo "1. [ ] App launches without errors"
echo "2. [ ] Settings page accessible"
echo "3. [ ] Can save credentials to Keychain"
echo "4. [ ] Can load credentials from Keychain"
echo "5. [ ] Backend status shows 'running'"
echo "6. [ ] Can create strategies"
echo "7. [ ] Can start/stop runner"
echo "8. [ ] Dashboard displays data"
echo "9. [ ] Charts load properly"
echo "10. [ ] System tray icon functional"
echo "11. [ ] Close button minimizes to tray"
echo "12. [ ] Quit from tray exits app"
echo ""
echo "To run full manual tests, launch the app and go through each item."
