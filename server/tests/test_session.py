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


# ── is_meaningful_speech tests ─────────────────────────────────────


class TestIsMeaningfulSpeech:
    def test_empty_segments_not_meaningful(self):
        from lifelog.database import is_meaningful_speech
        assert is_meaningful_speech([]) is False

    def test_short_duration_still_meaningful(self):
        from lifelog.database import is_meaningful_speech
        segments = [
            {"start": 0, "end": 5, "text": "hello world"},
            {"start": 5, "end": 10, "text": "this is a test"},
        ]
        assert is_meaningful_speech(segments) is True

    def test_enough_duration_meaningful(self):
        from lifelog.database import is_meaningful_speech
        # 35 seconds of multi-word segments
        segments = [
            {"start": 0, "end": 10, "text": "hello world how are you doing today"},
            {"start": 10, "end": 20, "text": "I am doing well thank you very much"},
            {"start": 20, "end": 35, "text": "let me tell you about the meeting yesterday"},
        ]
        assert is_meaningful_speech(segments) is True

    def test_garbled_segments_still_meaningful(self):
        from lifelog.database import is_meaningful_speech
        # Even short/fragmented text counts as meaningful
        segments = [
            {"start": 0, "end": 3, "text": "yes"},
            {"start": 3, "end": 6, "text": "no"},
            {"start": 6, "end": 9, "text": "ok"},
            {"start": 9, "end": 12, "text": "right"},
            {"start": 12, "end": 15, "text": "well"},
            {"start": 15, "end": 25, "text": "this is a longer segment with more words"},
            {"start": 25, "end": 35, "text": "another longer segment with enough words"},
            {"start": 35, "end": 45, "text": "one more longer segment with enough words here"},
        ]
        assert is_meaningful_speech(segments) is True

    def test_empty_text_segments_not_meaningful(self):
        from lifelog.database import is_meaningful_speech
        # All segments have empty/whitespace text
        segments = [
            {"start": 0, "end": 5, "text": ""},
            {"start": 5, "end": 10, "text": "   "},
            {"start": 10, "end": 15, "text": ""},
        ]
        assert is_meaningful_speech(segments) is False

    def test_mixed_empty_and_text_meaningful(self):
        from lifelog.database import is_meaningful_speech
        # Some empty, some with text → meaningful
        segments = [
            {"start": 0, "end": 5, "text": ""},
            {"start": 5, "end": 10, "text": "hello world"},
            {"start": 10, "end": 15, "text": ""},
        ]
        assert is_meaningful_speech(segments) is True

    def test_few_short_segments_still_meaningful(self):
        from lifelog.database import is_meaningful_speech
        # 35 seconds, only 2/6 = 33% short segments
        segments = [
            {"start": 0, "end": 3, "text": "yes"},
            {"start": 3, "end": 6, "text": "no"},
            {"start": 6, "end": 15, "text": "this is a much longer segment of speech"},
            {"start": 15, "end": 25, "text": "another long segment with plenty of words here"},
            {"start": 25, "end": 35, "text": "one more segment with enough words to count"},
            {"start": 35, "end": 45, "text": "final segment with a lot of words in it"},
        ]
        assert is_meaningful_speech(segments) is True


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
                is_meaningful=True,
            )

        mock_conn.execute.assert_awaited_once()
        sql = mock_conn.execute.call_args[0][0]
        assert "INSERT INTO session_utterances" in sql

    @pytest.mark.asyncio
    async def test_get_session_meaningful_utterances(self, mock_conn):
        from lifelog.database import get_session_meaningful_utterances

        fake_rows = [
            {
                "utterance_id": 1,
                "audio_filename": "f1.opus",
                "transcript": json.dumps({"segments": []}),
                "named_segments": json.dumps([{"name": "Alice", "text": "hello"}]),
                "created_at": datetime.now(UTC),
            }
        ]
        mock_conn.fetch.return_value = fake_rows
        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            result = await get_session_meaningful_utterances(1)

        assert len(result) == 1
        sql = mock_conn.fetch.call_args[0][0]
        assert "is_meaningful = TRUE" in sql

    @pytest.mark.asyncio
    async def test_get_last_meaningful_utterance_time(self, mock_conn):
        from lifelog.database import get_last_meaningful_utterance_time

        now = datetime.now(UTC)
        mock_conn.fetchrow.return_value = {"created_at": now}
        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            result = await get_last_meaningful_utterance_time(1)

        assert result == now

    @pytest.mark.asyncio
    async def test_get_last_meaningful_utterance_time_none(self, mock_conn):
        from lifelog.database import get_last_meaningful_utterance_time

        mock_conn.fetchrow.return_value = None
        pool = _make_mock_pool(mock_conn)

        with patch("lifelog.database.pool", pool):
            result = await get_last_meaningful_utterance_time(1)

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


