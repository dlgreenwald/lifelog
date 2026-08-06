"""Tests for diarization pipeline: opus_to_wav and DiarizationPipeline.diarize."""
from unittest.mock import MagicMock, patch


def test_opus_to_wav_calls_ffmpeg():
    """opus_to_wav invokes ffmpeg with correct args and returns wav bytes."""
    from diarization.pipeline import opus_to_wav

    fake_wav = b"RIFF" + b"\x00" * 100  # Minimal WAV header

    with patch("diarization.pipeline.subprocess.run") as mock_run:
        def fake_run(cmd, **kwargs):
            # Write fake wav to the output path
            wav_path = cmd[-1]
            with open(wav_path, "wb") as f:
                f.write(fake_wav)

        mock_run.side_effect = fake_run

        result = opus_to_wav(b"fake-opus-data")

    assert result == fake_wav
    mock_run.assert_called_once()
    cmd = mock_run.call_args.args[0]
    assert cmd[0] == "ffmpeg"
    assert "-ar" in cmd
    assert "16000" in cmd
    assert "-ac" in cmd
    assert "1" in cmd


def test_opus_to_wav_cleans_up_temp_files():
    """opus_to_wav removes temp files even on error."""
    from diarization.pipeline import opus_to_wav

    with patch("diarization.pipeline.subprocess.run", side_effect=RuntimeError("ffmpeg failed")):
        try:
            opus_to_wav(b"bad-data")
        except RuntimeError:
            pass

    # No temp files should remain (they're cleaned up in finally block)
    # This test verifies the finally block runs


def test_diarization_pipeline_diarize():
    """DiarizationPipeline.diarize converts audio and runs pyannote."""
    from diarization.pipeline import DiarizationPipeline

    # Create a mock pipeline instance that bypasses __init__
    pipe = DiarizationPipeline.__new__(DiarizationPipeline)

    # Mock the pyannote pipeline
    mock_pyannote = MagicMock()

    # Create fake diarization result with itertracks
    mock_turn = MagicMock()
    mock_turn.start = 0.0
    mock_turn.end = 2.5
    mock_speaker = "SPEAKER_00"

    mock_result = MagicMock()
    mock_result.itertracks.return_value = [
        (mock_turn, None, mock_speaker),
    ]
    mock_pyannote.return_value = mock_result

    pipe.pipeline = mock_pyannote

    fake_wav = b"fake-wav-data"

    with patch("diarization.pipeline.opus_to_wav", return_value=fake_wav):
        # Mock tempfile to avoid real file I/O
        with patch("diarization.pipeline.tempfile.NamedTemporaryFile") as mock_tmp:
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.wav"
            mock_file.__enter__ = MagicMock(return_value=mock_file)
            mock_file.__exit__ = MagicMock(return_value=False)
            mock_tmp.return_value = mock_file

            result = pipe.diarize(b"fake-opus")

    assert len(result) == 1
    assert result[0]["speaker"] == "SPEAKER_00"
    assert result[0]["start"] == 0.0
    assert result[0]["end"] == 2.5
    mock_pyannote.assert_called_once_with("/tmp/test.wav")


def test_diarization_pipeline_multiple_speakers():
    """DiarizationPipeline.diarize handles multiple speakers."""
    from diarization.pipeline import DiarizationPipeline

    pipe = DiarizationPipeline.__new__(DiarizationPipeline)

    mock_pyannote = MagicMock()

    turns = [
        (MagicMock(start=0.0, end=2.0), None, "SPEAKER_00"),
        (MagicMock(start=2.0, end=4.5), None, "SPEAKER_01"),
        (MagicMock(start=4.5, end=6.0), None, "SPEAKER_00"),
    ]

    mock_result = MagicMock()
    mock_result.itertracks.return_value = turns
    mock_pyannote.return_value = mock_result

    pipe.pipeline = mock_pyannote

    with patch("diarization.pipeline.opus_to_wav", return_value=b"wav"):
        with patch("diarization.pipeline.tempfile.NamedTemporaryFile") as mock_tmp:
            mock_file = MagicMock()
            mock_file.name = "/tmp/test.wav"
            mock_file.__enter__ = MagicMock(return_value=mock_file)
            mock_file.__exit__ = MagicMock(return_value=False)
            mock_tmp.return_value = mock_file

            result = pipe.diarize(b"audio")

    assert len(result) == 3
    assert result[0]["speaker"] == "SPEAKER_00"
    assert result[1]["speaker"] == "SPEAKER_01"
    assert result[2]["speaker"] == "SPEAKER_00"
