"""Unit tests for lifelog.ingest — ingestion from PostgreSQL into Meilisearch."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── _parse_timestamp ──────────────────────────────────────────────────────────


class TestParseTimestamp:
    """Test the _parse_timestamp pure function."""

    def test_none_returns_empty_string(self):
        from lifelog.ingest import _parse_timestamp

        assert _parse_timestamp(None) == ""

    def test_datetime_returns_iso_date(self):
        from lifelog.ingest import _parse_timestamp

        dt = datetime(2026, 9, 20, 14, 30, 0)
        assert _parse_timestamp(dt) == "2026-09-20"

    def test_datetime_returns_only_date_portion(self):
        from lifelog.ingest import _parse_timestamp

        dt = datetime(2026, 1, 1, 23, 59, 59)
        assert _parse_timestamp(dt) == "2026-01-01"

    def test_iso_string_returns_date_portion(self):
        from lifelog.ingest import _parse_timestamp

        result = _parse_timestamp("2026-09-20T14:30:00")
        assert result == "2026-09-20"

    def test_iso_string_strips_timezone(self):
        from lifelog.ingest import _parse_timestamp

        result = _parse_timestamp("2026-09-20T14:30:00+00:00")
        assert result == "2026-09-20"

    def test_empty_string_returns_empty_string(self):
        from lifelog.ingest import _parse_timestamp

        assert _parse_timestamp("") == ""

    def test_random_string_returns_first_10_chars(self):
        from lifelog.ingest import _parse_timestamp

        # Non-ISO strings pass through as-is, sliced to 10 chars
        assert _parse_timestamp("not-a-date") == "not-a-date"


# ── _speaker_names_from_recording ─────────────────────────────────────────────


class TestSpeakerNamesFromRecording:
    """Test the _speaker_names_from_recording pure function."""

    def test_empty_recording_returns_empty_list(self):
        from lifelog.ingest import _speaker_names_from_recording

        assert _speaker_names_from_recording({}) == []

    def test_no_speakers_key_returns_empty_list(self):
        from lifelog.ingest import _speaker_names_from_recording

        assert _speaker_names_from_recording({"title": "Test"}) == []

    def test_null_speakers_returns_empty_list(self):
        from lifelog.ingest import _speaker_names_from_recording

        assert _speaker_names_from_recording({"speakers": None}) == []

    def test_empty_speakers_list_returns_empty_list(self):
        from lifelog.ingest import _speaker_names_from_recording

        assert _speaker_names_from_recording({"speakers": []}) == []

    def test_single_speaker(self):
        from lifelog.ingest import _speaker_names_from_recording

        recording = {"speakers": [{"name": "Alice", "id": 1}]}
        assert _speaker_names_from_recording(recording) == ["Alice"]

    def test_multiple_distinct_speakers(self):
        from lifelog.ingest import _speaker_names_from_recording

        recording = {
            "speakers": [
                {"name": "Alice", "id": 1},
                {"name": "Bob", "id": 2},
            ]
        }
        assert _speaker_names_from_recording(recording) == ["Alice", "Bob"]

    def test_duplicate_speakers_deduplicated(self):
        from lifelog.ingest import _speaker_names_from_recording

        recording = {
            "speakers": [
                {"name": "Alice"},
                {"name": "Bob"},
                {"name": "Alice"},
            ]
        }
        assert _speaker_names_from_recording(recording) == ["Alice", "Bob"]

    def test_speaker_with_missing_name_field(self):
        from lifelog.ingest import _speaker_names_from_recording

        recording = {"speakers": [{"id": 1}]}
        assert _speaker_names_from_recording(recording) == []

    def test_speaker_with_empty_name(self):
        from lifelog.ingest import _speaker_names_from_recording

        recording = {"speakers": [{"name": ""}]}
        assert _speaker_names_from_recording(recording) == []

    def test_non_dict_speaker_fallback_to_str(self):
        from lifelog.ingest import _speaker_names_from_recording

        recording = {"speakers": ["Alice", "Bob"]}
        assert _speaker_names_from_recording(recording) == ["Alice", "Bob"]

    def test_non_dict_speaker_with_empty_string(self):
        from lifelog.ingest import _speaker_names_from_recording

        recording = {"speakers": ["Alice", ""]}
        assert _speaker_names_from_recording(recording) == ["Alice"]

    def test_speakers_stored_as_json_string(self):
        from lifelog.ingest import _speaker_names_from_recording

        recording = {"speakers": json.dumps([{"name": "Alice"}, {"name": "Bob"}])}
        assert _speaker_names_from_recording(recording) == ["Alice", "Bob"]

    def test_speakers_stored_as_invalid_json_string(self):
        from lifelog.ingest import _speaker_names_from_recording

        recording = {"speakers": "not valid json"}
        assert _speaker_names_from_recording(recording) == []


# ── _build_full_transcript ────────────────────────────────────────────────────


class TestBuildFullTranscript:
    """Test the _build_full_transcript pure function."""

    def test_empty_recording_returns_empty_string(self):
        from lifelog.ingest import _build_full_transcript

        assert _build_full_transcript({}) == ""

    def test_no_transcript_key_returns_empty_string(self):
        from lifelog.ingest import _build_full_transcript

        assert _build_full_transcript({"title": "Test"}) == ""

    def test_null_transcript_returns_empty_string(self):
        from lifelog.ingest import _build_full_transcript

        assert _build_full_transcript({"transcript": None}) == ""

    def test_empty_segments_list_returns_empty_string(self):
        from lifelog.ingest import _build_full_transcript

        assert _build_full_transcript({"transcript": {"segments": []}}) == ""

    def test_single_segment_with_speaker(self):
        from lifelog.ingest import _build_full_transcript

        recording = {
            "transcript": {"segments": [{"speaker": "Alice", "text": "Hello world"}]}
        }
        assert _build_full_transcript(recording) == "Alice: Hello world"

    def test_single_segment_without_speaker(self):
        from lifelog.ingest import _build_full_transcript

        recording = {"transcript": {"segments": [{"text": "Hello world"}]}}
        assert _build_full_transcript(recording) == "Hello world"

    def test_multiple_segments(self):
        from lifelog.ingest import _build_full_transcript

        recording = {
            "transcript": {
                "segments": [
                    {"speaker": "Alice", "text": "Hi."},
                    {"speaker": "Bob", "text": "Hey."},
                ]
            }
        }
        result = _build_full_transcript(recording)
        assert "Alice: Hi." in result
        assert "Bob: Hey." in result

    def test_segments_with_empty_text_skipped(self):
        from lifelog.ingest import _build_full_transcript

        recording = {
            "transcript": {
                "segments": [
                    {"speaker": "Alice", "text": "Hello"},
                    {"speaker": "Bob", "text": ""},
                    {"speaker": "Carol", "text": "  "},
                ]
            }
        }
        result = _build_full_transcript(recording)
        # Empty/whitespace-only text is skipped, so Carol (spaces text) is dropped
        assert result == "Alice: Hello"

    def test_segments_with_name_instead_of_speaker(self):
        from lifelog.ingest import _build_full_transcript

        recording = {
            "transcript": {
                "segments": [
                    {"name": "Alice", "text": "Using name field"},
                ]
            }
        }
        assert _build_full_transcript(recording) == "Alice: Using name field"

    def test_transcript_as_plain_list(self):
        from lifelog.ingest import _build_full_transcript

        recording = {
            "transcript": [
                {"speaker": "Alice", "text": "Plain list format"},
            ]
        }
        assert _build_full_transcript(recording) == "Alice: Plain list format"

    def test_transcript_stored_as_json_string(self):
        from lifelog.ingest import _build_full_transcript

        recording = {
            "transcript": json.dumps(
                {"segments": [{"speaker": "Alice", "text": "From JSON string"}]}
            )
        }
        assert _build_full_transcript(recording) == "Alice: From JSON string"

    def test_transcript_stored_as_invalid_json_string(self):
        from lifelog.ingest import _build_full_transcript

        recording = {"transcript": "not valid json"}
        assert _build_full_transcript(recording) == ""


# ── ingest_recording ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_recording_not_found_returns_zero():
    """When the DB query returns no row, ingest_recording logs and returns 0."""
    from lifelog import ingest

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None

    class MockPoolAcquire:
        """pool.acquire() returns an async context manager directly."""

        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, *args):
            return False

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=MockPoolAcquire())

    with patch.object(ingest.db, "pool", mock_pool):
        count = await ingest.ingest_recording(user_id=1, recording_id=999)
    assert count == 0
    mock_conn.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_ingest_recording_full_flow():
    """A complete recording with transcript, summary, decisions, and todos is indexed."""
    from lifelog import ingest

    mock_row = {
        "id": 42,
        "user_id": 1,
        "title": "Test Session",
        "timestamp": "2026-09-20T10:00:00",
        "summary": "A brief summary",
        "long_summary": "",
        "decisions": json.dumps([{"decision": "Decide on Friday"}]),
        "todos": json.dumps([{"task": "Send email", "completed": False}]),
        "transcript": {
            "segments": [
                {"speaker": "Alice", "text": "Hello world"},
            ]
        },
        "speakers": [{"name": "Alice"}],
    }

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = mock_row

    class MockPoolAcquire:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, *args):
            return False

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=MockPoolAcquire())

    upsert_calls = {}

    def capture_upsert(**kwargs):
        key = kwargs.get("text", kwargs.get("full_text", str(kwargs)))
        upsert_calls[key] = kwargs

    with (
        patch.object(ingest.db, "pool", mock_pool),
        patch.object(ingest.search, "upsert_recording", side_effect=capture_upsert),
        patch.object(ingest.search, "upsert_summary", side_effect=capture_upsert),
        patch.object(ingest.search, "upsert_decision", side_effect=capture_upsert),
        patch.object(ingest.search, "upsert_todo", side_effect=capture_upsert),
    ):
        count = await ingest.ingest_recording(user_id=1, recording_id=42)

    # transcript + summary + decision + todo = 4
    assert count == 4

    # transcript doc
    assert "Alice: Hello world" in upsert_calls
    assert upsert_calls["Alice: Hello world"]["conversation_id"] == 42
    assert upsert_calls["Alice: Hello world"]["participants"] == ["Alice"]

    # summary doc
    summary_text = upsert_calls["A brief summary"]
    assert summary_text["text"] == "A brief summary"
    assert summary_text["conversation_id"] == 42

    # decision doc
    assert "Decide on Friday" in upsert_calls
    assert upsert_calls["Decide on Friday"]["text"] == "Decide on Friday"

    # todo doc
    assert "Send email" in upsert_calls
    assert upsert_calls["Send email"]["status"] == "open"


@pytest.mark.asyncio
async def test_ingest_recording_uses_long_summary_when_available():
    """When long_summary is present, it takes precedence over summary."""
    from lifelog import ingest

    mock_row = {
        "id": 43,
        "user_id": 1,
        "title": "Long Summary Test",
        "timestamp": "2026-09-20T10:00:00",
        "summary": "Short",
        "long_summary": "This is the detailed long summary",
        "decisions": "[]",
        "todos": "[]",
        "transcript": {"segments": [{"speaker": "Alice", "text": "Hello"}]},
        "speakers": [{"name": "Alice"}],
    }

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = mock_row

    class MockPoolAcquire:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, *args):
            return False

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=MockPoolAcquire())

    captured_summary_text = {}

    with (
        patch.object(ingest.db, "pool", mock_pool),
        patch.object(ingest.search, "upsert_recording"),
        patch.object(
            ingest.search,
            "upsert_summary",
            side_effect=lambda **kw: captured_summary_text.update(kw),
        ),
        patch.object(ingest.search, "upsert_decision"),
        patch.object(ingest.search, "upsert_todo"),
    ):
        await ingest.ingest_recording(user_id=1, recording_id=43)

    assert captured_summary_text["text"] == "This is the detailed long summary"


@pytest.mark.asyncio
async def test_ingest_recording_skips_empty_transcript():
    """When transcript is empty, no recording document is upserted."""
    from lifelog import ingest

    mock_row = {
        "id": 44,
        "user_id": 1,
        "title": "No Transcript",
        "timestamp": "2026-09-20T10:00:00",
        "summary": "Has summary but no transcript",
        "long_summary": "",
        "decisions": "[]",
        "todos": "[]",
        "transcript": {"segments": []},
        "speakers": [],
    }

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = mock_row

    class MockPoolAcquire:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, *args):
            return False

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=MockPoolAcquire())

    with (
        patch.object(ingest.db, "pool", mock_pool),
        patch.object(ingest.search, "upsert_recording") as mock_ur,
        patch.object(ingest.search, "upsert_summary") as mock_us,
        patch.object(ingest.search, "upsert_decision"),
        patch.object(ingest.search, "upsert_todo"),
    ):
        count = await ingest.ingest_recording(user_id=1, recording_id=44)

    # Only summary, no transcript
    assert count == 1
    mock_ur.assert_not_called()
    mock_us.assert_called_once()


# ── ingest_all ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_all_empty_user():
    """When a user has no recordings, ingest_all returns 0."""
    from lifelog import ingest

    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []

    class MockPoolAcquire:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, *args):
            return False

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=MockPoolAcquire())

    with patch.object(ingest.db, "pool", mock_pool):
        total = await ingest.ingest_all(user_id=1)

    assert total == 0


@pytest.mark.asyncio
async def test_ingest_all_calls_ingest_recording_per_recording():
    """ingest_all fetches all recording IDs and calls ingest_recording for each."""
    from lifelog import ingest

    # Two recording IDs returned from DB
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [{"id": 10}, {"id": 20}]

    class MockPoolAcquire:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, *args):
            return False

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=MockPoolAcquire())

    with (
        patch.object(ingest.db, "pool", mock_pool),
        patch.object(
            ingest, "ingest_recording", AsyncMock(side_effect=[3, 2])
        ) as mock_ir,
    ):
        total = await ingest.ingest_all(user_id=1)

    assert total == 5  # 3 + 2
    assert mock_ir.call_count == 2


@pytest.mark.asyncio
async def test_ingest_all_continues_on_recording_error():
    """A JSON decode error on one recording does not stop processing of the rest."""
    from lifelog import ingest

    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]

    class MockPoolAcquire:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, *args):
            return False

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=MockPoolAcquire())

    error_call_count = 0

    async def ingest_with_error(user_id, recording_id):
        nonlocal error_call_count
        if recording_id == 2:
            raise json.JSONDecodeError("test", "test", 0)
        return 1

    with (
        patch.object(ingest.db, "pool", mock_pool),
        patch.object(ingest, "ingest_recording", side_effect=ingest_with_error),
    ):
        total = await ingest.ingest_all(user_id=1)

    # Two recordings succeeded (1 + 1), recording 2 errored
    assert total == 2
