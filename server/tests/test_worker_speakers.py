"""Tests for the worker's centroid-based speaker resolution."""

from unittest.mock import AsyncMock, patch

import pytest

USER = {"id": 1, "encryption_secret": "sec", "key_salt": b"salt"}


@pytest.mark.asyncio
async def test_reidentify_matched_label_appends_voiceprint():
    """A matched centroid appends to the existing speaker and rewrites segments."""
    from lifelog.worker import _reidentify_recording

    recording = {
        "id": 10,
        "speaker_segments": [
            {
                "speaker": "SPEAKER_00",
                "start": 0,
                "end": 45.0,
                "text": "hello this is a longer segment",
                "audio_filename": "seg.enc",
            }
        ],
    }
    result = {
        "centroid": [0.1, 0.2],
        "match": {"speaker_id": 7, "name": "Alice Ashford", "similarity": 0.9},
    }

    with (
        patch("lifelog.worker.db") as mock_db,
        patch("lifelog.worker.audio_crypto.decrypt_audio", return_value=b"audio"),
        patch(
            "lifelog.pipeline.speaker_client.resolve_speaker", new_callable=AsyncMock
        ) as mock_resolve,
    ):
        # module-level import inside the function
        import lifelog.worker  # noqa: F401

        mock_db.get_all_voiceprints = AsyncMock(return_value=[])
        mock_db.add_voiceprint = AsyncMock(return_value=1)
        mock_db.update_recording_speaker_data = AsyncMock()
        mock_resolve.return_value = result
        await _reidentify_recording(USER, recording)

    mock_resolve.assert_awaited_once()
    mock_db.add_voiceprint.assert_awaited_once()
    speaker_id = mock_db.add_voiceprint.call_args.args[0]
    assert speaker_id == 7
    speakers, updated = mock_db.update_recording_speaker_data.call_args.args[1:3]
    assert speakers[0]["name"] == "Alice Ashford"
    assert speakers[0]["speaker_id"] == 7
    assert updated[0]["raw_speaker"] == "SPEAKER_00"
    assert updated[0]["speaker"] == "Alice Ashford"


@pytest.mark.asyncio
async def test_reidentify_unmatched_label_creates_speaker():
    """An unmatched centroid creates a new speaker with an alliterative name."""
    from lifelog.worker import _reidentify_recording

    recording = {
        "id": 10,
        "speaker_segments": [
            {
                "speaker": "SPEAKER_01",
                "start": 0,
                "end": 45.0,
                "text": "hi this is a longer segment",
                "audio_filename": "seg.enc",
            }
        ],
    }
    result = {"centroid": [0.3, 0.4], "match": None}

    with (
        patch("lifelog.worker.db") as mock_db,
        patch("lifelog.worker.audio_crypto.decrypt_audio", return_value=b"audio"),
        patch(
            "lifelog.pipeline.speaker_client.resolve_speaker",
            new_callable=AsyncMock,
        ) as mock_resolve,
    ):
        mock_db.get_all_voiceprints = AsyncMock(return_value=[])
        mock_db.create_speaker = AsyncMock(return_value={"id": 42, "name": "Sam Stone"})
        mock_db.add_voiceprint = AsyncMock(return_value=1)
        mock_db.update_recording_speaker_data = AsyncMock()
        mock_resolve.return_value = result
        await _reidentify_recording(USER, recording)

    mock_db.create_speaker.assert_awaited_once()
    name = mock_db.create_speaker.call_args.args[1]
    first, last = name.split(" ")
    assert first[0] == last[0]
    assert mock_db.add_voiceprint.call_args.args[0] == 42
    speakers, updated = mock_db.update_recording_speaker_data.call_args.args[1:3]
    assert speakers[0]["name"] == name
    assert speakers[0]["speaker_id"] == 42
    assert updated[0]["raw_speaker"] == "SPEAKER_01"


