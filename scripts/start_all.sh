#!/bin/bash
# One-container start (Railway): seed the data folder, start the API inside the container, wait
# until it is healthy, then serve the UI on $PORT. If either process stops, the container exits
# (and Railway restarts it).
set -e
API_VENV="${API_VENV:-/opt/venv}"
FE_VENV="${FE_VENV:-/opt/fe-venv}"
API_PORT="${API_PORT:-8000}"  # internal only
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SEED_DIR="$ROOT/seed-data" DATA_ROOT="$ROOT/data" PATH="$API_VENV/bin:$PATH" SEED_ONLY=1 \
  sh scripts/start_api.sh
"$API_VENV/bin/python" scripts/seed_demo.py --if-empty

"$API_VENV/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$API_PORT" --timeout-keep-alive 75 &
API_PID=$!
for _ in $(seq 1 300); do
  if "$API_VENV/bin/python" -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$API_PORT/health', timeout=2)" \
      2>/dev/null; then
    break
  fi
  kill -0 "$API_PID" 2>/dev/null || { echo "API failed to start"; exit 1; }
  sleep 1
done
echo "API ready; starting the UI on port ${PORT:-8080}"

cd frontend
USE_MOCKS=false API_BASE_URL="http://127.0.0.1:$API_PORT/api/v1" \
  "$FE_VENV/bin/gunicorn" app:server --bind "[::]:${PORT:-8080}" --workers 1 --threads 8 \
  --timeout 120 &
WEB_PID=$!

trap 'kill "$API_PID" "$WEB_PID" 2>/dev/null' TERM INT
while kill -0 "$API_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do
  sleep 2
done
echo "a process stopped; exiting"
kill "$API_PID" "$WEB_PID" 2>/dev/null || true
exit 1
