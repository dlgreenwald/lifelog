"""Tests for database module using mocked asyncpg pool.

asyncpg's pool.acquire() returns an async context manager directly
(not a coroutine). The mock must replicate this pattern.
"""
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class MockPoolConnection:
    """Simulates asyncpg pool.acquire() returning an async context manager."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        return False


def _make_mock_pool(mock_conn):
    """Create a mock pool whose acquire() returns an async context manager."""
    pool = MagicMock()
    pool.acquire.return_value = MockPoolConnection(mock_conn)
    return pool


@pytest.fixture
def mock_conn():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock()
    conn.fetch = AsyncMock()
    conn.execute = AsyncMock()
    return conn


@pytest.mark.asyncio
async def test_get_user_by_api_key(mock_conn):
    from lifelog.database import get_user_by_api_key

    fake_row = {"id": 1, "api_key": "key-123", "oidc_sub": None, "name": "Test", "encryption_secret": "sec"}
    mock_conn.fetchrow.return_value = fake_row
    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        result = await get_user_by_api_key("key-123")

    assert result == fake_row
    mock_conn.fetchrow.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_user_by_api_key_not_found(mock_conn):
    from lifelog.database import get_user_by_api_key

    mock_conn.fetchrow.return_value = None
    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        result = await get_user_by_api_key("nonexistent")

    assert result is None


@pytest.mark.asyncio
async def test_get_user_by_oidc_sub(mock_conn):
    from lifelog.database import get_user_by_oidc_sub

    fake_row = {"id": 2, "api_key": None, "oidc_sub": "oidc-abc", "name": "OIDC User", "encryption_secret": "sec"}
    mock_conn.fetchrow.return_value = fake_row
    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        result = await get_user_by_oidc_sub("oidc-abc")

    assert result == fake_row


@pytest.mark.asyncio
async def test_create_user(mock_conn):
    from lifelog.database import create_user

    mock_conn.fetchrow.return_value = {"id": 5}
    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        result = await create_user(api_key="new-key", oidc_sub="sub-1", name="New User")

    assert result["id"] == 5
    assert result["api_key"] == "new-key"
    assert len(result["encryption_secret"]) == 64


@pytest.mark.asyncio
async def test_save_recording(mock_conn):
    from lifelog.database import save_recording

    mock_conn.fetchrow.return_value = {"id": 42}
    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        recording_id = await save_recording(
            1, {"text": "Hello"}, [{"name": "Alice"}],
            {"summary": "Chat", "todos": [], "calendar": [], "notes": []},
            "file.enc",
        )

    assert recording_id == 42
    sql = mock_conn.fetchrow.call_args.args[0]
    assert "INSERT INTO recordings" in sql


@pytest.mark.asyncio
async def test_get_recordings_by_date(mock_conn):
    from lifelog.database import get_recordings_by_date

    mock_conn.fetch.return_value = [{"id": 1, "timestamp": datetime(2024, 1, 15, tzinfo=UTC), "summary": "Chat"}]
    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        result = await get_recordings_by_date(1, "2024-01-15")

    assert len(result) == 1
    assert result[0]["summary"] == "Chat"


@pytest.mark.asyncio
async def test_get_recording(mock_conn):
    from lifelog.database import get_recording

    mock_conn.fetchrow.return_value = {"id": 10, "user_id": 1, "summary": "Test"}
    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        result = await get_recording(1, 10)

    assert result["id"] == 10


@pytest.mark.asyncio
async def test_get_recording_not_found(mock_conn):
    from lifelog.database import get_recording

    mock_conn.fetchrow.return_value = None
    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        result = await get_recording(1, 999)

    assert result is None


@pytest.mark.asyncio
async def test_get_unknown_speakers(mock_conn):
    from lifelog.database import get_unknown_speakers

    mock_conn.fetch.return_value = [
        {"id": 5, "timestamp": datetime(2024, 1, 15, tzinfo=UTC), "speakers": [{"name": "Unknown"}], "audio_filename": "abc.enc"},
    ]
    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        result = await get_unknown_speakers(1)

    assert len(result) == 1


@pytest.mark.asyncio
async def test_update_speaker_name(mock_conn):
    from lifelog.database import update_speaker_name

    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        await update_speaker_name(10, "Unknown", "Alice")

    sql = mock_conn.execute.call_args.args[0]
    assert "UPDATE recordings" in sql
    assert "jsonb_set" in sql


@pytest.mark.asyncio
async def test_get_all_voiceprints(mock_conn):
    from lifelog.database import get_all_voiceprints

    mock_conn.fetch.return_value = [
        {"id": 1, "name": "Alice", "embedding": b"\x01\x02\x03"},
    ]
    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        result = await get_all_voiceprints(1)

    assert len(result) == 1
    assert result[0]["name"] == "Alice"


@pytest.mark.asyncio
async def test_save_voiceprint(mock_conn):
    from lifelog.database import save_voiceprint

    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        await save_voiceprint(1, "Alice", b"\x01\x02\x03")

    sql = mock_conn.execute.call_args.args[0]
    assert "INSERT INTO voiceprints" in sql
    assert "ON CONFLICT" in sql


@pytest.mark.asyncio
async def test_get_todos(mock_conn):
    from lifelog.database import get_todos

    mock_conn.fetch.return_value = [
        {
            "id": 1,
            "task": "Buy milk",
            "owner": "Bob",
            "due": None,
            "priority": "low",
            "completed": False,
            "completed_at": None,
            "created_at": datetime(2024, 1, 15, tzinfo=UTC),
            "recording_id": 10,
            "recording_timestamp": datetime(2024, 1, 15, tzinfo=UTC),
        },
    ]
    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        result = await get_todos(1)

    assert len(result) == 1
    assert result[0]["task"] == "Buy milk"
    assert result[0]["recording_id"] == 10
    assert result[0]["completed"] is False


@pytest.mark.asyncio
async def test_save_todos(mock_conn):
    from lifelog.database import save_todos

    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        await save_todos(
            recording_id=10,
            user_id=1,
            todos=[
                {"task": "Buy milk", "owner": "Bob", "priority": "low"},
                {"task": "Fix bug", "owner": "Alice", "priority": "high"},
            ],
        )

    assert mock_conn.execute.await_count == 2
    first_sql = mock_conn.execute.call_args_list[0].args[0]
    assert "INSERT INTO todos" in first_sql


@pytest.mark.asyncio
async def test_update_todo_completion(mock_conn):
    from lifelog.database import update_todo_completion

    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        await update_todo_completion(todo_id=5, completed=True)

    sql = mock_conn.execute.call_args.args[0]
    assert "UPDATE todos" in sql
    assert mock_conn.execute.call_args.args[1] is True
    assert mock_conn.execute.call_args.args[2] == 5


@pytest.mark.asyncio
async def test_delete_todo(mock_conn):
    from lifelog.database import delete_todo

    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        await delete_todo(todo_id=5)

    sql = mock_conn.execute.call_args.args[0]
    assert "DELETE FROM todos" in sql
    assert mock_conn.execute.call_args.args[1] == 5


@pytest.mark.asyncio
async def test_get_decisions(mock_conn):
    from lifelog.database import get_decisions

    mock_conn.fetch.return_value = [
        {"id": 1, "timestamp": datetime(2024, 1, 15, tzinfo=UTC), "summary": "Decided to go"},
    ]
    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        result = await get_decisions(1, limit=10)

    assert len(result) == 1


@pytest.mark.asyncio
async def test_update_recording_speakers(mock_conn):
    from lifelog.database import update_recording_speakers

    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        await update_recording_speakers(10, [{"name": "Alice"}])

    sql = mock_conn.execute.call_args.args[0]
    assert "UPDATE recordings" in sql
