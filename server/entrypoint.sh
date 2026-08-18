#!/bin/bash
set -e

echo "[ENTRYPOINT] Running migrations..."
python3 migrate.py

echo "[ENTRYPOINT] Starting uvicorn..."
exec uvicorn lifelog.main:app --host 0.0.0.0 --port 8443
