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

    with patch(
        "lifelog.routes.dashboard.get_recordings_by_date",
        new_callable=AsyncMock,
        return_value=fake_recordings,
    ):
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

    with patch(
        "lifelog.routes.dashboard.get_recording",
        new_callable=AsyncMock,
        return_value=fake_recording,
    ):
        client = TestClient(app)
        response = client.get("/recording/1")

    assert response.status_code == 200
    assert response.json()["summary"] == "Morning chat"


@pytest.mark.asyncio
async def test_get_recording_not_found():
    """Recording detail returns 404 when not found."""
    app = _app_with_mocks()

    with patch(
        "lifelog.routes.dashboard.get_recording",
        new_callable=AsyncMock,
        return_value=None,
    ):
        client = TestClient(app)
        response = client.get("/recording/999")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_todos():
    """Todos endpoint returns all todos from the todos table."""
    fake_todos = [
        {
            "id": 1,
            "task": "Buy milk",
            "owner": "Bob",
            "due": None,
            "priority": "low",
            "completed": False,
            "completed_at": None,
            "created_at": "2024-01-15T10:00:00",
            "recording_id": 10,
            "recording_timestamp": "2024-01-15T10:00:00",
        },
        {
            "id": 2,
            "task": "Fix bug",
            "owner": "Alice",
            "due": "2024-01-20",
            "priority": "high",
            "completed": False,
            "completed_at": None,
            "created_at": "2024-01-15T11:00:00",
            "recording_id": 10,
            "recording_timestamp": "2024-01-15T10:00:00",
        },
    ]

    app = _app_with_mocks()

    with patch(
        "lifelog.routes.dashboard.get_todos",
        new_callable=AsyncMock,
        return_value=fake_todos,
    ):
        client = TestClient(app)
        response = client.get("/todos")

    assert response.status_code == 200
    assert len(response.json()["todos"]) == 2
    assert response.json()["todos"][0]["id"] == 1


@pytest.mark.asyncio
async def test_get_todos_for_date():
    """Todos for date endpoint returns todos from that day's recordings."""
    fake_todos = [
        {"id": 1, "task": "Buy milk", "owner": "Bob", "completed": False},
    ]

    app = _app_with_mocks()

    with patch(
        "lifelog.routes.dashboard.get_todos_for_date",
        new_callable=AsyncMock,
        return_value=fake_todos,
    ):
        client = TestClient(app)
        response = client.get("/todos/2024-01-15")

    assert response.status_code == 200
    assert len(response.json()["todos"]) == 1


@pytest.mark.asyncio
async def test_complete_todo():
    """Complete todo endpoint marks a todo as done."""
    app = _app_with_mocks()

    with (
        patch(
            "lifelog.routes.dashboard.get_todo_owner",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "lifelog.routes.dashboard.update_todo_completion", new_callable=AsyncMock
        ),
    ):
        client = TestClient(app)
        response = client.post("/todos/5/complete", json={"completed": True})

    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.asyncio
