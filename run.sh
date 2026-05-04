#!/usr/bin/env bash
# Quick start: setup env, migrate, run server
# Usage: ./run.sh [port]  (default port: 8001)
set -e

PORT=${1:-8001}

if [ ! -f .env ]; then
    echo ">> Copying .env.example -> .env (silakan edit sebelum lanjut)"
    cp .env.example .env
fi

if [ ! -d .venv ]; then
    echo ">> Creating virtualenv..."
    python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo ">> Installing / updating requirements..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo ">> Init DB + seed (tabel & data default)..."
python -m scripts.init_db

echo ">> Migration v2 (tambah role baru, kolom baru)..."
python -m scripts.migrate_v2

echo ">> Migration v3 (sederhanakan role → 3 tingkatan, seed task permissions)..."
python -m scripts.migrate_v3

echo ""
echo ">> Server siap di http://0.0.0.0:${PORT}"
echo ">> Swagger UI : http://localhost:${PORT}/docs"
echo ">> Login      : admin / admin123  (GANTI DI PRODUKSI!)"
echo ""
exec uvicorn app.main:app --reload --host 0.0.0.0 --port "${PORT}"
