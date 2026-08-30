#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

VENV=".venv"
[ -d "$VENV" ] || uv venv "$VENV"
uv pip install -e ".[dev]" --quiet
"$VENV/bin/python" -m py_compile audio.py pipeline.py main.py
"$VENV/bin/ruff" check audio.py pipeline.py main.py
"$VENV/bin/python" -m pytest -q
