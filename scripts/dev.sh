#!/usr/bin/env bash
# Start QUASAR API (uvicorn) + frontend (Vite) for local demo.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

API_PORT="${API_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
SKIP_FRONTEND="${SKIP_FRONTEND:-0}"

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi

export QUASAR_ENV="${QUASAR_ENV:-development}"
export ALLOWED_ORIGINS="http://localhost:${FRONTEND_PORT},http://127.0.0.1:${FRONTEND_PORT}"

cleanup() {
  [[ -n "${API_PID:-}" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "${FE_PID:-}" ]] && kill "$FE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting API on http://127.0.0.1:${API_PORT} ..."
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port "$API_PORT" &
API_PID=$!

if [[ "$SKIP_FRONTEND" != "1" ]]; then
  if [[ ! -d frontend/node_modules ]]; then
    echo "Installing frontend deps (npm ci) ..."
    (cd frontend && npm ci)
  fi
  echo "Starting frontend on http://127.0.0.1:${FRONTEND_PORT} ..."
  (cd frontend && npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT") &
  FE_PID=$!
fi

echo
echo "API docs:  http://127.0.0.1:${API_PORT}/docs"
echo "Health:    http://127.0.0.1:${API_PORT}/health"
[[ "$SKIP_FRONTEND" != "1" ]] && echo "Frontend:  http://127.0.0.1:${FRONTEND_PORT}"
echo "Press Ctrl+C to stop."
wait "$API_PID"
