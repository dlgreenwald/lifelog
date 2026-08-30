#!/usr/bin/env bash
# server/build.sh — Lint, compile-check, and test the server orchestrator
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV=".venv"
RUFF="$VENV/bin/ruff"
PYTEST="$VENV/bin/python -m pytest"

# --- Bootstrap: ensure .venv exists with dev dependencies ---
if ! command -v uv >/dev/null 2>&1; then
    echo "  ! uv not on PATH; build.sh requires uv to set up the venv" >&2
    exit 1
fi
if [ ! -x "$VENV/bin/python" ]; then
    echo "[setup] Creating $VENV and installing dev dependencies..."
    uv venv "$VENV"
    uv pip install -e ".[dev]" --quiet
fi

echo "============================================"
echo "  Server Orchestrator — Build & Verify"
echo "============================================"
echo ""

PASS=0
FAIL=0

# --- Step 1: Compile check (syntax validation for every .py file) ---
echo "[1/3] Compile check (python -m py_compile)..."
COMPILE_FAIL=0
for f in $(find src -name '*.py' -not -path '*__pycache__*'); do
    if ! $VENV/bin/python -m py_compile "$f" 2>/dev/null; then
        echo "  ✗ $f"
        COMPILE_FAIL=1
    fi
done
if [ "$COMPILE_FAIL" -eq 0 ]; then
    echo "  ✓ All source files compile"
    PASS=$((PASS + 1))
else
    echo "  ✗ Compile errors found"
    FAIL=$((FAIL + 1))
fi

# --- Step 2: Ruff lint ---
echo ""
echo "[2/3] Ruff lint..."
if $RUFF check src/ tests/ 2>&1; then
    echo "  ✓ Lint clean"
    PASS=$((PASS + 1))
else
    echo "  ✗ Lint errors found"
    FAIL=$((FAIL + 1))
fi

# --- Step 3: Tests ---
echo ""
echo "[3/3] Tests..."
if $PYTEST tests/ -q 2>&1; then
    echo "  ✓ Tests passed"
    PASS=$((PASS + 1))
else
    echo "  ✗ Tests failed"
    FAIL=$((FAIL + 1))
fi

# --- Summary ---
echo ""
echo "============================================"
if [ "$FAIL" -eq 0 ]; then
    echo "  RESULT: $PASS/$((PASS + FAIL)) passed ✓"
    exit 0
else
    echo "  RESULT: $FAIL/$((PASS + FAIL)) failed ✗"
    exit 1
fi
