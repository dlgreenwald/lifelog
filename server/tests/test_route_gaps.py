"""Tests for previously untested route functions: get_calendar, get_audio, rerun_identification."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lifelog.auth import validate_oidc_token
from lifelog.routes.dashboard import router as dashboard_router
from lifelog.routes.speakers import rerun_identification
from lifelog.routes.speakers import router as speakers_router


class _MockPoolConnection:
    def __init__(self, conn):
        self._conn = conn
    async def __aenter__(self):
        return self._conn
    async def __aexit__(self, *args):
        return False


def _app_with_mocks(oidc_user=None):
    app = FastAPI()
    app.include_router(dashboard_router)
    app.include_router(speakers_router)

    async def fake_oidc(token=None):
        return oidc_user or {"id": 1, "name": "Test", "encryption_secret": "sec"}

    app.dependency_overrides[validate_oidc_token] = fake_oidc
    return app


def _make_pool(mock_conn):
    pool = MagicMock()
    pool.acquire.return_value = _MockPoolConnection(mock_conn)
    return pool


# --- get_calendar ---


@pytest.mark.asyncio
async def test_get_calendar():
    """get_calendar returns dates with recording counts."""
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [
        {"date": "2024-01-15", "count": 3},
        {"date": "2024-01-20", "count": 1},
    ]
    pool = _make_pool(mock_conn)

    app = _app_with_mocks()

    with patch("lifelog.database.pool", pool):
        client = TestClient(app)
        response = client.get("/calendar/2024/1")

    assert response.status_code == 200
    data = response.json()
    assert len(data["dates"]) == 2
    assert data["dates"][0]["count"] == 3


# --- get_audio ---


@pytest.mark.asyncio
async def test_get_audio():
    """get_audio decrypts and streams audio file."""
    fake_audio = b"decrypted-opus-bytes"

    app = _app_with_mocks({"id": 1, "name": "Test", "encryption_secret": "sec"})

    with patch("lifelog.routes.dashboard.audio_crypto") as mock_crypto:
        mock_crypto.decrypt_audio.return_value = fake_audio

        client = TestClient(app)
        response = client.get("/audio/test-file.enc")

    assert response.status_code == 200
    assert response.content == fake_audio
    assert response.headers["content-type"] == "audio/opus"


# --- rerun_identification ---


@pytest.mark.asyncio
async def test_rerun_identification_processes_all_unknowns():
    """rerun_identification decrypts audio and re-identifies speakers for each recording."""
    user = {"id": 1, "encryption_secret": "sec-123"}

    fake_recordings = [
        {"id": 10, "audio_filename": "rec1.enc", "speakers": [{"name": "Unknown"}]},
        {"id": 20, "audio_filename": "rec2.enc", "speakers": [{"name": "Unknown"}]},
    ]

    with (
        patch("lifelog.routes.speakers.get_unknown_speakers", new_callable=AsyncMock, return_value=fake_recordings),
        patch("lifelog.routes.speakers.audio_crypto") as mock_crypto,
        patch("lifelog.routes.speakers.identify_speakers", new_callable=AsyncMock) as mock_identify,
        patch("lifelog.routes.speakers.update_recording_speakers", new_callable=AsyncMock) as mock_update,
    ):
        mock_crypto.decrypt_audio.return_value = b"decrypted"
        mock_identify.return_value = [{"name": "Alice", "start": 0.0, "end": 2.0}]

        await rerun_identification(user)

    assert mock_crypto.decrypt_audio.call_count == 2
    assert mock_identify.call_count == 2
    assert mock_update.call_count == 2

    mock_crypto.decrypt_audio.assert_any_call("rec1.enc", 1, "sec-123")
    mock_crypto.decrypt_audio.assert_any_call("rec2.enc", 1, "sec-123")


@pytest.mark.asyncio
async def test_rerun_identification_no_unknowns():
    """rerun_identification does nothing when there are no unknowns."""
    user = {"id": 1, "encryption_secret": "sec"}

    with (
        patch("lifelog.routes.speakers.get_unknown_speakers", new_callable=AsyncMock, return_value=[]),
        patch("lifelog.routes.speakers.audio_crypto") as mock_crypto,
        patch("lifelog.routes.speakers.identify_speakers", new_callable=AsyncMock) as mock_identify,
        patch("lifelog.routes.speakers.update_recording_speakers", new_callable=AsyncMock) as mock_update,
    ):
        await rerun_identification(user)

    mock_crypto.decrypt_audio.assert_not_called()
    mock_identify.assert_not_awaited()
    mock_update.assert_not_awaited()
