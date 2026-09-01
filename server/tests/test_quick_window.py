"""Unit tests for the quick-job windowing + the apply-loop span partitioning."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lifelog import worker as lm_worker


def _utt(uid: int, when: datetime, transcript=None):
    return {"utterance_id": uid, "created_at": when, "transcript": transcript}


def _session(sid: int = 116, user_id: int = 26):
    return {"id": sid, "user_id": user_id}


def _make_pool(return_value=None):
    """Build a fake asyncpg pool whose acquire() returns a safe connection."""
    fake_conn = MagicMock()
    fake_conn.fetchrow = AsyncMock(return_value=return_value)
    fake_ctx = MagicMock()
    fake_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=fake_ctx)
    return mock_pool


# ---------------------------------------------------------------------------
# Windowing tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_window_floor_is_last_completed_plus_one_microsecond():
    """A fresh quick job only includes utterances newer than the last completed job
    and only after the 5-minute batching window has elapsed.
    """
    untranscribed = [
        _utt(1, datetime(2026, 9, 1, 13, 19, 8, tzinfo=UTC)),
        _utt(2, datetime(2026, 9, 1, 13, 19, 30, tzinfo=UTC)),
        _utt(3, datetime(2026, 9, 1, 15, 40, 0, tzinfo=UTC)),
    ]
    last_completed_at = datetime(2026, 9, 1, 15, 39, 30, 150_000, tzinfo=UTC)
    expected_floor = last_completed_at.replace(tzinfo=None)

    mock_create = AsyncMock(return_value=9999)
    with (
        patch.object(
            lm_worker.db,
            "get_active_sessions_with_utterances",
            new=AsyncMock(return_value=[_session(116)]),
        ),
        patch.object(
            lm_worker.db,
            "get_session_all_utterances",
            new=AsyncMock(return_value=untranscribed),
        ),
        patch.object(
            lm_worker.db,
            "get_pending_session_quick_job",
            new=AsyncMock(return_value=None),
        ),
        patch.object(
            lm_worker.db,
            "get_latest_completed_quick_job",
            new=AsyncMock(
                return_value={"id": 1854, "completed_at": last_completed_at}
            ),
        ),
        patch.object(
            lm_worker.db,
            "get_user_settings",
            new=AsyncMock(return_value={"language": "auto"}),
        ),
        patch.object(lm_worker.db, "create_session_quick_job", new=mock_create),
        patch("lifelog.worker.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = datetime(
            2026, 9, 1, 15, 45, 0, tzinfo=UTC
        )
        await lm_worker._create_session_quick_jobs()

    args = mock_create.await_args.args
    # signature: (session_id, utterance_ids, window_start, window_end, language)
    # Only utterances newer than last_completed_at are included
    assert args[1] == [3], f"utterance_ids={args[1]!r}"
    assert args[2] == expected_floor, (
        f"window_start={args[2]!r} expected={expected_floor!r}"
    )
    assert args[3] == datetime(2026, 9, 1, 15, 40, 0, tzinfo=UTC).replace(
        tzinfo=None
    )
@pytest.mark.asyncio
async def test_first_job_processes_all_untranscribed_when_no_prior_history():
    """With no prior completed quick jobs, the first job processes every
    untranscribed utterance immediately (no 5-minute wait — nothing to batch).
    """
    last_utt_ts = datetime(2026, 9, 1, 15, 45, 0, tzinfo=UTC)
    untranscribed = [
        _utt(1, datetime(2026, 9, 1, 13, 19, 8, tzinfo=UTC)),
        _utt(50, datetime(2026, 9, 1, 14, 50, 0, tzinfo=UTC)),
        _utt(99, last_utt_ts),
    ]
    expected_window_start = untranscribed[0]["created_at"].replace(tzinfo=None)

    mock_create = AsyncMock(return_value=9999)
    fake_pool = _make_pool(return_value={"language": "auto"})
    with (
        patch.object(
            lm_worker.db,
            "get_active_sessions_with_utterances",
            new=AsyncMock(return_value=[_session(116)]),
        ),
        patch.object(
            lm_worker.db,
            "get_session_all_utterances",
            new=AsyncMock(return_value=untranscribed),
        ),
        patch.object(
            lm_worker.db,
            "get_pending_session_quick_job",
            new=AsyncMock(return_value=None),
        ),
        patch.object(
            lm_worker.db,
            "get_latest_completed_quick_job",
            new=AsyncMock(return_value=None),
        ),
        patch.object(lm_worker.db, "create_session_quick_job", new=mock_create),
        patch.object(lm_worker.settings, "quick_window_minutes", 5),
    ):
        import lifelog.database as lm_db

        original_pool = lm_db.pool
        lm_db.pool = fake_pool
        try:
            await lm_worker._create_session_quick_jobs()
        finally:
            lm_db.pool = original_pool

    args = mock_create.await_args.args
    assert args[1] == [1, 50, 99], f"utterance_ids={args[1]!r}"
    assert args[2] == expected_window_start, (
        f"window_start={args[2]!r} expected={expected_window_start!r}"
    )


# ---------------------------------------------------------------------------
# Apply-loop tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_partitions_segments_by_utterance_spans():
    """Each WhisperX segment lands in the utterance whose span contains the
    segment's midpoint; spans never overlap so the mapping is unambiguous."""
    utterances = [
        _utt(1, datetime(2026, 9, 1, 15, 0, 0)),
        _utt(2, datetime(2026, 9, 1, 15, 1, 0)),
        _utt(3, datetime(2026, 9, 1, 15, 2, 0)),
    ]
    job = {
        "id": 1854,
        "session_id": 7,
        "window_start": datetime(2026, 9, 1, 15, 0, 0),
        "window_end": datetime(2026, 9, 1, 15, 3, 0),
        "result": {
            "utterance_ids": [1, 2, 3],
            "utterance_spans": [
                {"utterance_id": 1, "start": 0.0, "end": 5.0},
                {"utterance_id": 2, "start": 5.0, "end": 12.0},
                {"utterance_id": 3, "start": 12.0, "end": 18.0},
            ],
            "segments": [
                {"start": 1.0, "end": 2.5, "text": "Hello.", "speaker": "SPEAKER_00"},
                {"start": 6.5, "end": 8.0, "text": "World.", "speaker": "SPEAKER_00"},
                {"start": 13.0, "end": 14.5, "text": "Bye.", "speaker": "SPEAKER_01"},
            ],
        },
    }
    written: dict[int, list] = {}

    async def fake_write(_sid, utt_id, payload):
        written[utt_id] = payload["segments"]

    with (
        patch.object(
            lm_worker.db, "get_completed_quick_jobs", new=AsyncMock(return_value=[job])
        ),
        patch.object(
            lm_worker.db,
            "get_session_utterances_in_range",
            new=AsyncMock(return_value=utterances),
        ),
        patch.object(
            lm_worker.db, "update_session_utterance_transcript", new=fake_write
        ),
        patch.object(lm_worker.db, "mark_quick_job_applied", new=AsyncMock()),
    ):
        await lm_worker._apply_quick_transcripts()

    assert [s["text"] for s in written[1]] == ["Hello."]
    assert written[1][0]["start"] == pytest.approx(1.0)
    assert [s["text"] for s in written[2]] == ["World."]
    assert written[2][0]["start"] == pytest.approx(6.5 - 5.0)
    assert [s["text"] for s in written[3]] == ["Bye."]
    assert written[3][0]["speaker"] == "SPEAKER_01"


