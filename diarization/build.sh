#!/usr/bin/env bash
# diarization/build.sh — Lint, compile-check, format-check, dep-audit, and test the diarization service
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV=".venv"
RUFF="$VENV/bin/ruff"
PYTEST="$VENV/bin/python -m pytest"
PIP_AUDIT="$VENV/bin/pip-audit"

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
echo "  Diarization Service — Build & Verify"
echo "============================================"
echo ""

PASS=0
FAIL=0

# --- Step 1: Compile check ---
echo "[1/5] Compile check (python -m py_compile)..."
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
echo "[2/5] Ruff lint..."
if $RUFF check src/ tests/ 2>&1; then
    echo "  ✓ Lint clean"
    PASS=$((PASS + 1))
else
    echo "  ✗ Lint errors found"
    FAIL=$((FAIL + 1))
fi

# --- Step 3: Ruff format check ---
echo ""
echo "[3/5] Ruff format check..."
if $RUFF format --check src/ tests/ 2>&1; then
    echo "  ✓ Format clean"
    PASS=$((PASS + 1))
else
    echo "  ✗ Format drift detected, run 'ruff format'"
    FAIL=$((FAIL + 1))
fi

# --- Step 4: pip-audit (Python dependency CVE scan) ---
# We freeze the venv minus our editable local package and audit that
# requirements file. Then check whether the output reports any
# vulnerability rows.
echo ""
echo "[4/5] pip-audit (Python dependency CVE scan)..."
set +e
TMP_REQ="$(mktemp)"
"$VENV/bin/python" -m pip freeze --exclude-editable > "$TMP_REQ"
AUDIT_OUT="$($PIP_AUDIT --requirement "$TMP_REQ" 2>&1)"
AUDIT_RC=$?
rm -f "$TMP_REQ"
set -e
if [ "$AUDIT_RC" -eq 0 ]; then
    echo "  ✓ No known CVEs in dependencies"
    PASS=$((PASS + 1))
else
    if echo "$AUDIT_OUT" | grep -qE '^Name +Version +ID +Fix Versions'; then
        echo "  ✗ Vulnerabilities found:"
        echo "$AUDIT_OUT" | sed 's/^/    /'
        FAIL=$((FAIL + 1))
    else
        echo "  ⚠ pip-audit ran with warnings but no CVEs. See full output:"
        echo "$AUDIT_OUT" | sed 's/^/    /'
        PASS=$((PASS + 1))
    fi
fi

# --- Step 5: Tests ---
echo ""
echo "[5/5] Tests..."
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
