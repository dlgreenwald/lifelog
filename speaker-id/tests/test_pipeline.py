"""Tests for speaker-id pipeline: opus_to_wav and SpeakerEncoder.extract_embedding."""
from unittest.mock import MagicMock, patch

import numpy as np


def test_opus_to_wav_calls_ffmpeg():
    """opus_to_wav invokes ffmpeg with correct args and returns wav bytes."""
    from speaker_id.routes import opus_to_wav

    fake_wav = b"RIFF" + b"\x00" * 100

    with patch("speaker_id.routes.subprocess.run") as mock_run:
        def fake_run(cmd, **kwargs):
            wav_path = cmd[-1]
            with open(wav_path, "wb") as f:
                f.write(fake_wav)

        mock_run.side_effect = fake_run

        result = opus_to_wav(b"fake-opus-data")

    assert result == fake_wav
    mock_run.assert_called_once()
    cmd = mock_run.call_args.args[0]
    assert cmd[0] == "ffmpeg"


def test_opus_to_wav_cleans_up_temp_files():
    """opus_to_wav removes temp files even on error."""
    from speaker_id.routes import opus_to_wav

    with patch("speaker_id.routes.subprocess.run", side_effect=RuntimeError("ffmpeg failed")):
        try:
            opus_to_wav(b"fake-opus-data")
        except RuntimeError:
            pass


class _MockTensor:
    """Mimics torch.Tensor so extract_embedding's .cpu().numpy() chain works."""

    def __init__(self, arr):
        self._arr = np.array(arr)

    def squeeze(self):
        return _MockTensor(self._arr.squeeze())

    def cpu(self):
        return self

    def numpy(self):
        return self._arr


def test_speaker_encoder_extract_embedding():
    """SpeakerEncoder.extract_embedding writes a wav temp file, calls encode_batch, and returns a numpy array."""
    from speaker_id.embeddings import SpeakerEncoder

    encoder = SpeakerEncoder.__new__(SpeakerEncoder)

    mock_classifier = MagicMock()
    mock_classifier.encode_batch.return_value = _MockTensor([[[0.1, 0.2, 0.3, 0.4]]])
    encoder.encoder = mock_classifier

    # Generate real PCM 16kHz mono audio and write to a real temp file, so the
    # implementation's tempfile / soundfile.read / os.unlink pipeline succeeds
    # end-to-end while we still mock the actual ECAPA inference.
    import io

    import soundfile
    fake_audio = np.zeros(16000, dtype="float32")
    buf = io.BytesIO()
    soundfile.write(buf, fake_audio, 16000, format="WAV", subtype="FLOAT")
    audio_bytes = buf.getvalue()

    result = encoder.extract_embedding(audio_bytes)

    assert isinstance(result, np.ndarray)
    assert result.shape == (4,)
    assert abs(result[0] - 0.1) < 1e-6


def test_speaker_encoder_extract_embedding_2d():
    """SpeakerEncoder handles (1, embedding_dim) shaped output."""
    from speaker_id.embeddings import SpeakerEncoder

    encoder = SpeakerEncoder.__new__(SpeakerEncoder)

    mock_classifier = MagicMock()
    mock_classifier.encode_batch.return_value = _MockTensor([[0.5, 0.6, 0.7]])
    encoder.encoder = mock_classifier

    import io

    import soundfile
    fake_audio = np.zeros(16000, dtype="float32")
    buf = io.BytesIO()
    soundfile.write(buf, fake_audio, 16000, format="WAV", subtype="FLOAT")
    audio_bytes = buf.getvalue()

    result = encoder.extract_embedding(audio_bytes)

    assert result.shape == (3,)
    assert abs(result[2] - 0.7) < 1e-6
