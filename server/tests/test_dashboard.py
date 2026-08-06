"""Mock integration tests for dashboard routes."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lifelog.auth import validate_oidc_token
from lifelog.routes.dashboard import router


def _app_with_mocks(oidc_user=None, db_fn=None, db_mock=None):
    """Build a test app with dependency overrides."""
    app = FastAPI()
    app.include_router(router)

    async def fake_oidc(token=None):
        return oidc_user or {"id": 1, "name": "Test"}

    app.dependency_overrides[validate_oidc_token] = fake_oidc
    return app


@pytest.mark.asyncio
async def test_get_day_recordings():
    """Dashboard recordings endpoint returns list for a date."""
    fake_recordings = [
        {"id": 1, "timestamp": "2024-01-15T10:00:00", "summary": "Morning chat"},
        {"id": 2, "timestamp": "2024-01-15T14:00:00", "summary": "Afternoon call"},
    ]

    app = _app_with_mocks()

    with patch("lifelog.routes.dashboard.get_recordings_by_date", new_callable=AsyncMock, return_value=fake_recordings):
        client = TestClient(app)
        response = client.get("/recordings/2024-01-15")

    assert response.status_code == 200
    data = response.json()
    assert len(data["recordings"]) == 2
    assert data["recordings"][0]["summary"] == "Morning chat"


@pytest.mark.asyncio
async def test_get_recording_detail():
    """Recording detail endpoint returns full recording data."""
    fake_recording = {
        "id": 1,
        "timestamp": "2024-01-15T10:00:00",
        "summary": "Morning chat",
        "speakers": [{"name": "Alice", "text": "Hi"}],
        "todos": [],
    }

    app = _app_with_mocks()

    with patch("lifelog.routes.dashboard.get_recording", new_callable=AsyncMock, return_value=fake_recording):
        client = TestClient(app)
        response = client.get("/recording/1")

    assert response.status_code == 200
    assert response.json()["summary"] == "Morning chat"


@pytest.mark.asyncio
async def test_get_recording_not_found():
    """Recording detail returns 404 when not found."""
    app = _app_with_mocks()

    with patch("lifelog.routes.dashboard.get_recording", new_callable=AsyncMock, return_value=None):
        client = TestClient(app)
        response = client.get("/recording/999")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_todos():
    """Todos endpoint returns aggregated TODOs."""
    fake_todos = [
        {"task": "Buy milk", "owner": "Bob", "priority": "low"},
        {"task": "Fix bug", "owner": "Alice", "priority": "high"},
    ]

    app = _app_with_mocks()

    with patch("lifelog.routes.dashboard.get_todos", new_callable=AsyncMock, return_value=fake_todos):
        client = TestClient(app)
        response = client.get("/todos")

    assert response.status_code == 200
    assert len(response.json()["todos"]) == 2


@pytest.mark.asyncio
async def test_get_decisions():
    """Decisions endpoint returns recent decisions."""
    fake_decisions = [
        {"id": 1, "timestamp": "2024-01-15", "summary": "Decided to launch v2"},
    ]

    app = _app_with_mocks()

    with patch("lifelog.routes.dashboard.get_decisions", new_callable=AsyncMock, return_value=fake_decisions):
        client = TestClient(app)
        response = client.get("/decisions")

    assert response.status_code == 200
    assert len(response.json()["decisions"]) == 1


@pytest.mark.asyncio
async def test_get_unknown_speakers():
    """Unknown speakers endpoint returns recordings with Unknown speakers."""
    fake_unknowns = [
        {"id": 5, "timestamp": "2024-01-15", "speakers": [{"name": "Unknown"}], "audio_filename": "abc.enc"},
    ]

    app = _app_with_mocks()

    with patch("lifelog.routes.dashboard.get_unknown_speakers", new_callable=AsyncMock, return_value=fake_unknowns):
        client = TestClient(app)
        response = client.get("/unknown-speakers")

    assert response.status_code == 200
    assert len(response.json()["recordings"]) == 1
