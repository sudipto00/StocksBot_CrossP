# StocksBot - Quick Start for Standalone Testing

Get a working standalone StocksBot app in **5 minutes**.

## Prerequisites Check

```bash
# Verify you have everything
python3 --version  # Should be 3.10+
node --version     # Should be 18+
cargo --version    # Should be 1.70+
```

If anything is missing, install it first.

## One-Command Build

```bash
# From the repo root
./scripts/build-standalone.sh
```

This script will:
1. ✅ Install PyInstaller
2. ✅ Build Python backend into executable
3. ✅ Test the backend
4. ✅ Build React frontend
5. ✅ Package everything with Tauri

**Time:** ~3-5 minutes depending on your system

## What You Get

After the build completes, you'll have a **fully self-contained installer**:

### macOS
```
src-tauri/target/release/bundle/dmg/StocksBot_0.1.0_*.dmg
```
Double-click to install, then find "StocksBot" in Applications.

### Windows
```
src-tauri/target/release/bundle/msi/StocksBot_0.1.0_*.msi
```
Double-click to install, then find "StocksBot" in Start Menu.

### Linux
```
src-tauri/target/release/bundle/appimage/StocksBot_*.AppImage
```
Make executable and run:
```bash
chmod +x StocksBot_*.AppImage
./StocksBot_*.AppImage
```

## First Run

1. **Launch the app** from your applications folder

2. **Go to Settings page**
   - Click "Settings" in the sidebar

3. **Add Alpaca credentials**
   - Enter your Paper API key and secret
   - Click "Save to Keychain"
   - Toggle "Paper Trading Mode" ON
   - Click "Save Settings"

4. **Test the connection**
   - Go to Dashboard
   - Check "Backend Status" - should be green
   - Check "Broker Status" - should show your account info

5. **Create a strategy**
   - Go to "Strategies" page
   - Click "+ New Strategy"
   - Enter name and symbols (e.g., `AAPL, MSFT, GOOGL`)
   - Click "Create"
   - Click "Start Strategy" button

6. **Start the runner**
   - Click "Start Runner" button
   - Watch it execute your strategy

## What's Included

The standalone app is **100% self-contained**:

- ✅ No Python installation needed
- ✅ No Node.js installation needed
- ✅ No external dependencies
- ✅ Secure credential storage (OS Keychain)
- ✅ SQLite database (auto-created)
- ✅ All Python libraries embedded
- ✅ All migrations included

## Testing Checklist

After installing, verify:

- [ ] App launches successfully
- [ ] Settings page loads
- [ ] Can save Alpaca credentials to Keychain
- [ ] Can load credentials from Keychain
- [ ] Backend status is reachable (healthy/degraded)
- [ ] Can create a new strategy
- [ ] Can start/stop the runner
- [ ] Dashboard shows positions/orders
- [ ] Audit logs are visible
- [ ] Charts load on Screener page
- [ ] System tray icon works
- [ ] Closing window minimizes to tray
- [ ] "Quit" from tray actually exits

## Troubleshooting

### "Backend not responding"

Check if something is using port 8000:
```bash
# macOS/Linux
lsof -ti:8000
kill -9 <PID>

# Windows
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

### "Failed to connect to broker"

1. Verify credentials in Settings
2. Test Alpaca connection at https://alpaca.markets
3. Check you're using Paper credentials (not Live)
4. Ensure Paper Trading Mode is ON

### "Database error"

Reset the database:
```bash
# macOS
rm ~/Library/Application\ Support/com.stocksbot.app/stocksbot.db

# Linux
rm ~/.local/share/com.stocksbot.app/stocksbot.db

# Windows
del %APPDATA%\com.stocksbot.app\stocksbot.db
```

Then restart the app - it will recreate the database.

### Check Logs

```bash
# macOS
tail -f ~/Library/Application\ Support/com.stocksbot.app/logs/stocksbot.log

# Linux
tail -f ~/.local/share/com.stocksbot.app/logs/stocksbot.log

# Windows
type %APPDATA%\com.stocksbot.app\logs\stocksbot.log
```

## Advanced: Build Just Backend

If you only want to rebuild the backend:

```bash
cd backend
pip install pyinstaller
pyinstaller build-backend.spec
```

Test it:
```bash
cd dist
./stocksbot-backend  # Backend runs on http://127.0.0.1:8000
```

## Advanced: Build Just Frontend

If you only want to rebuild the UI:

```bash
cd ui
npm run build
```

The built files are in `ui/dist/`

## Advanced: Development vs Production

**Development** (current setup with `npm run tauri:dev`):
- Backend runs as Python script
- Frontend runs with hot reload
- Fast iteration

**Production** (standalone build):
- Backend is compiled executable
- Frontend is static HTML/CSS/JS
- Single installer file
- No dependencies needed

## Next Steps

Once you've verified the standalone app works:

1. **Distribute to testers** - Send them the installer
2. **Test on clean systems** - VM without Python/Node
3. **Verify Keychain flow** - Credentials persist across restarts
4. **Monitor logs** - Check for any errors
5. **Paper trade** - Run with small amounts first

## Need Help?

- Full build guide: `BUILD_STANDALONE.md`
- API reference: `API.md`
- Alpaca setup: `ALPACA_SETUP.md`
- Testing guide: `TESTING_AND_BUILD.md`

---

**Estimated Build Time:** 3-5 minutes
**Installer Size:** ~80-120 MB (varies by platform)
**First Run Time:** ~5 seconds
