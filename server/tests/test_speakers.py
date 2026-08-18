"""Mock integration tests for speaker label route."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lifelog.auth import validate_oidc_token
from lifelog.routes.speakers import router


def _app_with_mocks(oidc_user=None):
    """Build a test app with dependency overrides."""
    app = FastAPI()
    app.include_router(router)

    async def fake_oidc(token=None):
        return oidc_user or {"id": 1, "name": "Test", "encryption_secret": "sec"}

    app.dependency_overrides[validate_oidc_token] = fake_oidc
    return app


@pytest.mark.asyncio
async def test_label_speaker():
    """Label speaker: update name, enroll embedding, save voiceprint, re-run ID."""
    mock_user = {"id": 1, "name": "Test", "encryption_secret": "sec"}
    mock_recording = {
        "id": 10,
        "user_id": 1,
        "audio_filename": "rec-abc.enc",
        "speakers": [{"name": "Unknown"}],
    }

    mock_enroll_response = MagicMock()
    mock_enroll_response.json.return_value = {"name": "Alice", "embedding": [1, 2, 3]}

    mock_http_client = AsyncMock()
    mock_http_client.post.return_value = mock_enroll_response
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=False)

    app = _app_with_mocks(mock_user)

    with (
        patch("lifelog.routes.speakers.get_recording", new_callable=AsyncMock, return_value=mock_recording),
        patch("lifelog.routes.speakers.update_speaker_name", new_callable=AsyncMock),
        patch("lifelog.routes.speakers.extract_speaker_audio", return_value=b"fake-audio"),
        patch("lifelog.routes.speakers.httpx.AsyncClient", return_value=mock_http_client),
        patch("lifelog.routes.speakers.save_voiceprint", new_callable=AsyncMock),
        patch("lifelog.routes.speakers.rerun_identification", new_callable=AsyncMock),
    ):
        client = TestClient(app)
        response = client.post(
            "/label",
            json={"recording_id": 10, "speaker_id": "Unknown", "label": "Alice"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "labeled"
    assert data["label"] == "Alice"


@pytest.mark.asyncio
async def test_label_speaker_recording_not_found():
    """Labeling a non-existent recording returns 404."""
    app = _app_with_mocks()

    with patch("lifelog.routes.speakers.get_recording", new_callable=AsyncMock, return_value=None):
        client = TestClient(app)
        response = client.post(
            "/label",
            json={"recording_id": 999, "speaker_id": "Unknown", "label": "Alice"},
        )

    assert response.status_code == 404