@pytest.mark.asyncio
async def test_reidentify_label_without_audio_left_raw():
    """A raw label with no segment audio stays unresolved."""
    from lifelog.worker import _reidentify_recording

    recording = {
        "id": 10,
        "speaker_segments": [
            {
                "speaker": "SPEAKER_00",
                "start": 0,
                "end": 45.0,
                "text": "hello this is a longer segment",
            }
        ],
    }

    with (
        patch("lifelog.worker.db") as mock_db,
        patch(
            "lifelog.pipeline.speaker_client.resolve_speaker", new_callable=AsyncMock
        ) as mock_resolve,
    ):
        mock_db.get_all_voiceprints = AsyncMock(return_value=[])
        mock_db.update_recording_speaker_data = AsyncMock()
        await _reidentify_recording(USER, recording)

    mock_resolve.assert_not_awaited()
    speakers, updated = mock_db.update_recording_speaker_data.call_args.args[1:3]
    assert speakers[0]["name"] == "SPEAKER_00"
    assert updated[0]["speaker"] == "SPEAKER_00"
    assert updated[0]["raw_speaker"] == "SPEAKER_00"


@pytest.mark.asyncio
async def test_reidentify_overlap_segment_skipped_for_enrollment():
    """Segments flagged with ``overlap_with`` are resolved (for matching) but not used for enrollment."""
    from lifelog.worker import _reidentify_recording

    recording = {
        "id": 10,
        "speaker_segments": [
            {
                "speaker": "SPEAKER_00",
                "start": 0,
                "end": 45.0,
                "text": "this is a long segment",
                "audio_filename": "seg.enc",
                "overlap_with": ["SPEAKER_01"],
            }
        ],
    }
    result = {
        "centroid": [0.1, 0.2],
        "match": {"speaker_id": 7, "name": "Alice Ashford", "similarity": 0.9},
    }

    with (
        patch("lifelog.worker.db") as mock_db,
        patch("lifelog.worker.audio_crypto.decrypt_audio", return_value=b"audio"),
        patch(
            "lifelog.pipeline.speaker_client.resolve_speaker", new_callable=AsyncMock
        ) as mock_resolve,
    ):
        mock_db.get_all_voiceprints = AsyncMock(return_value=[])
        mock_db.add_voiceprint = AsyncMock(return_value=1)
        mock_db.update_recording_speaker_data = AsyncMock()
        mock_resolve.return_value = result
        await _reidentify_recording(USER, recording)

    # Overlapping segment IS resolved (for matching) even though it's excluded from enrollment
    mock_resolve.assert_called_once()
    # Matched → voiceprint accumulated, no new speaker enrolled
    mock_db.add_voiceprint.assert_called_once()
    # Segment gets the matched speaker's name
    _speakers, updated = mock_db.update_recording_speaker_data.call_args.args[1:3]
    assert updated[0]["raw_speaker"] == "SPEAKER_00"
    assert updated[0]["speaker"] == "Alice Ashford"
    assert updated[0]["speaker_id"] == 7


def test_shifted_segments_shifts_word_timestamps():
    """Word-level timestamps must be shifted to absolute timebase, not left chunk-relative."""
    from lifelog.worker import _shifted_segments

    segments = [
        {
            "start": 0.0,
            "end": 3.5,
            "speaker": "SPEAKER_00",
            "words": [
                {"word": "hello", "start": 0.0, "end": 0.8},
                {"word": "world", "start": 0.9, "end": 1.5},
            ],
        },
        {
            "start": 10.0,
            "end": 13.0,
            "speaker": "SPEAKER_01",
            "words": [
                {"word": "goodbye", "start": 10.0, "end": 11.0},
            ],
        },
    ]

    # offset = 4351.5  (second chunk starts at 4351.5s into the recording)
    result = _shifted_segments(segments, 4351.5)

    # Segment-level timestamps
    assert result[0]["start"] == pytest.approx(4351.5)
    assert result[0]["end"] == pytest.approx(4355.0)
    assert result[1]["start"] == pytest.approx(4361.5)

    # Word-level timestamps must ALSO be shifted
    assert result[0]["words"][0]["start"] == pytest.approx(4351.5)
    assert result[0]["words"][0]["end"] == pytest.approx(4352.3)
    assert result[0]["words"][1]["start"] == pytest.approx(4352.4)
    assert result[0]["words"][1]["end"] == pytest.approx(4353.0)
    assert result[1]["words"][0]["start"] == pytest.approx(4361.5)
    assert result[1]["words"][0]["end"] == pytest.approx(4362.5)

    # Original segments must NOT be mutated
    assert segments[0]["words"][0]["start"] == 0.0
    assert segments[0]["start"] == 0.0
