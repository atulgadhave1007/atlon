@echo off
echo ============================================
echo   Atlon HRMS — Development Startup
echo ============================================
echo.

cd /d "%~dp0backend"

if not exist ".env" (
    echo [WARN] No .env file found. Copying from .env.example...
    copy .env.example .env
    echo [INFO] Please edit backend\.env with your configuration.
    echo.
)

echo [INFO] Checking Python environment...
python --version 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.12+
    pause
    exit /b 1
)

if not exist "venv\Scripts\activate.bat" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
)

echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

echo [INFO] Installing dependencies...
pip install -r requirements.txt --quiet

echo [INFO] Creating database tables...
python -c "from app import create_app; app = create_app(); print('[OK] Database ready')"

set /p seed="Seed demo data? (y/N): "
if /i "%seed%"=="y" (
    echo [INFO] Seeding demo data...
    python seed_demo.py
)

echo.
echo [INFO] Starting Flask development server...
echo [INFO] API: http://localhost:5000
echo [INFO] Health: http://localhost:5000/health
echo [INFO] Login: http://localhost:5173 (or open frontend/public/index.html)
echo.
set FLASK_ENV=development
python run.py
