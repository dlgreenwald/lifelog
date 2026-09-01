"""Tests for session grouping logic.

Tests session assignment, meaningful speech detection, and reprocessing.
"""

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
            {
                "id": 1,
                "user_id": 1,
                "started_at": datetime.now(UTC),
                "ended_at": datetime.now(UTC),
            }
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
            {
                "id": 1,
                "user_id": 1,
                "started_at": datetime(2025, 1, 1, 10, 0, 0),
                "ended_at": None,
            },
            {
                "id": 3,
                "user_id": 2,
                "started_at": datetime(2025, 1, 1, 11, 0, 0),
                "ended_at": None,
            },
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
    async def test_reprocess_session_queues_full_jobs(self):
        """Ended sessions enqueue missing full jobs without inline inference."""
        from lifelog.worker import _reprocess_session

        utterances = [
            {
                "utterance_id": 1,
                "audio_filename": "utt1.opus",
                "transcript": {},
                "named_segments": [],
                "created_at": datetime(2025, 1, 1, 10, 0, 0),
            }
        ]
        with patch("lifelog.worker.db") as mock_db:
            mock_db.get_session_all_utterances = AsyncMock(return_value=utterances)
            mock_db.get_transcription_jobs = AsyncMock(return_value=[])
            mock_db.get_user_settings = AsyncMock(return_value={"language": "auto"})
            mock_db.create_transcription_job = AsyncMock()
            await _reprocess_session(
                {"id": 1, "user_id": 1, "started_at": datetime(2025, 1, 1, 10, 0, 0)}
            )

        mock_db.create_transcription_job.assert_awaited_once_with(
            1,
            datetime(2025, 1, 1, 10, 0, 0),
            datetime(2025, 1, 1, 10, 0, 1),
            0,
            language="auto",
        )

    @pytest.mark.asyncio
    async def test_reprocess_session_no_utterances(self):
        """Hourly reprocess marks an empty session processed."""
        from lifelog.worker import _reprocess_session

        with patch("lifelog.worker.db") as mock_db:
            mock_db.get_session_all_utterances = AsyncMock(return_value=[])
            mock_db.mark_session_processed = AsyncMock()
            await _reprocess_session({"id": 1, "user_id": 1})
            mock_db.mark_session_processed.assert_awaited_once_with(1)

    @pytest.mark.asyncio
    async def test_process_utterance_queues_quick_job(self):
        from lifelog.worker import process_utterance

        timestamp = datetime(2025, 1, 1, 10)
        with (
            patch(
                "lifelog.worker.get_utterance_chunks",
                new_callable=AsyncMock,
                return_value=[{"audio_bytes": b"opus"}],
            ),
            patch(
                "lifelog.worker.get_user_secret",
                new_callable=AsyncMock,
                return_value={"encryption_secret": "s", "key_salt": b"salt"},
            ),
            patch(
                "lifelog.worker.audio_crypto.encrypt_audio", return_value="audio.enc"
            ),
            patch("lifelog.worker.delete_utterance_chunks", new_callable=AsyncMock),
            patch("lifelog.worker.complete_utterance", new_callable=AsyncMock),
            patch("lifelog.worker.db") as mock_db,
        ):
            mock_db.get_utterance_queue_entry = AsyncMock(
                return_value={"created_at": timestamp}
            )
            mock_db.get_active_session = AsyncMock(return_value=None)
            mock_db.create_session = AsyncMock(return_value=7)
            mock_db.append_session_utterance = AsyncMock()
            await process_utterance(1, 9)
        mock_db.append_session_utterance.assert_awaited_once()
        mock_db.create_session.assert_awaited_once_with(1, timestamp)

    @pytest.mark.asyncio
    async def test_apply_quick_transcript_updates_utterance(self):
        from lifelog.worker import _apply_quick_transcripts

        with patch("lifelog.worker.db") as mock_db:
            mock_db.get_completed_quick_jobs = AsyncMock(
                return_value=[
                    {
                        "id": 4,
                        "session_id": 1,
                        "chunk_index": 9,
                        "result": {"segments": [{"text": "hello"}]},
                    }
                ]
            )
            mock_db.update_session_utterance_transcript = AsyncMock()
            mock_db.mark_quick_job_applied = AsyncMock()
            await _apply_quick_transcripts()
        mock_db.update_session_utterance_transcript.assert_awaited_once_with(
            1, 9, {"segments": [{"text": "hello"}]}
        )
        mock_db.mark_quick_job_applied.assert_awaited_once_with(4)

    @pytest.mark.asyncio
    async def test_finalize_completed_session_persists_encrypted_segments(self):
        from lifelog.worker import _finalize_completed_sessions

        session = {"id": 1, "user_id": 2, "started_at": datetime(2025, 1, 1, 10)}
        jobs = [
            {
                "id": 4,
                "chunk_index": 0,
                "window_start": datetime(2025, 1, 1, 10),
                "window_end": datetime(2025, 1, 1, 10, 10),
                "status": "done",
                "job_type": "full",
                "result": {
                    "segments": [
                        {"start": 0, "end": 1, "text": "hello", "speaker": "SPEAKER_00"}
                    ],
                    "speaker_map": {},
                    "speaker_segments": [
                        {
                            "speaker": "SPEAKER_00",
                            "start": 0,
                            "end": 1,
                            "text": "hello",
                            "audio": "YQ==",
                        }
                    ],
                },
            }
        ]
        with (
            patch("lifelog.worker.db") as mock_db,
            patch(
                "lifelog.worker.get_user_secret",
                new_callable=AsyncMock,
                return_value={"encryption_secret": "s", "key_salt": b"salt"},
            ),
            patch(
                "lifelog.worker.audio_crypto.encrypt_audio", return_value="segment.enc"
            ),
            patch(
                "lifelog.worker.summarize",
                return_value={"summary": "s", "todos": [], "calendar": [], "notes": []},
            ),
            patch("lifelog.worker._auto_enroll_speakers", new_callable=AsyncMock),
            patch("lifelog.worker._daily_reprocess_user", new_callable=AsyncMock),
        ):
            mock_db.get_sessions_for_reprocessing = AsyncMock(return_value=[session])
            mock_db.get_transcription_jobs = AsyncMock(return_value=jobs)
            mock_db.get_recording_audio_filenames = AsyncMock(return_value=["full.enc"])
            mock_db.get_recording = AsyncMock(return_value=None)
            mock_db.save_session_recording = AsyncMock(return_value=99)
            mock_db.mark_session_processed = AsyncMock()
            mock_db.get_unknown_speakers = AsyncMock(return_value=[])
            mock_db.get_user_settings = AsyncMock(
                return_value={"language": "auto", "llm_context": ""}
            )
            await _finalize_completed_sessions()
        saved = mock_db.save_session_recording.call_args.kwargs["speaker_segments"]
        assert saved == [
            {
                "speaker": "SPEAKER_00",
                "start": 0.0,
                "end": 1.0,
                "text": "hello",
                "audio_filename": "segment.enc",
            }
        ]
        assert "audio" not in saved[0]
        mock_db.mark_session_processed.assert_awaited_once_with(1)