@pytest.mark.asyncio
async def test_apply_falls_back_to_legacy_time_partition_when_no_spans():
    """Jobs without utterance_spans preserve the legacy wall-clock partition
    so that historical results (which never had spans) can still be applied."""
    utterances = [
        _utt(10, datetime(2026, 9, 1, 15, 0, 0)),
        _utt(11, datetime(2026, 9, 1, 15, 0, 10)),
        _utt(12, datetime(2026, 9, 1, 15, 0, 35)),
    ]
    job = {
        "id": 1854,
        "session_id": 8,
        "window_start": datetime(2026, 9, 1, 15, 0, 0),
        "window_end": datetime(2026, 9, 1, 15, 1, 0),
        "result": {
            "utterance_ids": [10, 11, 12],
            # No utterance_spans — triggers legacy path
            "segments": [
                {"start": 3.0, "end": 4.5, "text": "First.", "speaker": "SPEAKER_00"},
                {
                    "start": 14.0,
                    "end": 16.0,
                    "text": "Second.",
                    "speaker": "SPEAKER_00",
                },
            ],
        },
    }
    written: dict[int, list] = {}

    async def fake_write(_sid, utt_id, payload):
        written[utt_id] = payload["segments"]

    with (
        patch.object(
            lm_worker.db, "get_completed_quick_jobs", new=AsyncMock(return_value=[job])
        ),
        patch.object(
            lm_worker.db,
            "get_session_utterances_in_range",
            new=AsyncMock(return_value=utterances),
        ),
        patch.object(
            lm_worker.db, "update_session_utterance_transcript", new=fake_write
        ),
        patch.object(lm_worker.db, "mark_quick_job_applied", new=AsyncMock()),
    ):
        await lm_worker._apply_quick_transcripts()

    assert [s["text"] for s in written[10]] == ["First."]
    assert [s["text"] for s in written[11]] == ["Second."]
    assert written.get(12, []) == []
