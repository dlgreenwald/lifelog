"""Tests for session grouping logic.

Tests session assignment, meaningful speech detection, and reprocessing.
"""
import json
from datetime import UTC, datetime, timedelta
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


# ── Session CRUD tests ─────────────────────────────────────────────


class TestSessionCRUD:
    @pytest.mark.asyncio
    async def test_get_active_session(self, mock_conn):
        from lifelog.database import get_active_session

        fake_session = {
            "id": 1,
            "user_id": 1,
            "started_at": datetime.now(UTC),
            "ended_at": None,
            "status": "active",
            "created_at": datetime.now(UTC),
        }
        mock_conn.fetchrow.return_value = fake_session
        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            result = await get_active_session(1)

        assert result is not None
        assert result["id"] == 1

    @pytest.mark.asyncio
    async def test_get_active_session_none(self, mock_conn):
        from lifelog.database import get_active_session

        mock_conn.fetchrow.return_value = None
        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            result = await get_active_session(1)

        assert result is None

    @pytest.mark.asyncio
    async def test_create_session(self, mock_conn):
        from lifelog.database import create_session

        mock_conn.fetchrow.return_value = {"id": 42}
        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            result = await create_session(1, datetime.now(UTC))

        assert result == 42

    @pytest.mark.asyncio
    async def test_end_session(self, mock_conn):
        from lifelog.database import end_session

        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            await end_session(1)

        mock_conn.execute.assert_awaited_once()
        sql = mock_conn.execute.call_args[0][0]
        assert "UPDATE sessions" in sql

    @pytest.mark.asyncio
    async def test_append_session_utterance(self, mock_conn):
        from lifelog.database import append_session_utterance

        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            await append_session_utterance(
                session_id=1,
                utterance_id=10,
                audio_filename="encrypted.opus",
                transcript={"segments": []},
                named_segments=[{"name": "Alice", "text": "hello"}],
            )

        mock_conn.execute.assert_awaited_once()
        sql = mock_conn.execute.call_args[0][0]
        assert "INSERT INTO session_utterances" in sql

    @pytest.mark.asyncio
    async def test_get_last_utterance_time(self, mock_conn):
        from lifelog.database import get_last_utterance_time

        now = datetime.now(UTC)
        mock_conn.fetchrow.return_value = {"created_at": now}
        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            result = await get_last_utterance_time(1)

        assert result == now

    @pytest.mark.asyncio
    async def test_get_last_utterance_time_none(self, mock_conn):
        from lifelog.database import get_last_utterance_time

        mock_conn.fetchrow.return_value = None
        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            result = await get_last_utterance_time(1)

        assert result is None

    @pytest.mark.asyncio
    async def test_save_session_recording_new(self, mock_conn):
        from lifelog.database import save_session_recording

        # No existing recording
        mock_conn.fetchrow.side_effect = [
            None,  # no existing
            {"id": 99},  # INSERT result
        ]
        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            result = await save_session_recording(
                user_id=1,
                session_id=5,
                transcript={"segments": []},
                speakers=[],
                result={
                    "summary": "Test summary",
                    "todos": [],
                    "calendar": [],
                    "notes": [],
                },
                audio_filename="test.opus",
            )

        assert result == 99

    @pytest.mark.asyncio
    async def test_save_session_recording_update(self, mock_conn):
        from lifelog.database import save_session_recording

        # Existing recording found
        mock_conn.fetchrow.return_value = {"id": 42}
        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            result = await save_session_recording(
                user_id=1,
                session_id=5,
                transcript={"segments": []},
                speakers=[],
                result={
                    "summary": "Updated summary",
                    "todos": [],
                    "calendar": [],
                    "notes": [],
                },
                audio_filename="test.opus",
            )

        assert result == 42
        sql = mock_conn.execute.call_args[0][0]
        assert "UPDATE recordings" in sql

    @pytest.mark.asyncio
    async def test_get_recording_audio_filenames(self, mock_conn):
        from lifelog.database import get_recording_audio_filenames

        mock_conn.fetch.return_value = [
            {"audio_filename": "f1.opus"},
            {"audio_filename": "f2.opus"},
        ]
        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            result = await get_recording_audio_filenames(1)

        assert result == ["f1.opus", "f2.opus"]

    @pytest.mark.asyncio
    async def test_join_sessions(self, mock_conn):
        from lifelog.database import join_sessions

        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            await join_sessions([1, 2, 3], keep_id=1)

        assert mock_conn.execute.await_count == 3  # UPDATE, UPDATE, DELETE

    @pytest.mark.asyncio
    async def test_join_sessions_noop(self, mock_conn):
        from lifelog.database import join_sessions

        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            await join_sessions([1], keep_id=1)

        # No calls — only session is the kept one
        mock_conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_sessions_for_reprocessing(self, mock_conn):
        from lifelog.database import get_sessions_for_reprocessing

        mock_conn.fetch.return_value = [
            {"id": 1, "user_id": 1, "started_at": datetime.now(UTC), "ended_at": datetime.now(UTC)}
        ]
        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            result = await get_sessions_for_reprocessing()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_sessions_by_date_range(self, mock_conn):
        from lifelog.database import get_sessions_by_date_range

        mock_conn.fetch.return_value = []
        pool = _make_mock_pool(mock_conn)

        now = datetime.now(UTC)
        with patch("lifelog.database.pool", pool):
            result = await get_sessions_by_date_range(1, now - timedelta(days=1), now)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_recording_with_session_audio_filenames(self, mock_conn):
        """get_recording returns audio_filenames from session_utterances."""
        from lifelog.database import get_recording

        fake_recording = {
            "id": 10,
            "user_id": 1,
            "session_id": 5,
            "audio_filename": "legacy.opus",
            "timestamp": datetime.now(UTC),
        }
        fake_audio = [
            {"audio_filename": "utt1.opus"},
            {"audio_filename": "utt2.opus"},
        ]
        mock_conn.fetchrow.return_value = fake_recording
        mock_conn.fetch.return_value = fake_audio
        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            result = await get_recording(1, 10)

        assert result is not None
        assert result["audio_filenames"] == ["utt1.opus", "utt2.opus"]

    @pytest.mark.asyncio
    async def test_get_recording_no_session_legacy(self, mock_conn):
        """get_recording without session_id uses legacy audio_filename."""
        from lifelog.database import get_recording

        fake_recording = {
            "id": 10,
            "user_id": 1,
            "session_id": None,
            "audio_filename": "legacy.opus",
            "timestamp": datetime.now(UTC),
        }
        mock_conn.fetchrow.return_value = fake_recording
        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            result = await get_recording(1, 10)

        assert result is not None
        assert result["audio_filenames"] == ["legacy.opus"]

    @pytest.mark.asyncio
    async def test_get_session_utterances_in_range(self, mock_conn):
        """get_session_utterances_in_range fetches utterances within a time range."""
        from lifelog.database import get_session_utterances_in_range

        fake_utterances = [
            {
                "utterance_id": 1,
                "audio_filename": "utt1.opus",
                "transcript": {},
                "named_segments": [],
                "created_at": datetime(2025, 1, 1, 10, 0, 0),
            },
            {
                "utterance_id": 2,
                "audio_filename": "utt2.opus",
                "transcript": {},
                "named_segments": [],
                "created_at": datetime(2025, 1, 1, 10, 5, 0),
            },
        ]
        mock_conn.fetch.return_value = fake_utterances
        pool = _make_mock_pool(mock_conn)

        start = datetime(2025, 1, 1, 9, 55, 0)
        end = datetime(2025, 1, 1, 10, 10, 0)

        with patch("lifelog.database.pool", pool):
            result = await get_session_utterances_in_range(1, start, end)

        assert len(result) == 2
        mock_conn.fetch.assert_awaited_once()
        sql = mock_conn.fetch.call_args[0][0]
        assert "created_at >= $2" in sql
        assert "created_at <= $3" in sql

    @pytest.mark.asyncio
    async def test_get_session_utterances_in_range_empty(self, mock_conn):
        """get_session_utterances_in_range returns empty when no utterances in range."""
        from lifelog.database import get_session_utterances_in_range

        mock_conn.fetch.return_value = []
        pool = _make_mock_pool(mock_conn)

        start = datetime(2025, 1, 1, 11, 0, 0)
        end = datetime(2025, 1, 1, 12, 0, 0)

        with patch("lifelog.database.pool", pool):
            result = await get_session_utterances_in_range(1, start, end)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_active_sessions_with_utterances(self, mock_conn):
        """get_active_sessions_with_utterances returns active sessions that have utterances."""
        from lifelog.database import get_active_sessions_with_utterances

        fake_sessions = [
            {"id": 1, "user_id": 1, "started_at": datetime(2025, 1, 1, 10, 0, 0), "ended_at": None},
            {"id": 3, "user_id": 2, "started_at": datetime(2025, 1, 1, 11, 0, 0), "ended_at": None},
        ]
        mock_conn.fetch.return_value = fake_sessions
        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            result = await get_active_sessions_with_utterances()

        assert len(result) == 2
        assert result[0]["id"] == 1
        mock_conn.fetch.assert_awaited_once()
        sql = mock_conn.fetch.call_args[0][0]
        assert "JOIN session_utterances" in sql
        assert "status = 'active'" in sql

    @pytest.mark.asyncio
    async def test_get_active_sessions_with_utterances_empty(self, mock_conn):
        """get_active_sessions_with_utterances returns empty when no active sessions."""
        from lifelog.database import get_active_sessions_with_utterances

        mock_conn.fetch.return_value = []
        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            result = await get_active_sessions_with_utterances()

        assert result == []


