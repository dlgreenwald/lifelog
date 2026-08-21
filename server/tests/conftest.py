import os
import tempfile

# Set env vars BEFORE any lifelog imports so pydantic-settings picks them up
os.environ.setdefault("POSTGRES_PASSWORD", "test-password")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("AUDIO_STORAGE_PATH", tempfile.mkdtemp())

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_pool():
    """Mock asyncpg connection pool."""
    pool = AsyncMock()
    conn = AsyncMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.fixture
def mock_settings():
    """Return a mock settings object with test values."""
    return MagicMock(
        whisper_asr_url="http://localhost:9000",
        speaker_id_url="http://localhost:8443",
        openai_base_url="http://localhost:11434/v1",
        openai_api_key="ollama",
        openai_model="llama3",
        oidc_issuer_url="https://auth.test.com",
        oidc_client_id="test-client",
        audio_storage_path=tempfile.mkdtemp(),
    )


@pytest.fixture
def fake_user():
    """Return a fake authenticated user dict."""
    return {
        "id": 1,
        "api_key": "test-key-123",
        "oidc_sub": "user-oidc-sub",
        "name": "Test User",
        "encryption_secret": "test-encryption-secret-abc123",
    }