class TestDailyReprocessing:
    @pytest.mark.asyncio
    async def test_daily_reprocess_generates_summary(self, mock_conn):
        """Daily reprocess collects transcripts and generates a daily summary."""
        from lifelog.worker import _daily_reprocess_user

        now = datetime.now(UTC)
        sessions = [
            {
                "id": 1,
                "user_id": 1,
                "started_at": now - timedelta(hours=3),
                "ended_at": now - timedelta(hours=2),
            },
        ]

        utterances = [
            {
                "utterance_id": 1,
                "transcript": {
                    "segments": [{"speaker": "SPEAKER_00", "text": "hello"}]
                },
            },
        ]

        with (
            patch("lifelog.worker.db") as mock_db,
            patch(
                "lifelog.pipeline.llm.summarize_day",
                return_value={"daily_summary": "Work: Met with team."},
            ) as mock_summarize,
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


class TestPartitionSegments:
    """Tests for session gap-split logic."""

    def test_partition_segments_no_gap(self):
        """No split when segments are continuous."""
        from lifelog.worker import _partition_segments

        segments = [
            {"speaker": "SPEAKER_00", "start": 0, "end": 10, "text": "hello"},
            {"speaker": "SPEAKER_01", "start": 10, "end": 20, "text": "hi there"},
        ]
        result = _partition_segments(segments)
        assert len(result) == 1
        assert len(result[0]) == 2

    def test_partition_segments_within_5_min_gap(self):
        """No split for gap < 5 minutes."""
        from lifelog.worker import _partition_segments

        segments = [
            {"speaker": "SPEAKER_00", "start": 0, "end": 10, "text": "hello"},
            {
                "speaker": "SPEAKER_01",
                "start": 270,
                "end": 280,
                "text": "hi",
            },  # 4.5 min gap
        ]
        result = _partition_segments(segments)
        assert len(result) == 1

    def test_partition_segments_split_on_5_min_gap(self):
        """Split when gap > 5 minutes."""
        from lifelog.worker import _partition_segments

        segments = [
            {"speaker": "SPEAKER_00", "start": 0, "end": 10, "text": "hello"},
            {
                "speaker": "SPEAKER_01",
                "start": 310,
                "end": 320,
                "text": "hi",
            },  # 5 min 10 sec gap
        ]
        result = _partition_segments(segments)
        assert len(result) == 2
        assert result[0][0]["start"] == 0
        assert result[1][0]["start"] == 310

    def test_partition_segments_multiple_gaps(self):
        """Multiple splits for multiple large gaps."""
        from lifelog.worker import _partition_segments

        segments = [
            {"speaker": "SPEAKER_00", "start": 0, "end": 10, "text": "a"},
            {"speaker": "SPEAKER_01", "start": 310, "end": 320, "text": "b"},  # gap 1
            {"speaker": "SPEAKER_00", "start": 620, "end": 630, "text": "c"},  # gap 2
        ]
        result = _partition_segments(segments)
        assert len(result) == 3
        assert [p[0]["text"] for p in result] == ["a", "b", "c"]

    def test_partition_segments_empty(self):
        """Empty list returns empty partitions."""
        from lifelog.worker import _partition_segments

        assert _partition_segments([]) == []
