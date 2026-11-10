#!/usr/bin/env bash
# Run the full demo: backend (:8000) + Dash front end (:8050).
# Uses Docker Compose when available, otherwise runs both locally with uv.
#   scripts/demo.sh            auto
#   scripts/demo.sh --local    force local
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ "${1:-}" != "--local" ]] && command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "▶ docker compose up --build  (UI http://localhost:8050 · API http://localhost:8000/docs)"
  exec docker compose up --build
fi

command -v uv >/dev/null 2>&1 || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }
echo "▶ installing dependencies (uv sync)…"
uv sync -q
(cd frontend && uv sync -q --no-dev)
uv run python scripts/seed_demo.py --if-empty

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

uv run uvicorn app.main:app --port 8000 &
pids+=($!)
for _ in $(seq 1 60); do curl -sf http://localhost:8000/health >/dev/null && break; sleep 0.5; done

(cd frontend && USE_MOCKS=false API_BASE_URL=http://localhost:8000/api/v1 DASH_DEBUG=false \
  uv run python app.py) &
pids+=($!)

echo
echo "  Transition Studio is running"
echo "  UI   http://localhost:8050   (demo@advisor.test / demo1234)"
echo "  API  http://localhost:8000/docs"
echo "  Ctrl+C to stop"
wait
