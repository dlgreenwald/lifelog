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
                "end": 2,
                "text": "hello",
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
                "end": 2,
                "text": "hi",
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
            {"speaker": "SPEAKER_00", "start": 0, "end": 2, "text": "hello"}
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
