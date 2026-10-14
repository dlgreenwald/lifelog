#!/bin/bash
# Lifelog MCP build + verification script
set -e

VENV=".venv"
PYTHON="${VENV}/bin/python"
PYTEST="${VENV}/bin/pytest"
RUFF="${VENV}/bin/ruff"

echo "=== lifelog-mcp build ==="

# venv bootstrap (only if .venv missing or --recreate passed)
if [ ! -d "${VENV}" ] || [ "$1" = "--recreate" ]; then
    echo "[bootstrap] Creating venv..."
    uv venv "${VENV}"
fi

echo "[1/4] Installing dependencies..."
uv pip install -e ".[dev]" --quiet

echo "[2/4] Checking syntax..."
"${PYTHON}" -m py_compile src/lifelog_mcp/__init__.py
"${PYTHON}" -m py_compile src/lifelog_mcp/config.py
"${PYTHON}" -m py_compile src/lifelog_mcp/auth.py
"${PYTHON}" -m py_compile src/lifelog_mcp/server.py
"${PYTHON}" -m py_compile src/lifelog_mcp/tools/__init__.py
"${PYTHON}" -m py_compile src/lifelog_mcp/tools/search.py
"${PYTHON}" -m py_compile src/lifelog_mcp/tools/recordings.py
"${PYTHON}" -m py_compile src/lifelog_mcp/tools/todos.py
"${PYTHON}" -m py_compile src/lifelog_mcp/tools/decisions.py
"${PYTHON}" -m py_compile src/lifelog_mcp/tools/speakers.py
echo "  syntax OK"

echo "[3/4] Running ruff..."
"${RUFF}" check src/ tests/ --quiet
echo "  ruff OK"

echo "[4/4] Running pytest..."
"${PYTEST}" tests/ -q
echo "  pytest OK"

echo "=== lifelog-mcp build PASSED ==="
