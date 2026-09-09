"""Mock integration tests for speaker rename/merge/delete routes."""

from unittest.mock import AsyncMock, patch

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
async def test_rename_speaker():
    """Rename returns ok with the new name."""
    app = _app_with_mocks()

    with patch(
        "lifelog.routes.speakers.rename_speaker",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_rename:
        client = TestClient(app)
        response = client.post(
            "/rename", json={"speaker_id": 9, "name": "Alice Ashford"}
        )

    assert response.status_code == 200
    data = response.json()
    assert data == {"ok": True, "speaker_id": 9, "name": "Alice Ashford"}
    mock_rename.assert_awaited_once_with(1, 9, "Alice Ashford")


@pytest.mark.asyncio
async def test_rename_speaker_not_found():
    """Renaming an unknown speaker returns 404."""
    app = _app_with_mocks()

    with patch(
        "lifelog.routes.speakers.rename_speaker",
        new_callable=AsyncMock,
        return_value=False,
    ):
        client = TestClient(app)
        response = client.post(
            "/rename", json={"speaker_id": 999, "name": "Alice Ashford"}
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Speaker not found"


@pytest.mark.asyncio
async def test_rename_speaker_duplicate_name():
    """Renaming to an existing name returns 409."""
    import asyncpg

    app = _app_with_mocks()

    async def raise_duplicate(*args, **kwargs):
        raise asyncpg.UniqueViolationError("duplicate key value")

    with patch(
        "lifelog.routes.speakers.rename_speaker",
        new_callable=AsyncMock,
        side_effect=raise_duplicate,
    ):
        client = TestClient(app)
        response = client.post(
            "/rename", json={"speaker_id": 9, "name": "Alice Ashford"}
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Speaker name already exists"


@pytest.mark.asyncio
async def test_merge_speakers():
    """Merge returns ok with the target id."""
    app = _app_with_mocks()

    with patch(
        "lifelog.routes.speakers.merge_speakers",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_merge:
        client = TestClient(app)
        response = client.post("/merge", json={"source_id": 3, "target_id": 9})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "speaker_id": 9}
    mock_merge.assert_awaited_once_with(1, 3, 9)


@pytest.mark.asyncio
async def test_merge_speakers_self_merge():
    """Merging a speaker into itself returns 400."""
    app = _app_with_mocks()

    with patch(
        "lifelog.routes.speakers.merge_speakers", new_callable=AsyncMock
    ) as mock_merge:
        client = TestClient(app)
        response = client.post("/merge", json={"source_id": 9, "target_id": 9})

    assert response.status_code == 400
    assert response.json()["detail"] == "Cannot merge a speaker into itself"
    mock_merge.assert_not_awaited()


@pytest.mark.asyncio
async def test_merge_speakers_not_found():
    """Merging an unknown speaker returns 404."""
    app = _app_with_mocks()

    with patch(
        "lifelog.routes.speakers.merge_speakers",
        new_callable=AsyncMock,
        return_value=False,
    ):
        client = TestClient(app)
        response = client.post("/merge", json={"source_id": 3, "target_id": 999})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_speaker():
    """Delete returns ok."""
    app = _app_with_mocks()

    with patch(
        "lifelog.routes.speakers.delete_speaker",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_delete:
        client = TestClient(app)
        response = client.delete("/9")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    mock_delete.assert_awaited_once_with(1, 9)


@pytest.mark.asyncio
async def test_delete_speaker_not_found():
    """Deleting an unknown speaker returns 404."""
    app = _app_with_mocks()

    with patch(
        "lifelog.routes.speakers.delete_speaker",
        new_callable=AsyncMock,
        return_value=False,
    ):
        client = TestClient(app)
        response = client.delete("/999")

    assert response.status_code == 404