# ── Reprocessing tests ─────────────────────────────────────────────


class TestHourlyReprocessing:
    @pytest.mark.asyncio
    async def test_reprocess_session_creates_recording(self, mock_conn):
        """Hourly reprocess creates a recording for an ended session."""
        from lifelog.worker import _reprocess_session

        # Mock get_session_all_utterances — deferred transcription model
        utterances = [
            {
                "utterance_id": 1,
                "audio_filename": "utt1.opus",
                "transcript": {},
                "named_segments": [],
                "created_at": datetime(2025, 1, 1, 10, 0, 0),
            }
        ]

        fake_window_result = {
            "all_named_segments": [
                {"id": 0, "name": "Alice", "start": 0.0, "end": 5.0, "text": "hello world"},
            ],
            "full_transcript": {
                "segments": [{"start": 0.0, "end": 5.0, "text": "hello world", "speaker": "Alice"}],
            },
            "speaker_map": {"SPEAKER_00": "Alice"},
        }

        fake_llm_result = {
            "summary": "Test summary",
            "todos": [],
            "calendar": [],
            "notes": [],
        }

        with (
            patch("lifelog.worker.db") as mock_db,
            patch("lifelog.worker.transcribe_window", new_callable=AsyncMock, return_value=fake_window_result),
            patch("lifelog.worker.summarize", return_value=fake_llm_result),
        ):
            mock_db.get_session_all_utterances = AsyncMock(return_value=utterances)
            mock_db.get_recording_audio_filenames = AsyncMock(return_value=["utt1.opus"])
            mock_db.get_recording = AsyncMock(return_value=None)  # first processing
            mock_db.save_session_recording = AsyncMock(return_value=99)
            mock_db.save_todos = AsyncMock()
            mock_db.mark_session_processed = AsyncMock()

            session = {"id": 1, "user_id": 1, "started_at": datetime(2025, 1, 1, 10, 0, 0)}
            await _reprocess_session(session)

            mock_db.save_session_recording.assert_called_once()
            # No todos in llm_result, so save_todos should not be called
            mock_db.save_todos.assert_not_called()
            mock_db.mark_session_processed.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_reprocess_session_no_utterances(self, mock_conn):
        """Hourly reprocess skips session with no utterances."""
        from lifelog.worker import _reprocess_session

        with (
            patch("lifelog.worker.db") as mock_db,
        ):
            mock_db.get_session_all_utterances = AsyncMock(return_value=[])

            session = {"id": 1, "user_id": 1}
            await _reprocess_session(session)

            # Should not attempt to save
            mock_db.save_session_recording.assert_not_called()


