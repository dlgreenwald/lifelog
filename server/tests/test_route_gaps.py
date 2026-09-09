"""Tests for previously untested route functions: get_calendar, get_audio."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lifelog.auth import validate_oidc_token
from lifelog.routes.dashboard import router as dashboard_router
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

    app = _app_with_mocks(
        {"id": 1, "name": "Test", "encryption_secret": "sec", "key_salt": b"test-salt"}
    )

    with patch("lifelog.routes.dashboard.audio_crypto") as mock_crypto:
        mock_crypto.decrypt_audio.return_value = fake_audio

        client = TestClient(app)
        response = client.get("/audio/test-file.enc")

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/ogg"


def test_speaker_audio_legacy_fallback():
    recording = {"id": 10, "audio_filename": "legacy.enc", "speaker_segments": []}
    app = _app_with_mocks({"id": 1, "encryption_secret": "sec", "key_salt": b"salt"})
    with (
        patch(
            "lifelog.routes.dashboard.get_recording",
            new_callable=AsyncMock,
            return_value=recording,
        ),
        patch(
            "lifelog.routes.dashboard.audio_crypto.decrypt_audio", return_value=b"opus"
        ),
    ):
        response = TestClient(app).get("/recording/10/speaker/Unknown/audio")
    assert response.status_code == 200
    assert response.content == b"opus"
    assert response.headers["content-type"] == "audio/ogg"


def test_speaker_audio_rejects_other_users_recording():
    app = _app_with_mocks({"id": 1, "encryption_secret": "sec", "key_salt": b"salt"})
    with patch(
        "lifelog.routes.dashboard.get_recording",
        new_callable=AsyncMock,
        return_value=None,
    ):
        response = TestClient(app).get("/recording/10/speaker/Alice/audio")
    assert response.status_code == 404


def test_speaker_audio_uses_owned_matching_segments():
    recording = {
        "id": 10,
        "speaker_segments": [
            {"speaker": "Alice", "start": 2, "audio_filename": "late.enc"},
            {"speaker": "Alice", "start": 1, "audio_filename": "early.enc"},
        ],
    }
    app = _app_with_mocks({"id": 1, "encryption_secret": "sec", "key_salt": b"salt"})
    with (
        patch(
            "lifelog.routes.dashboard.get_recording",
            new_callable=AsyncMock,
            return_value=recording,
        ),
        patch(
            "lifelog.routes.dashboard.audio_crypto.decrypt_audio",
            side_effect=[b"early", b"late"],
        ) as decrypt,
        patch(
            "lifelog.routes.dashboard._concatenate_wav", return_value=b"RIFF"
        ) as concat,
    ):
        response = TestClient(app).get("/recording/10/speaker/Alice/audio")
    assert response.status_code == 200
    assert response.content == b"RIFF"
    assert [call.args[0] for call in decrypt.call_args_list] == [
        "early.enc",
        "late.enc",
    ]
    concat.assert_called_once_with([b"early", b"late"])
