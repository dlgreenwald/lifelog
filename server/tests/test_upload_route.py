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
async def test_upload_chunk_stored():
    """Upload with is_final=false stores chunk and returns chunk_stored."""
    mock_user = {
        "id": 1,
        "api_key": "test-key",
        "name": "Test",
        "encryption_secret": "secret-123",
    }
    app = _app_with_mocks(mock_user)

    with patch("lifelog.routes.upload.save_utterance_chunk", new_callable=AsyncMock):
        client = TestClient(app)
        response = client.post(
            "/upload",
            files={"file": ("chunk.opus", b"chunk-data", "audio/opus")},
            data={"utterance_id": 5, "chunk_index": 0, "is_final": "false"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "chunk_stored"
    assert data["utterance_id"] == 5
    assert data["chunk_index"] == 0


@pytest.mark.asyncio
async def test_upload_enqueue_on_final():
    """Upload with is_final=true stores chunk and enqueues for processing."""
    mock_user = {
        "id": 1,
        "api_key": "test-key",
        "name": "Test",
        "encryption_secret": "secret-123",
    }
    app = _app_with_mocks(mock_user)

    with (
        patch("lifelog.routes.upload.save_utterance_chunk", new_callable=AsyncMock),
        patch("lifelog.routes.upload.database.pool") as mock_pool,
    ):
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        client = TestClient(app)
        response = client.post(
            "/upload",
            files={"file": ("final.opus", b"final-data", "audio/opus")},
            data={"utterance_id": 10, "chunk_index": 2, "is_final": "true"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "enqueued"
    assert data["utterance_id"] == 10


@pytest.mark.asyncio
async def test_upload_missing_api_key():
    """Upload without API key returns 422 (missing required header)."""
    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)
    response = client.post(
        "/upload",
        files={"file": ("test.opus", b"data", "audio/opus")},
        data={"utterance_id": 1, "chunk_index": 0, "is_final": "true"},
    )

    assert response.status_code == 422