class TestDailyReprocessing:
    @pytest.mark.asyncio
    async def test_daily_reprocess_generates_summary(self, mock_conn):
        """Daily reprocess collects transcripts and generates a daily summary."""
        from lifelog.worker import _daily_reprocess_user

        now = datetime.now(UTC)
        sessions = [
            {"id": 1, "user_id": 1, "started_at": now - timedelta(hours=3),
             "ended_at": now - timedelta(hours=2)},
        ]

        utterances = [
            {
                "utterance_id": 1,
                "transcript": {"segments": [{"speaker": "SPEAKER_00", "text": "hello"}]},
            },
        ]

        with (
            patch("lifelog.worker.db") as mock_db,
            patch("lifelog.pipeline.llm.summarize_day", return_value={"daily_summary": "Work: Met with team."}) as mock_summarize,
        ):
            mock_db.get_sessions_by_date_range = AsyncMock(return_value=sessions)
            mock_db.get_session_all_utterances = AsyncMock(return_value=utterances)
            mock_db.save_daily_summary = AsyncMock()

            await _daily_reprocess_user(1)

            mock_summarize.assert_called_once()
            mock_db.save_daily_summary.assert_called_once()

    @pytest.mark.asyncio
    async def test_daily_reprocess_no_sessions(self, mock_conn):
        """Daily reprocess handles user with no sessions."""
        from lifelog.worker import _daily_reprocess_user

        with (
            patch("lifelog.worker.db") as mock_db,
        ):
            mock_db.get_sessions_by_date_range = AsyncMock(return_value=[])

            # Should not raise
            await _daily_reprocess_user(1)

            mock_db.save_daily_summary.assert_not_called()

