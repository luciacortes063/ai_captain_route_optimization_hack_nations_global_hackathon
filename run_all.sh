#!/bin/bash
set -e  # fail on error (no -u to avoid $! unbound issues)

echo "Starting AI Captain backend and frontend..."

# Start backend in the background and capture PID
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
BACKEND_PID=$!

if [ -z "$BACKEND_PID" ]; then
  echo "Failed to start backend (no PID captured). Check your Python/venv."
  exit 1
fi

echo "Backend starting (PID=${BACKEND_PID})... waiting until it's ready"

# Wait until /health responds (no curl/nc required)
python - <<'PY'
import time, urllib.request
url = "http://localhost:8000/health"
while True:
    try:
        with urllib.request.urlopen(url, timeout=1) as r:
            if r.status == 200:
                print("Backend is up")
                break
    except Exception:
        time.sleep(1)
PY

# Start static frontend
echo "Starting frontend on http://localhost:5500 ..."
cd frontend
python -m http.server 5500 --bind 127.0.0.1
