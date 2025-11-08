#!/bin/bash
set -e

echo "Starting AI Captain backend and frontend..."

# Start backend from repo root (module path)
(uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000) &

# Wait a bit so backend comes up
sleep 5

# Start static frontend
(cd frontend && python -m http.server 5500)
