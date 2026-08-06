#!/usr/bin/env bash
# firmware/build.sh — Compile-check the ESP32 firmware
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================"
echo "  Firmware — Build & Verify"
echo "============================================"
echo ""

PASS=0
FAIL=0

# --- Step 1: Check PlatformIO is installed ---
echo "[1/3] Checking PlatformIO..."
if ! command -v pio &>/dev/null; then
    echo "  ⊘ PlatformIO not installed — skipping firmware build"
    echo "    Install: pip install platformio"
    echo "    Skipping firmware checks (not a failure)"
    exit 0
fi
echo "  ✓ PlatformIO found: $(pio --version)"
PASS=$((PASS + 1))

# --- Step 2: Compile check ---
echo ""
echo "[2/3] Compile check (pio run)..."
if pio run 2>&1 | tail -5; then
    echo "  ✓ Firmware compiles"
    PASS=$((PASS + 1))
else
    echo "  ✗ Compilation failed"
    FAIL=$((FAIL + 1))
fi

# --- Step 3: Check config completeness ---
echo ""
echo "[3/3] Config validation..."
CONFIG_FAIL=0
if grep -q 'your-server.local' src/config.h; then
    echo "  ⚠ SERVER_HOST not configured (still default)"
    CONFIG_FAIL=1
fi
if grep -q 'your-api-key-here' src/config.h; then
    echo "  ⚠ API_KEY not configured (still default)"
    CONFIG_FAIL=1
fi
if grep -q 'your-wifi-ssid' src/config.h; then
    echo "  ⚠ WIFI_SSID not configured (still default)"
    CONFIG_FAIL=1
fi
if [ "$CONFIG_FAIL" -eq 0 ]; then
    echo "  ✓ Config looks configured"
    PASS=$((PASS + 1))
else
    echo "  ⚠ Defaults detected — configure before flashing"
    PASS=$((PASS + 1))
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
