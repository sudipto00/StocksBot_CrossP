# StocksBot - Cross-Platform Trading Desktop Application

A cross-platform desktop application for automated stock trading, built with Tauri, React, and Python FastAPI.

## Architecture

### Sidecar Model

StocksBot uses a **sidecar architecture** where the Python FastAPI backend runs as a separate process alongside the Tauri desktop application:

```
┌─────────────────────────────────────────┐
│         Tauri Desktop App               │
│  ┌───────────────────────────────────┐  │
│  │   React + Tailwind Frontend       │  │
│  │   (TypeScript)                    │  │
│  └───────────────┬───────────────────┘  │
│                  │ HTTP/WebSocket        │
│                  ▼                       │
│  ┌───────────────────────────────────┐  │
│  │   Python FastAPI Backend          │  │
│  │   (Sidecar Process)               │  │
│  │   - Trading Engine                │  │
│  │   - Market Integrations           │  │
│  │   - Data Storage                  │  │
│  │   - Analytics                     │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### Directory Structure

```
StocksBot_CrossP/
├── backend/                    # Python FastAPI backend (sidecar)
│   ├── app.py                 # Main FastAPI application
│   ├── requirements.txt       # Python dependencies
│   ├── config/                # Configuration management
│   ├── engine/                # Trading engine core logic
│   ├── integrations/          # External API integrations (brokers, data providers)
│   ├── storage/               # Data persistence layer
│   ├── audit/                 # Audit and compliance logging
│   ├── export/                # Data export functionality
│   ├── services/              # Business logic services
│   ├── api/                   # API route handlers
│   └── tests/                 # Backend tests
│
├── ui/                        # React frontend application
│   ├── src/
│   │   ├── pages/            # Page components
│   │   ├── components/       # Reusable UI components
│   │   ├── layouts/          # Layout components
│   │   ├── store/            # State management (Zustand/Redux)
│   │   ├── api/              # API client utilities
│   │   ├── hooks/            # Custom React hooks
│   │   └── styles/           # Tailwind CSS and global styles
│   ├── package.json
│   └── vite.config.ts
│
├── src-tauri/                 # Tauri application (Rust)
│   ├── src/
│   │   └── main.rs           # Tauri main process, sidecar launcher
│   ├── tauri.conf.json       # Tauri configuration
│   ├── build.rs              # Build script
│   └── Cargo.toml            # Rust dependencies
│
├── package.json               # Root package.json with dev scripts
└── README.md                  # This file
```

## Prerequisites

### Required Tools

1. **Node.js** (v18 or later)
   - Download: https://nodejs.org/

2. **Python** (3.9 or later)
   - Download: https://www.python.org/downloads/

3. **Rust** (1.70 or later)
   - Install: https://rustup.rs/

4. **Tauri Prerequisites**
   - **Linux**: `sudo apt-get install libwebkit2gtk-4.0-dev build-essential curl wget file libssl-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev`
   - **macOS**: `xcode-select --install`
   - **Windows**: Microsoft Visual C++ Build Tools

## Local Development Setup

### 1. Install Frontend Dependencies

```bash
cd ui
npm install
```

### 2. Install Backend Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 3. Install Tauri Dependencies

```bash
cd src-tauri
cargo build
```

## Running the Application

### Development Mode

You have two options for running in development:

#### Option 1: Run Backend and Frontend Separately (Recommended for development)

**Terminal 1 - Start Backend:**
```bash
cd backend
python app.py
# Backend will run on http://127.0.0.1:8000
```

**Terminal 2 - Start Tauri + Frontend:**
```bash
npm run tauri dev
# Frontend will run on http://localhost:1420
# Tauri app will open automatically
```

#### Option 2: Run Everything with Tauri (Full integration test)

```bash
npm run tauri dev
```

This will:
1. Start the Vite dev server for the React frontend
2. Launch the Tauri desktop application
3. Note: You'll need to manually start the Python backend in a separate terminal

### Verify Backend Connection

Once both are running:
1. Open the Tauri app (should open automatically)
2. Check the "Backend Status" card on the dashboard
3. It should show a green indicator with "running" status

## Building for Production

### Build Backend Executable

To bundle the Python backend as a standalone executable:

```bash
cd backend
# TODO: Add PyInstaller or similar tool configuration
# pip install pyinstaller
# pyinstaller --onefile app.py
```

### Build Tauri Application

```bash
npm run tauri build
```

This will:
1. Build the React frontend for production
2. Bundle the Tauri application with the sidecar
3. Create platform-specific installers in `src-tauri/target/release/bundle/`

## Cross-Platform Sidecar Execution

### How the Sidecar Works

1. **Development**: The Python backend runs as a separate process you start manually
2. **Production**: The backend will be bundled as a binary and launched automatically by Tauri

### Sidecar Configuration (TODO)

In `src-tauri/tauri.conf.json`, configure the sidecar:

```json
{
  "tauri": {
    "bundle": {
      "externalBin": [
        "backend/dist/app"
      ]
    }
  }
}
```

In `src-tauri/src/main.rs`, the sidecar launch logic:

```rust
// Launch Python backend on startup
let sidecar_path = app
    .path_resolver()
    .resolve_resource("backend/app")
    .expect("failed to resolve sidecar");

let child = Command::new(sidecar_path)
    .spawn()
    .expect("failed to spawn sidecar");
```

### Platform-Specific Notes

- **Windows**: Backend will be bundled as `app.exe`
- **macOS**: Backend will be bundled as a Unix executable `app`
- **Linux**: Backend will be bundled as a Unix executable `app`

## Testing

### Backend Tests

```bash
cd backend
pytest tests/
```

### Frontend Tests (TODO)

```bash
cd ui
npm run test
```

## Available API Endpoints

The backend provides a REST API for frontend-backend communication.

**Documentation:** See [API.md](./API.md) for complete API documentation.

**Quick Reference:**
- `GET /` - Root endpoint
- `GET /status` - Health check
- `GET /config` - Get configuration
- `POST /config` - Update configuration
- `GET /positions` - Get current positions (stub data)
- `GET /orders` - Get orders (stub data)
- `POST /orders` - Create order (placeholder)
- `POST /notifications` - Request notification (placeholder)

For detailed request/response schemas, see the [API Documentation](./API.md).

## Current Status

This is a **scaffold version** with minimal functionality:

✅ **Completed:**
- Project structure and directory layout
- FastAPI backend with /status endpoint
- React + Tailwind UI with basic dashboard
- Tauri application setup
- Cross-platform build configuration
- Basic backend-frontend communication

🚧 **TODO (Feature Parity):**
- Trading engine implementation
- Broker API integrations
- Portfolio management
- Market data feeds
- Analytics and reporting
- User authentication
- Database integration
- Real-time updates (WebSocket)
- System tray full implementation
- Notifications
- Settings management
- Data export functionality
- Comprehensive testing

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## License

[License TBD]

## Support

For issues and questions, please open an issue on GitHub.
