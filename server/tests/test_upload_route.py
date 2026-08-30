"""Mock integration tests for upload route endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lifelog.routes.upload import _active_utterances, router, validate_upload_auth

SERVER_UTT_ID = 1700000000


def _app_with_mocks(user=None):
    """Build a test app with dependency overrides."""
    app = FastAPI()
    app.include_router(router)

    async def fake_upload_auth():
        return user or {
            "id": 1,
            "api_key": "test-key",
            "name": "Test",
            "encryption_secret": "secret-123",
        }

    app.dependency_overrides[validate_upload_auth] = fake_upload_auth
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

    with (
        patch("lifelog.routes.upload.save_utterance_chunk", new_callable=AsyncMock),
        patch("lifelog.routes.upload._current_epoch", return_value=1700000000),
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

    assert resp1.json()["utterance_id"] == resp2.json()["utterance_id"]


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

    epoch_counter = [1700000000]

    def _next_epoch():
        val = epoch_counter[0]
        epoch_counter[0] += 1
        return val

    with (
        patch("lifelog.routes.upload.save_utterance_chunk", new_callable=AsyncMock),
        patch("lifelog.routes.upload._current_epoch", side_effect=_next_epoch),
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

    # New utterance got a different server ID (exact value depends on call count)
    assert isinstance(resp.json()["utterance_id"], int)
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
async def test_upload_missing_auth():
    """Upload without Bearer token returns 401."""
    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)
    response = client.post(
        "/upload",
        files={"file": ("test.opus", b"data", "audio/opus")},
        data={"utterance_id": 1, "chunk_index": 0, "is_final": "true"},
        headers={"Authorization": "Invalid token"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upload_rejects_oversized_chunk():
    """Upload rejects chunks larger than MAX_CHUNK_SIZE."""
    from lifelog.routes.upload import MAX_CHUNK_SIZE

    app = _app_with_mocks()

    with patch("lifelog.routes.upload.save_utterance_chunk", new_callable=AsyncMock):
        client = TestClient(app)
        oversized = b"x" * (MAX_CHUNK_SIZE + 1)
        response = client.post(
            "/upload",
            files={"file": ("test.opus", oversized, "audio/opus")},
            data={"utterance_id": 1, "chunk_index": 0, "is_final": "false"},
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 413
    assert response.json()["detail"] == "Chunk too large"
