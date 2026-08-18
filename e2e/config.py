"""E2E test configuration constants."""

import os
from pathlib import Path

# Load .env file if present
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# Server
SERVER_URL = "http://localhost:8444"
UPLOAD_PATH = "/api/v1/upload"
STATUS_PATH = "/api/v1/utterance/{utterance_id}/status"

# Auth
API_KEY = "e2e-test-key"

# Database (docker-compose maps 5433:5432)
DB_HOST = "localhost"
DB_PORT = 5433
DB_NAME = "lifelog"
DB_USER = "lifelog"
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

# Audio format (matching firmware)
SAMPLE_RATE = 16000
OPUS_BITRATE = "24k"
OPUS_FRAME_MS = 20
CHUNK_DURATION_S = 5.0

# Piper voice defaults
DEFAULT_VOICES = {
    "Alice": "en_US-lessac-medium",
    "Bob": "en_US-ryan-medium",
    "Carol": "en_US-amy-medium",
    "Dave": "en_US-joe-medium",
}

# Directories (relative to e2e/ — script runs from inside this dir)
VOICES_DIR = "voices"
CONVERSATIONS_DIR = "conversations"
