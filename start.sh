#!/bin/bash
set -e

echo "============================================"
echo "  Atlon HRMS — Development Startup"
echo "============================================"
echo ""

cd "$(dirname "$0")/backend"

if [ ! -f ".env" ]; then
    echo "[WARN] No .env file found. Copying from .env.example..."
    cp .env.example .env
    echo "[INFO] Edit backend/.env with your configuration."
fi

if [ ! -d "venv" ]; then
    echo "[INFO] Creating virtual environment..."
    python3 -m venv venv
fi

echo "[INFO] Activating virtual environment..."
source venv/bin/activate

echo "[INFO] Installing dependencies..."
pip install -r requirements.txt --quiet

echo "[INFO] Initializing database..."
python -c "from app import create_app; app = create_app(); print('[OK] Database ready')"

read -p "Seed demo data? (y/N): " seed
if [[ "$seed" =~ ^[Yy]$ ]]; then
    echo "[INFO] Seeding demo data..."
    python seed_demo.py
fi

echo ""
echo "[INFO] Starting Flask development server on http://localhost:5000"
echo "[INFO] Open frontend/public/index.html in your browser"
echo ""
export FLASK_ENV=development
python run.py
