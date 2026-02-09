# Development Guide

## Quick Start

### First Time Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/sudipto00/StocksBot_CrossP.git
   cd StocksBot_CrossP
   ```

2. **Install all dependencies**
   ```bash
   # Install UI dependencies
   cd ui
   npm install
   
   # Install backend dependencies
   cd ../backend
   pip install -r requirements.txt
   
   # Install Tauri CLI (from root)
   cd ..
   npm install
   ```

3. **Setup database (first time only)**
   ```bash
   cd backend
   # Run database migrations
   alembic upgrade head
   ```

### Running in Development

**Option 1: Manual (Recommended for development)**

Open two terminal windows:

**Terminal 1 - Backend:**
```bash
cd backend
python app.py
```
You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

**Terminal 2 - Frontend:**
```bash
cd ui
npm run dev
```
You should see:
```
  VITE ready in Xms
  ➜  Local:   http://localhost:1420/
```

Open your browser to http://localhost:1420 to see the app.

**Option 2: Using npm scripts (from root)**
```bash
# Terminal 1
npm run backend:dev

# Terminal 2
npm run dev
```

### Project Structure

```
StocksBot_CrossP/
│
├── backend/                 # Python FastAPI Backend
│   ├── app.py              # Main entry point
│   ├── requirements.txt    # Python dependencies
│   ├── config/             # Configuration
│   ├── engine/             # Trading engine (TODO)
│   ├── integrations/       # External APIs (TODO)
│   ├── storage/            # Data persistence (TODO)
│   ├── audit/              # Compliance & logging (TODO)
│   ├── export/             # Data export (TODO)
│   ├── services/           # Business logic (TODO)
│   ├── api/                # API routes (TODO)
│   └── tests/              # Tests
│
├── ui/                     # React Frontend
│   ├── src/
│   │   ├── pages/         # Page components
│   │   ├── components/    # Reusable components
│   │   ├── layouts/       # Layout components
│   │   ├── store/         # State management (TODO)
│   │   ├── api/           # API client
│   │   ├── hooks/         # Custom hooks
│   │   └── styles/        # CSS/Tailwind
│   ├── package.json
│   └── vite.config.ts
│
└── src-tauri/              # Tauri Desktop App
    ├── src/main.rs         # Rust main process
    ├── tauri.conf.json     # Tauri config
    └── Cargo.toml          # Rust dependencies
```

## Development Workflow

### Database Management

**Run Migrations:**
```bash
cd backend
alembic upgrade head
```

**Create New Migration (after modifying models):**
```bash
cd backend
alembic revision --autogenerate -m "Description of changes"
alembic upgrade head
```

**Rollback Migration:**
```bash
cd backend
alembic downgrade -1  # Rollback one version
```

**View Migration History:**
```bash
cd backend
alembic history
alembic current
```

The database file (`stocksbot.db`) is created automatically in the `backend/` directory when you run migrations or start the app.

**Database Configuration:**
- **Default (Development):** SQLite - `backend/stocksbot.db`
- **Custom URL:** Set `DATABASE_URL` environment variable
  ```bash
  # Example for PostgreSQL in production
  export DATABASE_URL="postgresql://user:password@localhost/stocksbot"
  ```

### Making Changes

1. **Backend Changes**
   - Edit files in `backend/`
   - FastAPI auto-reloads on file changes
   - Test with `pytest` in `backend/tests/`

2. **Frontend Changes**
   - Edit files in `ui/src/`
   - Vite hot-reloads automatically
   - View changes instantly in browser

3. **Tauri Changes**
   - Edit `src-tauri/src/main.rs` or `tauri.conf.json`
   - Requires Tauri rebuild

4. **Database Schema Changes**
   - Edit models in `backend/storage/models.py`
   - Create migration: `alembic revision --autogenerate -m "Description"`
   - Apply migration: `alembic upgrade head`

### Testing

**Backend Tests:**
```bash
cd backend
pytest tests/ -v

