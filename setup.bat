@echo off
REM StocksBot - Quick Start Script for Windows

echo.
echo 🚀 StocksBot Quick Start
echo ========================
echo.

REM Check if Python is installed
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ Python is not installed. Please install Python 3.9 or later.
    exit /b 1
)

REM Check if Node is installed
where node >nul 2>nul
if %errorlevel% neq 0 (
    echo ❌ Node.js is not installed. Please install Node.js 18 or later.
    exit /b 1
)

echo ✅ Python and Node.js are installed
echo.

REM Install backend dependencies
echo 📦 Installing backend dependencies...
cd backend
pip install -q -r requirements.txt
cd ..
echo ✅ Backend dependencies installed
echo.

REM Install UI dependencies
echo 📦 Installing UI dependencies...
cd ui
npm install --silent
cd ..
echo ✅ UI dependencies installed
echo.

REM Install Tauri CLI
echo 📦 Installing Tauri CLI...
npm install --silent
echo ✅ Tauri CLI installed
echo.

echo ✅ Setup complete!
echo.
echo To run the application:
echo.
echo Terminal 1 (Backend):
echo   cd backend ^&^& python app.py
echo.
echo Terminal 2 (Frontend):
echo   cd ui ^&^& npm run dev
echo.
echo Then open: http://localhost:1420
echo.
pause
