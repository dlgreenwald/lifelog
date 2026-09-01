from unittest.mock import patch

import numpy as np
import pytest

from audio import (
    concatenate_segments,
    concatenate_segments_with_spans,
    decode_audio,
    waveform_to_numpy,
)


def test_decode_rejects_empty_audio():
    with pytest.raises(ValueError, match="empty"):
        decode_audio(b"")


def test_concatenate_rejects_mismatched_lists():
    with pytest.raises(ValueError, match="equal lengths"):
        concatenate_segments([b"a"], ["2025-01-01T00:00:00", "2025-01-01T00:00:01"])


def test_concatenate_places_timestamp_gap():
    samples = np.ones(4, dtype=np.float32)
    with patch("audio.decode_audio", side_effect=[(samples, 4), (samples, 4)]):
        result, rate = concatenate_segments(
            [b"a", "b" * 1],
            ["2025-01-01T00:00:00", "2025-01-01T00:00:02"],
        )
    assert rate == 4
    assert result.tolist() == [1, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1]


def test_waveform_to_numpy_preserves_suitable_array():
    waveform = np.zeros(4, dtype=np.float32)
    assert waveform_to_numpy(waveform) is waveform


def test_concatenate_segments_with_spans_emits_correct_offsets():
    """Each utterance's span pairs (start, end) with its true placement in
    the concatenated waveform, regardless of timestamp gaps.
    """
    samples_short = np.ones(3, dtype=np.float32)
    samples_long = np.full(6, 2.0, dtype=np.float32)
    with patch(
        "audio.decode_audio",
        side_effect=[(samples_short, 2), (samples_long, 2)],
    ):
        waveform, sample_rate, spans = concatenate_segments_with_spans(
            [b"a", b"b"],
            ["2025-01-01T00:00:00", "2025-01-01T00:00:03"],
        )
    assert sample_rate == 2
    # First utterance: 0..1.5s; second utterance starts after 3s gap = 6 samples.
    assert spans[0] == (0.0, 1.5)
    assert spans[1] == (3.0, 6.0)
    assert waveform.shape == (12,)
    assert waveform[:3].tolist() == [1, 1, 1]
    assert waveform[6:12].tolist() == [2, 2, 2, 2, 2, 2]
    assert waveform[3:6].tolist() == [0, 0, 0]


def test_concatenate_segments_legacy_signature_still_two_tuple_return():
    """``concatenate_segments`` callers expect a 2-tuple (waveform, sample_rate).
    Backward-compat regression guard for the spans refactor.
    """
    samples = np.ones(4, dtype=np.float32)
    with patch("audio.decode_audio", return_value=(samples, 4)):
        result = concatenate_segments([b"a"], ["2025-01-01T00:00:00"])
    assert isinstance(result, tuple)
    assert len(result) == 2
