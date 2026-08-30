#!/usr/bin/env bash
# build.sh — Top-level build: lint, compile-check, and test all components
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔══════════════════════════════════════════╗"
echo "║       LifeLog — Full Build & Verify      ║"
echo "╚══════════════════════════════════════════╝"
echo ""

COMPONENTS=(
    "server"
    "diarization"
    "speaker-id"
    "transcription-worker"
    "dashboard"
    "firmware-ota"
)
TOTAL_PASS=0
TOTAL_FAIL=0
FAILED_COMPONENTS=()

for component in "${COMPONENTS[@]}"; do
    if [ ! -f "$component/build.sh" ]; then
        echo "⚠ $component/build.sh not found — skipping"
        continue
    fi

    echo "▶ $component"
    echo "────────────────────────────────────────────"

    if bash "$component/build.sh"; then
        TOTAL_PASS=$((TOTAL_PASS + 1))
    else
        TOTAL_FAIL=$((TOTAL_FAIL + 1))
        FAILED_COMPONENTS+=("$component")
    fi

    echo ""
done

# --- Final summary ---
echo "╔══════════════════════════════════════════╗"
echo "║            BUILD SUMMARY                 ║"
echo "╠══════════════════════════════════════════╣"

ALL_PASS=$((TOTAL_PASS + TOTAL_FAIL))
for component in "${COMPONENTS[@]}"; do
    if [[ " ${FAILED_COMPONENTS[*]:-} " =~ " ${component} " ]]; then
        echo "║  ✗ $component"
    elif [ -f "$component/build.sh" ]; then
        echo "║  ✓ $component"
    else
        echo "║  ⊘ $component (skipped)"
    fi
done

echo "╠══════════════════════════════════════════╣"
echo "║  Total: $TOTAL_PASS/$ALL_PASS passed, $TOTAL_FAIL failed"
echo "╚══════════════════════════════════════════╝"

if [ "$TOTAL_FAIL" -gt 0 ]; then
    echo ""
    echo "Failed components: ${FAILED_COMPONENTS[*]}"
    exit 1
fi

exit 0
