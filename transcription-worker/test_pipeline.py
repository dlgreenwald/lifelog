import base64
import sys
from unittest.mock import MagicMock, patch

import numpy as np

from pipeline import (
    _extract_segment_wav,
    group_into_speaker_segments,
    quick_transcribe,
    transcribe_audio,
)


def test_group_merges_consecutive_speakers():
    result = group_into_speaker_segments([
        {"speaker": "A", "start": 0, "end": 1, "text": " hello "},
        {"speaker": "A", "start": 1, "end": 2, "text": "world"},
        {"speaker": "B", "start": 2, "end": 3, "text": "bye"},
    ])
    assert result[0] == {"speaker": "A", "start": 0.0, "end": 2.0, "text": "hello world", "segment_indices": [0, 1]}
    assert result[1]["speaker"] == "B"


def test_missing_speaker_defaults_unknown():
    assert group_into_speaker_segments([{"start": 0, "end": 1, "text": "x"}])[0]["speaker"] == "Unknown"


def test_wav_extraction_is_bounded():
    encoded = _extract_segment_wav(np.arange(10, dtype=np.float32), 10, [{"start": -1, "end": 0.5}], [0])
    assert base64.b64decode(encoded).startswith(b"RIFF")


def test_quick_transcribe_only_calls_asr():
    asr = MagicMock()
    asr.transcribe.return_value = {"segments": [{"text": "hi"}]}
    result = quick_transcribe({"asr": asr}, np.zeros(10, dtype=np.float32), 16000)
    assert result == {"segments": [{"text": "hi"}], "full_transcript": {"segments": [{"text": "hi"}]}}
    asr.transcribe.assert_called_once()


def test_full_result_shape_and_audio():
    asr = MagicMock()
    asr.transcribe.return_value = {"segments": [{"speaker": "SPEAKER_00", "start": 0, "end": 0.01, "text": "hi"}], "language": "en"}
    diarize = MagicMock(return_value=MagicMock())
    fake_whisperx = MagicMock()
    fake_whisperx.assign_word_speakers.return_value = {"segments": asr.transcribe.return_value["segments"]}
    with patch.dict(sys.modules, {"whisperx": fake_whisperx}):
        result = transcribe_audio({"asr": asr, "diarize": diarize, "device": "cpu"}, np.ones(160, dtype=np.float32), 16000)
    assert set(result) == {"segments", "full_transcript", "speaker_map", "speaker_segments"}
    assert result["speaker_segments"][0]["speaker"] == "SPEAKER_00"
    assert "audio" in result["speaker_segments"][0]
    assert "segment_indices" not in result["speaker_segments"][0]
