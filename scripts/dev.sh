#!/usr/bin/env bash
# Start the API (port 8000) and the Vite dev server (port 5173); Ctrl+C stops both.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
py="$root/.venv/bin/python"
[ -x "$py" ] || { echo "Run: python3 -m venv .venv && .venv/bin/pip install -e 'backend[dev]'"; exit 1; }
[ -d "$root/frontend/node_modules" ] || (cd "$root/frontend" && npm install)
trap 'kill 0' EXIT
(cd "$root" && "$py" -m uvicorn docauth.main:app --reload --reload-dir backend --port 8000) &
(cd "$root/frontend" && npm run dev) &
echo "API: http://127.0.0.1:8000/docs   App: http://localhost:5173"
wait
