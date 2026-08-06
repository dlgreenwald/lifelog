"""Unit tests for merge_speakers helper in upload route."""
from lifelog.routes.upload import merge_speakers


def test_merge_speakers_basic():
    """Basic merge: each speaker gets matching transcript text."""
    transcript = {
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "Hello"},
            {"start": 2.0, "end": 4.0, "text": "World"},
        ]
    }
    diarization = [
        {"speaker": "SPEAKER_00", "start": 0.0, "end": 2.0},
        {"speaker": "SPEAKER_01", "start": 2.0, "end": 4.0},
    ]
    speakers = [
        {"name": "Alice", "start": 0.0, "end": 2.0},
        {"name": "Bob", "start": 2.0, "end": 4.0},
    ]

    result = merge_speakers(transcript, diarization, speakers)

    assert len(result) == 2
    assert result[0]["name"] == "Alice"
    assert result[0]["text"] == "Hello"
    assert result[1]["name"] == "Bob"
    assert result[1]["text"] == "World"


def test_merge_speakers_overlapping_transcript():
    """Transcript segment spans multiple speakers."""
    transcript = {
        "segments": [
            {"start": 0.0, "end": 3.0, "text": "Long segment"},
        ]
    }
    speakers = [
        {"name": "Alice", "start": 0.0, "end": 1.5},
        {"name": "Bob", "start": 1.5, "end": 3.0},
    ]

    result = merge_speakers(transcript, [], speakers)

    assert len(result) == 2
    # Both speakers overlap with the transcript segment
    assert "Long segment" in result[0]["text"]
    assert "Long segment" in result[1]["text"]


def test_merge_speakers_no_transcript_segments():
    """No transcript segments results in empty text."""
    speakers = [
        {"name": "Alice", "start": 0.0, "end": 2.0},
    ]

    result = merge_speakers({}, [], speakers)

    assert len(result) == 1
    assert result[0]["text"] == ""


def test_merge_speakers_unknown_speaker():
    """Unknown speakers are handled correctly."""
    speakers = [
        {"name": "Unknown", "start": 0.0, "end": 2.0},
    ]
    transcript = {"segments": [{"start": 0.5, "end": 1.5, "text": "Mystery"}]}

    result = merge_speakers(transcript, [], speakers)

    assert result[0]["name"] == "Unknown"
    assert result[0]["text"] == "Mystery"


def test_merge_speakers_preserves_ids():
    """Segment IDs are assigned sequentially."""
    speakers = [
        {"name": "A", "start": 0.0, "end": 1.0},
        {"name": "B", "start": 1.0, "end": 2.0},
        {"name": "C", "start": 2.0, "end": 3.0},
    ]

    result = merge_speakers({}, [], speakers)

    assert [s["id"] for s in result] == [0, 1, 2]


def test_merge_speakers_missing_name_defaults_unknown():
    """Speakers without a name default to Unknown."""
    speakers = [
        {"start": 0.0, "end": 1.0},
    ]

    result = merge_speakers({}, [], speakers)

    assert result[0]["name"] == "Unknown"


def test_merge_speakers_no_matching_transcript():
    """No overlapping transcript segments means empty text."""
    transcript = {
        "segments": [
            {"start": 10.0, "end": 12.0, "text": "Far away"},
        ]
    }
    speakers = [
        {"name": "Alice", "start": 0.0, "end": 2.0},
    ]

    result = merge_speakers(transcript, [], speakers)

    assert result[0]["text"] == ""
