#!/usr/bin/env bash
# dashboard/build.sh — Type-check, build, and test the React dashboard
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================"
echo "  Dashboard — Build & Verify"
echo "============================================"
echo ""

PASS=0
FAIL=0

# --- Step 1: TypeScript compile check ---
echo "[1/4] TypeScript type check (tsc --noEmit)..."
TSC_OUTPUT=$(npx tsc --noEmit 2>&1 | grep -v 'npm warn\|npm notice' || true)
if [ -z "$TSC_OUTPUT" ]; then
    echo "  ✓ Type check clean"
    PASS=$((PASS + 1))
else
    echo "$TSC_OUTPUT"
    echo "  ✗ Type errors found"
    FAIL=$((FAIL + 1))
fi

# --- Step 2: Vite production build ---
echo ""
echo "[2/4] Production build (vite build)..."
if npx vite build 2>&1 | grep -v 'npm warn\|npm notice' | tail -5; then
    echo "  ✓ Build successful"
    PASS=$((PASS + 1))
else
    echo "  ✗ Build failed"
    FAIL=$((FAIL + 1))
fi

# --- Step 3: Tests ---
echo ""
echo "[3/4] Tests (vitest)..."
VITEST_OUTPUT=$(npx vitest run 2>&1 | grep -v 'npm warn\|npm notice')
echo "$VITEST_OUTPUT" | tail -5
if echo "$VITEST_OUTPUT" | grep -q "passed"; then
    echo "  ✓ Tests passed"
    PASS=$((PASS + 1))
else
    echo "  ✗ Tests failed"
    FAIL=$((FAIL + 1))
fi

# --- Step 4: Bundle size ---
echo ""
echo "[4/4] Bundle size..."
if [ -d "dist" ]; then
    SIZE=$(du -sh dist | cut -f1)
    echo "  ✓ Bundle size: $SIZE"
    PASS=$((PASS + 1))
else
    echo "  ✗ No dist/ directory"
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
