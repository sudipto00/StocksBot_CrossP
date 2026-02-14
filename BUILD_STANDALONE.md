# StocksBot - Standalone App Build Guide

This guide walks you through building a fully standalone StocksBot application that bundles everything (frontend, backend, database) into a single distributable package.

## Overview

The standalone build process:
1. **Bundles Python backend** into a single executable using PyInstaller
2. **Builds React frontend** into static assets
3. **Packages everything** with Tauri into a native installer

## Prerequisites

- Python 3.10+ with pip
- Node.js 18+
- Rust toolchain (cargo, rustc)
- Tauri prerequisites for your OS
- PyInstaller: `pip install pyinstaller`

## Quick Build (All Platforms)

```bash
# From repo root
./scripts/build-standalone.sh
```

The installer will be in `src-tauri/target/release/bundle/`

## Step-by-Step Manual Build

### Step 1: Install PyInstaller

```bash
cd backend
pip install pyinstaller
```

### Step 2: Build Python Backend Executable

```bash
cd backend

# macOS/Linux
pyinstaller build-backend.spec

# Windows
pyinstaller build-backend.spec
```

This creates `dist/stocksbot-backend` (or `stocksbot-backend.exe` on Windows)

### Step 3: Test Backend Executable

```bash
# macOS/Linux
cd backend/dist
./stocksbot-backend

# Windows
cd backend\dist
stocksbot-backend.exe
```

You should see: `INFO: Started server process` on http://127.0.0.1:8000

### Step 4: Build Tauri Application

```bash
# From repo root
npm run tauri build
```

This will:
1. Run `npm --prefix ui run build` (builds React frontend)
2. Copy backend executable to bundle
3. Build Tauri app with everything embedded
4. Create platform-specific installer

### Step 5: Find Your Installer

**macOS:**
```
src-tauri/target/release/bundle/dmg/StocksBot_0.1.0_*.dmg
src-tauri/target/release/bundle/macos/StocksBot.app
```

**Windows:**
```
src-tauri/target/release/bundle/msi/StocksBot_0.1.0_*.msi
src-tauri/target/release/bundle/nsis/StocksBot_0.1.0_*.exe
```

**Linux:**
```
src-tauri/target/release/bundle/deb/stocksbot_0.1.0_*.deb
src-tauri/target/release/bundle/appimage/StocksBot_0.1.0_*.AppImage
```

## Testing the Standalone App

### macOS
```bash
# Install DMG or run .app directly
open src-tauri/target/release/bundle/macos/StocksBot.app
```

### Windows
```powershell
# Install MSI or run installer
.\src-tauri\target\release\bundle\msi\StocksBot_0.1.0_x64_en-US.msi
```

### Linux
```bash
# Install DEB
sudo dpkg -i src-tauri/target/release/bundle/deb/stocksbot_0.1.0_amd64.deb

# Or run AppImage
chmod +x src-tauri/target/release/bundle/appimage/StocksBot_0.1.0_amd64.AppImage
./src-tauri/target/release/bundle/appimage/StocksBot_0.1.0_amd64.AppImage
```

## What Gets Bundled

The standalone app includes:

- ✅ Tauri native wrapper (Rust)
- ✅ React UI (compiled to static HTML/CSS/JS)
- ✅ Python backend executable (single binary)
- ✅ SQLite database (created on first run)
- ✅ Python dependencies (embedded in executable)
- ✅ Alembic migrations (embedded)
- ✅ Configuration templates

The app is **completely self-contained** - no Python, Node, or external dependencies required.

## App Data Locations

The standalone app stores data in standard OS locations:

**macOS:**
```
~/Library/Application Support/com.stocksbot.app/
  ├── stocksbot.db          # Trading database
  ├── logs/                 # Application logs
  └── config/               # User configuration
```

**Windows:**
```
%APPDATA%\com.stocksbot.app\
  ├── stocksbot.db
  ├── logs\
  └── config\
```

