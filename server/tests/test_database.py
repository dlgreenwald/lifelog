"""Tests for database module using mocked asyncpg pool.

asyncpg's pool.acquire() returns an async context manager directly
(not a coroutine). The mock must replicate this pattern.
"""

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


class MockTransaction:
    """Simulates conn.transaction() returning an async context manager."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _make_mock_pool(mock_conn):
    """Create a mock pool whose acquire() returns an async context manager."""
    pool = MagicMock()
    pool.acquire.return_value = MockPoolConnection(mock_conn)
    mock_conn.transaction = MagicMock(return_value=MockTransaction())
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

    fake_row = {
        "id": 1,
        "api_key": "key-123",
        "oidc_sub": None,
        "name": "Test",
        "encryption_secret": "sec",
    }
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

    fake_row = {
        "id": 2,
        "api_key": None,
        "oidc_sub": "oidc-abc",
        "name": "OIDC User",
        "encryption_secret": "sec",
    }
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
            1,
            {"text": "Hello"},
            [{"name": "Alice"}],
            {"summary": "Chat", "todos": [], "calendar": [], "notes": []},
            "file.enc",
        )

    assert recording_id == 42
    sql = mock_conn.fetchrow.call_args.args[0]
    assert "INSERT INTO recordings" in sql


@pytest.mark.asyncio
async def test_get_recordings_by_date(mock_conn):
    from lifelog.database import get_recordings_by_date

    mock_conn.fetch.return_value = [
        {"id": 1, "timestamp": datetime(2024, 1, 15, tzinfo=UTC), "summary": "Chat"}
    ]
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
        {
            "id": 5,
            "timestamp": datetime(2024, 1, 15, tzinfo=UTC),
            "speakers": [{"name": "Unknown"}],
            "audio_filename": "abc.enc",
        },
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
async def test_save_decisions(mock_conn):
    from lifelog.database import save_decisions

    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        await save_decisions(
            10,
            1,
            [
                {
                    "decision": "Use Postgres",
                    "made_by": "Alice",
                    "context": "DB choice",
                    "reason": "Team experience",
                },
                {"decision": "Launch Friday", "made_by": "Bob"},
            ],
        )

    # First call is DELETE, then two INSERTs
    assert mock_conn.execute.await_count == 3
    sql_first = mock_conn.execute.call_args_list[0].args[0]
    assert "DELETE FROM decisions" in sql_first


@pytest.mark.asyncio
async def test_get_decisions(mock_conn):
    from lifelog.database import get_decisions

    mock_conn.fetch.return_value = [
        {
            "id": 1,
            "decision": "Use Postgres",
            "made_by": "Alice",
            "context": "DB choice",
            "reason": "Team experience",
            "archived": False,
            "created_at": datetime(2024, 1, 15, tzinfo=UTC),
            "recording_id": 10,
            "recording_timestamp": datetime(2024, 1, 15, tzinfo=UTC),
        },
    ]
    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        result = await get_decisions(1, limit=10)

    assert len(result) == 1
    assert result[0]["decision"] == "Use Postgres"
    assert result[0]["reason"] == "Team experience"


@pytest.mark.asyncio
async def test_get_decisions_for_recording(mock_conn):
    from lifelog.database import get_decisions_for_recording

    mock_conn.fetch.return_value = [
        {
            "id": 1,
            "decision": "Go with A",
            "made_by": "Bob",
            "context": None,
            "reason": None,
            "archived": False,
            "created_at": datetime(2024, 1, 15, tzinfo=UTC),
        },
    ]
    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        result = await get_decisions_for_recording(10)

    assert len(result) == 1
    assert result[0]["decision"] == "Go with A"


@pytest.mark.asyncio
async def test_update_decision_archive(mock_conn):
    from lifelog.database import update_decision_archive

    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        await update_decision_archive(1, True)

    sql = mock_conn.execute.call_args.args[0]
    assert "UPDATE decisions" in sql


@pytest.mark.asyncio
async def test_delete_decision(mock_conn):
    from lifelog.database import delete_decision

    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        await delete_decision(1)

    sql = mock_conn.execute.call_args.args[0]
    assert "DELETE FROM decisions" in sql


@pytest.mark.asyncio
async def test_update_recording_speakers(mock_conn):
    from lifelog.database import update_recording_speakers

    pool = _make_mock_pool(mock_conn)

    with patch("lifelog.database.pool", pool):
        await update_recording_speakers(10, [{"name": "Alice"}])

    sql = mock_conn.execute.call_args.args[0]
    assert "UPDATE recordings" in sql


@pytest.mark.asyncio
async def test_create_transcription_job(mock_conn):
    from lifelog.database import create_transcription_job

    mock_conn.fetchrow.return_value = {"id": 7}
    with patch("lifelog.database.pool", _make_mock_pool(mock_conn)):
        result = await create_transcription_job(
            2, datetime(2025, 1, 1, 10), datetime(2025, 1, 1, 10, 10), 0
        )
    assert result == 7
    assert "INSERT INTO transcription_jobs" in mock_conn.fetchrow.call_args.args[0]


@pytest.mark.asyncio
async def test_claim_transcription_job_updates_processing(mock_conn):
    from lifelog.database import claim_transcription_job

    mock_conn.fetchrow.return_value = {
        "id": 8,
        "session_id": 2,
        "window_start": datetime(2025, 1, 1, 10),
        "window_end": datetime(2025, 1, 1, 10, 10),
        "chunk_index": 0,
        "status": "pending",
        "job_type": "full",
        "result": {},
    }
    with patch("lifelog.database.pool", _make_mock_pool(mock_conn)):
        result = await claim_transcription_job()
    assert result["status"] == "processing"
    assert result["id"] == 8
    assert "status = 'processing'" in mock_conn.execute.call_args.args[0]


@pytest.mark.asyncio
async def test_transcription_job_failure_is_retried(mock_conn):
    from lifelog.database import fail_transcription_job

    with patch("lifelog.database.pool", _make_mock_pool(mock_conn)):
        await fail_transcription_job(8, "cuda error")
    sql = mock_conn.execute.call_args.args[0]
    assert "failed_count = failed_count + 1" in sql
    assert "status = CASE" in sql


@pytest.mark.asyncio
async def test_completed_quick_jobs_are_unapplied(mock_conn):
    from lifelog.database import get_completed_quick_jobs

    mock_conn.fetch.return_value = [
        {"id": 3, "session_id": 2, "result": {"segments": []}}
    ]
    with patch("lifelog.database.pool", _make_mock_pool(mock_conn)):
        result = await get_completed_quick_jobs()
    assert result[0]["id"] == 3
    assert "job_type = 'quick'" in mock_conn.fetch.call_args.args[0]


@pytest.mark.asyncio
async def test_save_partition_recording_inserts_with_partition_index(mock_conn):
    from lifelog.database import save_partition_recording

    mock_conn.fetchrow.return_value = {"id": 42}
    with patch("lifelog.database.pool", _make_mock_pool(mock_conn)):
        recording_id = await save_partition_recording(
            user_id=1,
            session_id=10,
            partition_index=2,
            transcript={"segments": []},
            speakers=[{"name": "SPEAKER_00", "start": 0, "end": 5, "text": "hello"}],
            result={"summary": "test", "todos": [], "calendar": [], "notes": []},
            audio_filename="audio.enc",
            stored_segments=[
                {
                    "speaker": "SPEAKER_00",
                    "start": 0,
                    "end": 5,
                    "text": "hello",
                    "audio_filename": "seg.enc",
                }
            ],
            partition_start=datetime(2025, 1, 1, 10, 0, 0),
            partition_end=datetime(2025, 1, 1, 10, 5, 0),
            category="work",
        )
    assert recording_id == 42
    sql = mock_conn.fetchrow.call_args.args[0]
    assert "$2" in sql  # session_id
    assert "$3" in sql  # partition_index
