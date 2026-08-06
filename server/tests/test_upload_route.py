"""Mock integration tests for upload route endpoint."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lifelog.auth import validate_api_key
from lifelog.routes.upload import router


def _app_with_mocks(user=None):
    """Build a test app with dependency overrides."""
    app = FastAPI()
    app.include_router(router)

    async def fake_api_key(x_api_key: str = ""):
        return user or {"id": 1, "api_key": "test-key", "name": "Test", "encryption_secret": "secret-123"}

    app.dependency_overrides[validate_api_key] = fake_api_key
    return app


@pytest.mark.asyncio
async def test_upload_audio_full_pipeline():
    """Upload route runs full pipeline: transcribe → diarize → identify → LLM → save."""
    mock_user = {
        "id": 1,
        "api_key": "test-key",
        "name": "Test",
        "encryption_secret": "secret-123",
    }

    fake_transcript = {"text": "Hello world", "segments": [{"start": 0.0, "end": 2.0, "text": "Hello"}]}
    fake_diarization = [{"speaker": "SPEAKER_00", "start": 0.0, "end": 2.0}]
    fake_speakers = [{"name": "Alice", "start": 0.0, "end": 2.0}]
    fake_llm_result = {
        "summary": "A short chat",
        "conversation_changes": [],
        "decisions": [],
        "todos": [],
        "calendar": [],
        "notes": [],
    }

    app = _app_with_mocks(mock_user)

    with (
        patch("lifelog.routes.upload.transcribe", return_value=fake_transcript),
        patch("lifelog.routes.upload.diarize", new_callable=AsyncMock, return_value=fake_diarization),
        patch("lifelog.routes.upload.identify_speakers", new_callable=AsyncMock, return_value=fake_speakers),
        patch("lifelog.routes.upload.summarize", return_value=fake_llm_result),
        patch("lifelog.routes.upload.save_recording", new_callable=AsyncMock, return_value=42),
        patch("lifelog.routes.upload.audio_crypto") as mock_crypto,
    ):
        mock_crypto.encrypt_audio.return_value = "encrypted-abc.enc"

        client = TestClient(app)
        response = client.post(
            "/upload",
            files={"file": ("test.opus", b"fake-opus-data", "audio/opus")},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processed"
    assert data["recording_id"] == 42


@pytest.mark.asyncio
async def test_upload_missing_api_key():
    """Upload without API key returns 422 (missing required header)."""
    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)
    response = client.post("/upload", files={"file": ("test.opus", b"data", "audio/opus")})

    assert response.status_code == 422