**Linux:**
```
~/.local/share/com.stocksbot.app/
  ├── stocksbot.db
  ├── logs/
  └── config/
```

## Credentials Management

The standalone app uses OS-native secure storage:

- **macOS:** Keychain (`com.stocksbot.alpaca`)
- **Windows:** Windows Credential Manager
- **Linux:** Secret Service (libsecret)

Credentials are stored securely and never written to disk in plaintext.

## Environment Variables (Optional)

You can still override settings via environment variables:

```bash
# Backend API auth (optional for local use)
export STOCKSBOT_API_KEY_AUTH_ENABLED=false

# Custom database location
export STOCKSBOT_DATABASE_URL=sqlite:///path/to/custom.db

# Alpaca credentials (fallback if not in Keychain)
export ALPACA_API_KEY=your-key
export ALPACA_SECRET_KEY=your-secret
export ALPACA_PAPER=true
```

## Troubleshooting

### Backend Not Starting

Check if port 8000 is available:
```bash
# macOS/Linux
lsof -ti:8000

# Windows
netstat -ano | findstr :8000
```

### Missing Python Dependencies

Rebuild backend with:
```bash
cd backend
rm -rf build dist
pyinstaller build-backend.spec
```

### Database Migration Errors

The app auto-runs migrations on first start. If this fails:
```bash
# Manually run migrations
cd backend
alembic upgrade head
```

### Logs Location

Check application logs:
```bash
# macOS
tail -f ~/Library/Application\ Support/com.stocksbot.app/logs/stocksbot.log

# Linux
tail -f ~/.local/share/com.stocksbot.app/logs/stocksbot.log

# Windows
type %APPDATA%\com.stocksbot.app\logs\stocksbot.log
```

## Building for Distribution

### Code Signing (macOS)

```bash
# Set signing identity in src-tauri/tauri.conf.json
"macOS": {
  "signingIdentity": "Developer ID Application: Your Name (TEAM_ID)"
}
```

### Notarization (macOS)

After building:
```bash
xcrun notarytool submit src-tauri/target/release/bundle/dmg/StocksBot_0.1.0_*.dmg \
  --apple-id "your@email.com" \
  --password "app-specific-password" \
  --team-id "TEAM_ID"
```

### Code Signing (Windows)

```bash
# Set certificate in src-tauri/tauri.conf.json
"windows": {
  "certificateThumbprint": "YOUR_CERT_THUMBPRINT"
}
```

## CI/CD Integration

See `.github/workflows/build-release.yml` for automated builds on:
- Push to main
- New git tags
- Manual workflow dispatch

## Size Optimization

Reduce bundle size:

```bash
# Strip Python debug symbols
cd backend
pyinstaller --strip build-backend.spec

# Use UPX compression
pyinstaller --upx-dir=/path/to/upx build-backend.spec
```

## Platform-Specific Notes

### macOS (Apple Silicon)

Build universal binary:
```bash
rustup target add aarch64-apple-darwin x86_64-apple-darwin
npm run tauri build -- --target universal-apple-darwin
```

### Windows (32-bit)

```bash
rustup target add i686-pc-windows-msvc
npm run tauri build -- --target i686-pc-windows-msvc
```

### Linux (AppImage)

AppImage is the most portable format:
```bash
chmod +x StocksBot_*.AppImage
./StocksBot_*.AppImage --appimage-help
```

## Next Steps

After building:
1. Test the installer on a clean system
2. Verify credentials flow (Keychain → Backend)
3. Test trading with paper account
4. Check audit logs and database
5. Distribute to testers

## Support

Issues? Check:
- Logs in app data directory
- Backend health: http://127.0.0.1:8000/status
- Tauri dev tools: Right-click → Inspect Element

---

**Last Updated:** 2026-02-13
**Tauri Version:** 2.10.0
**Python Version:** 3.12
