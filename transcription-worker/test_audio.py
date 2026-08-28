from unittest.mock import patch

import numpy as np
import pytest

from audio import concatenate_segments, decode_audio, waveform_to_numpy


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
            [b"a", b"b"],
            ["2025-01-01T00:00:00", "2025-01-01T00:00:02"],
        )
    assert rate == 4
    assert result.tolist() == [1, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1]


def test_waveform_to_numpy_preserves_suitable_array():
    waveform = np.zeros(4, dtype=np.float32)
    assert waveform_to_numpy(waveform) is waveform
