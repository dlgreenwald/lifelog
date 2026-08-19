"""Mock integration tests for upload route endpoint."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lifelog.auth import validate_api_key
from lifelog.routes.upload import _active_utterances, router

SERVER_UTT_ID = 1700000000


def _app_with_mocks(user=None):
    """Build a test app with dependency overrides."""
    app = FastAPI()
    app.include_router(router)

    async def fake_api_key(x_api_key: str = ""):
        return user or {"id": 1, "api_key": "test-key", "name": "Test", "encryption_secret": "secret-123"}

    app.dependency_overrides[validate_api_key] = fake_api_key
    return app


@pytest.fixture(autouse=True)
def _clear_active_utterances():
    """Reset tracking state before every test."""
    _active_utterances.clear()
    yield
    _active_utterances.clear()


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

    with (
        patch("lifelog.routes.upload.save_utterance_chunk", new_callable=AsyncMock),
        patch("lifelog.routes.upload._current_epoch", return_value=SERVER_UTT_ID),
    ):
        client = TestClient(app)
        response = client.post(
            "/upload",
            files={"file": ("chunk.opus", b"chunk-data", "audio/opus")},
            data={"utterance_id": 5, "chunk_index": 0, "is_final": "false"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "chunk_stored"
    assert data["utterance_id"] == SERVER_UTT_ID
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
        patch("lifelog.routes.upload._current_epoch", return_value=SERVER_UTT_ID),
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
    assert data["utterance_id"] == SERVER_UTT_ID


@pytest.mark.asyncio
async def test_upload_new_utterance_on_device_id_change():
    """Different device utterance_ids get different server IDs."""
    mock_user = {
        "id": 1,
        "api_key": "test-key",
        "name": "Test",
        "encryption_secret": "secret-123",
    }
    app = _app_with_mocks(mock_user)

    epoch_values = [1700000000, 1700000001]

    with (
        patch("lifelog.routes.upload.save_utterance_chunk", new_callable=AsyncMock),
        patch("lifelog.routes.upload._current_epoch", side_effect=epoch_values),
    ):
        client = TestClient(app)

        resp1 = client.post(
            "/upload",
            files={"file": ("c1.opus", b"data1", "audio/opus")},
            data={"utterance_id": 1, "chunk_index": 0, "is_final": "false"},
        )
        resp2 = client.post(
            "/upload",
            files={"file": ("c2.opus", b"data2", "audio/opus")},
            data={"utterance_id": 2, "chunk_index": 0, "is_final": "false"},
        )

    assert resp1.json()["utterance_id"] == 1700000000
    assert resp2.json()["utterance_id"] == 1700000001
    assert resp1.json()["utterance_id"] != resp2.json()["utterance_id"]


@pytest.mark.asyncio
async def test_upload_new_utterance_on_chunk_index_reset():
    """chunk_index resetting to 0 with same device id signals new utterance."""
    mock_user = {
        "id": 1,
        "api_key": "test-key",
        "name": "Test",
        "encryption_secret": "secret-123",
    }
    app = _app_with_mocks(mock_user)

    epoch_values = [1700000000, 1700000001]

    with (
        patch("lifelog.routes.upload.save_utterance_chunk", new_callable=AsyncMock),
        patch("lifelog.routes.upload._current_epoch", side_effect=epoch_values),
        patch("lifelog.routes.upload.database.pool") as mock_pool,
    ):
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        client = TestClient(app)

        # Utterance 1: chunks 0, 1, 2
        client.post(
            "/upload",
            files={"file": ("c0.opus", b"d", "audio/opus")},
            data={"utterance_id": 5, "chunk_index": 0, "is_final": "false"},
        )
        client.post(
            "/upload",
            files={"file": ("c1.opus", b"d", "audio/opus")},
            data={"utterance_id": 5, "chunk_index": 1, "is_final": "false"},
        )
        client.post(
            "/upload",
            files={"file": ("c2.opus", b"d", "audio/opus")},
            data={"utterance_id": 5, "chunk_index": 2, "is_final": "false"},
        )
        # Utterance 2: chunk_index resets to 0
        resp = client.post(
            "/upload",
            files={"file": ("c3.opus", b"d", "audio/opus")},
            data={"utterance_id": 5, "chunk_index": 0, "is_final": "false"},
        )

    # First utterance got 1700000000, second got 1700000001
    assert resp.json()["utterance_id"] == 1700000001
    # Old utterance was enqueued (finalize called)
    assert mock_conn.execute.call_count >= 1


@pytest.mark.asyncio
async def test_upload_finalize_on_is_final():
    """is_final removes entry from active tracking."""
    mock_user = {
        "id": 1,
        "api_key": "test-key",
        "name": "Test",
        "encryption_secret": "secret-123",
    }
    app = _app_with_mocks(mock_user)

    with (
        patch("lifelog.routes.upload.save_utterance_chunk", new_callable=AsyncMock),
        patch("lifelog.routes.upload._current_epoch", return_value=SERVER_UTT_ID),
        patch("lifelog.routes.upload.database.pool") as mock_pool,
    ):
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        client = TestClient(app)

        # Store a chunk first
        client.post(
            "/upload",
            files={"file": ("c0.opus", b"d", "audio/opus")},
            data={"utterance_id": 3, "chunk_index": 0, "is_final": "false"},
        )
        assert 3 in _active_utterances.get(1, {})

        # Finalize
        resp = client.post(
            "/upload",
            files={"file": ("c1.opus", b"d", "audio/opus")},
            data={"utterance_id": 3, "chunk_index": 1, "is_final": "true"},
        )

    assert resp.json()["status"] == "enqueued"
    assert 3 not in _active_utterances.get(1, {})


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