# ── Reprocessing tests ─────────────────────────────────────────────


class TestHourlyReprocessing:
    @pytest.mark.asyncio
    async def test_reprocess_session_creates_recording(self, mock_conn):
        """Hourly reprocess creates a recording for an ended session."""
        from lifelog.worker import _reprocess_session

        # Mock get_session_meaningful_utterances
        utterances = [
            {
                "utterance_id": 1,
                "audio_filename": "utt1.opus",
                "transcript": json.dumps({"segments": [{"text": "hello"}]}),
                "named_segments": json.dumps([
                    {"name": "Alice", "start": 0, "end": 10, "text": "hello world"}
                ]),
                "created_at": datetime.now(UTC),
            }
        ]

        # Mock get_recording_audio_filenames
        audio_files = ["utt1.opus"]

        mock_conn.fetchrow.side_effect = [
            {"id": 99},  # save_session_recording INSERT result
        ]
        mock_conn.fetch.side_effect = [utterances, audio_files]

        pool = _make_mock_pool(mock_conn)

        fake_result = {
            "summary": "Test summary",
            "todos": [],
            "calendar": [],
            "notes": [],
        }

        with (
            patch("lifelog.database.pool", pool),
            patch("lifelog.worker.summarize", return_value=fake_result) as mock_summarize,
            patch("lifelog.worker.db") as mock_db,
        ):
            mock_db.get_session_meaningful_utterances = AsyncMock(return_value=utterances)
            mock_db.get_recording_audio_filenames = AsyncMock(return_value=audio_files)
            mock_db.save_session_recording = AsyncMock(return_value=99)
            mock_db.mark_session_processed = AsyncMock()

            session = {"id": 1, "user_id": 1}
            await _reprocess_session(session)

            mock_summarize.assert_called_once()
            mock_db.save_session_recording.assert_called_once()
            mock_db.mark_session_processed.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_reprocess_session_no_meaningful_utterances(self, mock_conn):
        """Hourly reprocess skips session with no meaningful utterances."""
        from lifelog.worker import _reprocess_session

        with (
            patch("lifelog.database.pool", _make_mock_pool(mock_conn)),
            patch("lifelog.worker.db") as mock_db,
        ):
            mock_db.get_session_meaningful_utterances = AsyncMock(return_value=[])

            session = {"id": 1, "user_id": 1}
            await _reprocess_session(session)

            # Should not attempt to save
            mock_db.save_session_recording.assert_not_called()


class TestDailyReprocessing:
    @pytest.mark.asyncio
    async def test_daily_reprocess_joins_adjacent_sessions(self, mock_conn):
        """Daily reprocess joins sessions with small gaps."""
        from lifelog.worker import _daily_reprocess_user

        now = datetime.now(UTC)
        sessions = [
            {"id": 1, "user_id": 1, "started_at": now - timedelta(hours=3),
             "ended_at": now - timedelta(hours=2)},
            {"id": 2, "user_id": 1, "started_at": now - timedelta(hours=2, minutes=56),
             "ended_at": now - timedelta(hours=1)},
            {"id": 3, "user_id": 1, "started_at": now - timedelta(minutes=30),
             "ended_at": now},
        ]

        utterances = [
            {
                "utterance_id": 1,
                "audio_filename": "utt1.opus",
                "transcript": json.dumps({"segments": [{"text": "hello"}]}),
                "named_segments": json.dumps([
                    {"name": "Alice", "start": 0, "end": 10, "text": "hello"}
                ]),
                "created_at": now,
            }
        ]
        audio_files = ["utt1.opus"]

        with (
            patch("lifelog.worker.db") as mock_db,
            patch("lifelog.worker.summarize", return_value={
                "summary": "Summary",
                "todos": [],
                "calendar": [],
                "notes": [],
            }),
        ):
            mock_db.get_sessions_by_date_range = AsyncMock(return_value=sessions)
            mock_db.join_sessions = AsyncMock()
            mock_db.get_session_meaningful_utterances = AsyncMock(return_value=utterances)
            mock_db.get_recording_audio_filenames = AsyncMock(return_value=audio_files)
            mock_db.save_session_recording = AsyncMock(return_value=1)

            await _daily_reprocess_user(1)

            # Sessions 1 and 2 are within 5min gap → should be joined
            mock_db.join_sessions.assert_called()
            # save_session_recording should be called for each remaining session
            assert mock_db.save_session_recording.await_count >= 1

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

            mock_db.join_sessions.assert_not_called()