async def test_complete_todo_not_found():
    """Complete todo returns 404 for nonexistent todo."""
    app = _app_with_mocks()

    with patch(
        "lifelog.routes.dashboard.get_todo_owner",
        new_callable=AsyncMock,
        return_value=None,
    ):
        client = TestClient(app)
        response = client.post("/todos/999/complete", json={"completed": True})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_todo_endpoint():
    """Delete todo endpoint removes a todo."""
    app = _app_with_mocks()

    with (
        patch(
            "lifelog.routes.dashboard.get_todo_owner",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch("lifelog.routes.dashboard.delete_todo", new_callable=AsyncMock),
    ):
        client = TestClient(app)
        response = client.delete("/todos/5")

    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.asyncio
async def test_delete_todo_not_found():
    """Delete todo returns 404 for nonexistent todo."""
    app = _app_with_mocks()

    with patch(
        "lifelog.routes.dashboard.get_todo_owner",
        new_callable=AsyncMock,
        return_value=None,
    ):
        client = TestClient(app)
        response = client.delete("/todos/999")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_recording_todos():
    """Recording todos endpoint returns todos for a specific recording."""
    fake_todos = [
        {"id": 1, "task": "Buy milk", "completed": False},
    ]

    app = _app_with_mocks()

    with (
        patch(
            "lifelog.routes.dashboard.get_recording",
            new_callable=AsyncMock,
            return_value={"id": 10},
        ),
        patch(
            "lifelog.routes.dashboard.get_todos_for_recording",
            new_callable=AsyncMock,
            return_value=fake_todos,
        ),
    ):
        client = TestClient(app)
        response = client.get("/recording/10/todos")

    assert response.status_code == 200
    assert len(response.json()["todos"]) == 1


@pytest.mark.asyncio
async def test_get_decisions():
    """Decisions endpoint returns recent decisions."""
    fake_decisions = [
        {
            "id": 1,
            "decision": "Launch v2",
            "made_by": "Alice",
            "context": "Team agreed",
            "reason": "Deadline pressure",
            "archived": False,
            "created_at": "2024-01-15T10:00:00",
            "recording_id": 10,
            "recording_timestamp": "2024-01-15T10:00:00",
        },
    ]

    app = _app_with_mocks()

    with patch(
        "lifelog.routes.dashboard.get_decisions",
        new_callable=AsyncMock,
        return_value=fake_decisions,
    ):
        client = TestClient(app)
        response = client.get("/decisions")

    assert response.status_code == 200
    assert len(response.json()["decisions"]) == 1
    assert response.json()["decisions"][0]["decision"] == "Launch v2"


@pytest.mark.asyncio
async def test_get_recording_decisions():
    """Per-recording decisions endpoint returns decisions."""
    fake_recording = {"id": 10, "timestamp": "2024-01-15"}
    fake_decisions = [
        {
            "id": 1,
            "decision": "Go with A",
            "made_by": "Bob",
            "context": None,
            "reason": None,
            "archived": False,
            "created_at": "2024-01-15",
        },
    ]

    app = _app_with_mocks()

    with (
        patch(
            "lifelog.routes.dashboard.get_recording",
            new_callable=AsyncMock,
            return_value=fake_recording,
        ),
        patch(
            "lifelog.routes.dashboard.get_decisions_for_recording",
            new_callable=AsyncMock,
            return_value=fake_decisions,
        ),
    ):
        client = TestClient(app)
        response = client.get("/recording/10/decisions")

    assert response.status_code == 200
    assert len(response.json()["decisions"]) == 1


@pytest.mark.asyncio
async def test_archive_decision():
    """Archive decision endpoint returns 200."""
    app = _app_with_mocks()

    with (
        patch(
            "lifelog.routes.dashboard.get_decision_owner",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "lifelog.routes.dashboard.update_decision_archive", new_callable=AsyncMock
        ),
    ):
        client = TestClient(app)
        response = client.post("/decisions/1/archive", json={"archived": True})

    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.asyncio
async def test_delete_decision_endpoint():
    """Delete decision endpoint returns 200."""
    app = _app_with_mocks()

    with (
        patch(
            "lifelog.routes.dashboard.get_decision_owner",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch("lifelog.routes.dashboard.delete_decision", new_callable=AsyncMock),
    ):
        client = TestClient(app)
        response = client.delete("/decisions/1")

    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.asyncio
async def test_get_unknown_speakers():
    """Unknown speakers endpoint returns recordings with Unknown speakers."""
    fake_unknowns = [
        {
            "id": 5,
            "timestamp": "2024-01-15",
            "speakers": [{"name": "Unknown"}],
            "audio_filename": "abc.enc",
        },
    ]

    app = _app_with_mocks()

    with patch(
        "lifelog.routes.dashboard.get_unknown_speakers",
        new_callable=AsyncMock,
        return_value=fake_unknowns,
    ):
        client = TestClient(app)
        response = client.get("/unknown-speakers")

    assert response.status_code == 200
    assert len(response.json()["recordings"]) == 1


@pytest.mark.asyncio
async def test_create_todo():
    """Create todo endpoint returns id."""
    app = _app_with_mocks()

    with patch(
        "lifelog.routes.dashboard.create_todo", new_callable=AsyncMock, return_value=42
    ):
        client = TestClient(app)
        response = client.post(
            "/todos", json={"task": "Buy milk", "owner": "Bob", "priority": "high"}
        )

    assert response.status_code == 200
    assert response.json()["id"] == 42


@pytest.mark.asyncio
async def test_create_todo_missing_task():
    """Create todo returns 422 when task is empty (Pydantic validation)."""
    app = _app_with_mocks()

    client = TestClient(app)
    response = client.post("/todos", json={"task": "", "owner": "Bob"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_todo_standalone():
    """Create todo without recording_id creates standalone todo."""
    app = _app_with_mocks()

    with patch(
        "lifelog.routes.dashboard.create_todo", new_callable=AsyncMock, return_value=99
    ) as mock_create:
        client = TestClient(app)
        response = client.post("/todos", json={"task": "Standalone task"})

    assert response.status_code == 200
    assert response.json()["id"] == 99
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args
    assert call_kwargs.kwargs["recording_id"] is None


@pytest.mark.asyncio
async def test_create_decision():
    """Create decision endpoint returns id."""
    app = _app_with_mocks()

    with patch(
        "lifelog.routes.dashboard.create_decision",
        new_callable=AsyncMock,
        return_value=7,
    ):
        client = TestClient(app)
        response = client.post(
            "/decisions", json={"decision": "Use PostgreSQL", "made_by": "Alice"}
        )

    assert response.status_code == 200
    assert response.json()["id"] == 7


@pytest.mark.asyncio
async def test_create_decision_missing_text():
    """Create decision returns 422 when decision is empty (Pydantic validation)."""
    app = _app_with_mocks()

    client = TestClient(app)
    response = client.post("/decisions", json={"decision": "", "made_by": "Alice"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_decision_standalone():
    """Create decision without recording_id creates standalone decision."""
    app = _app_with_mocks()

    with patch(
        "lifelog.routes.dashboard.create_decision",
        new_callable=AsyncMock,
        return_value=88,
    ) as mock_create:
        client = TestClient(app)
        response = client.post("/decisions", json={"decision": "Use React"})

    assert response.status_code == 200
    assert response.json()["id"] == 88
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args
    assert call_kwargs.kwargs["recording_id"] is None