# Run specific test file
pytest tests/test_storage.py -v

# Run with coverage
pytest --cov=storage --cov=services tests/
```

**Frontend Lint:**
```bash
cd ui
npm run lint
```

### Building

**Build Frontend:**
```bash
cd ui
npm run build
# Output: ui/dist/
```

**Build Tauri App (requires all system dependencies):**
```bash
npm run tauri:build
# Output: src-tauri/target/release/bundle/
```

## API Documentation

### Backend Endpoints

**Base URL:** `http://127.0.0.1:8000`

#### GET /
Returns root message
```json
{
  "message": "StocksBot API"
}
```

#### GET /status
Health check endpoint
```json
{
  "status": "running",
  "service": "StocksBot Backend",
  "version": "0.1.0"
}
```

### Adding New Endpoints

1. Create route handler in `backend/api/`
2. Import and register in `backend/app.py`
3. Add client method in `ui/src/api/backend.ts`
4. Create hook in `ui/src/hooks/` if needed

Example:
```python
# backend/api/portfolio.py
from fastapi import APIRouter

router = APIRouter(prefix="/api/portfolio")

@router.get("/")
async def get_portfolio():
    return {"portfolio": []}
```

```typescript
// ui/src/api/backend.ts
export async function getPortfolio() {
  const response = await fetch(`${BACKEND_URL}/api/portfolio`);
  return response.json();
}
```

## Troubleshooting

### Backend won't start
- Check if port 8000 is already in use: `lsof -i :8000`
- Verify Python dependencies: `pip install -r requirements.txt`
- Check Python version: `python --version` (requires 3.9+)

### Frontend won't start
- Check if port 1420 is already in use
- Delete `node_modules` and reinstall: `rm -rf node_modules && npm install`
- Check Node version: `node --version` (requires 18+)

### Backend connection fails in UI
- Verify backend is running on http://127.0.0.1:8000
- Check CORS settings in `backend/app.py`
- Check browser console for errors

### Tauri build fails
- Install system dependencies (see README.md prerequisites)
- Run `cargo build` in `src-tauri/` to see detailed errors
- Check Rust version: `rustc --version` (requires 1.70+)

## Next Steps

This is a scaffold. Here's what needs to be implemented:

### Backend (Priority Order)
1. ✅ Basic FastAPI app with /status
2. ✅ Configuration management (config/)
3. ✅ Database/storage layer (storage/)
   - ✅ SQLite database with SQLAlchemy
   - ✅ Alembic migrations
   - ✅ Models for positions, orders, trades, strategies, config
   - ✅ Repository pattern for CRUD operations
   - ✅ Storage service integration
   - ✅ Comprehensive tests
4. 🚧 Broker API integration (integrations/)
5. 🚧 Trading engine (engine/)
6. 🚧 Business services (services/)
7. 🚧 Additional API routes (api/)
8. 🚧 Export functionality (export/)
9. 🚧 Audit/compliance (audit/)

### Frontend (Priority Order)
1. ✅ Basic React + Tailwind setup
2. ✅ Main layout with sidebar
3. ✅ Dashboard page
4. ✅ Backend status checking
5. 🚧 Portfolio page
6. 🚧 Trading page
7. 🚧 Analytics page
8. 🚧 Settings page
9. 🚧 State management
10. 🚧 Real-time updates
11. 🚧 Charts and visualizations

### Tauri (Priority Order)
1. ✅ Basic Tauri setup
2. ✅ System tray placeholder
3. 🚧 Sidecar auto-start
4. 🚧 Tray menu implementation
5. 🚧 Window management
6. 🚧 Notifications
7. 🚧 Auto-updates

## Contributing

1. Create a feature branch
2. Make your changes
3. Add tests
4. Run linters and tests
5. Submit a pull request

## Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [React Documentation](https://react.dev/)
- [Tauri Documentation](https://tauri.app/)
- [Tailwind CSS](https://tailwindcss.com/)
