import subprocess
import tempfile

import torch
from pyannote.audio import Pipeline

from diarization.config import settings


class DiarizationPipeline:
    def __init__(self):
        self.pipeline = Pipeline.from_pretrained(
            settings.model_name, use_auth_token=settings.hf_token
        )
        self.pipeline.to(torch.device(settings.device))

    def diarize(self, audio_bytes: bytes) -> list[dict]:
        """
        Perform speaker diarization.
        Returns list of {speaker, start, end} segments.
        """
        wav_bytes = opus_to_wav(audio_bytes)

        # Write wav bytes to temp file for pyannote
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            f.flush()

            diarization = self.pipeline(f.name)

        segments = []
        for turn, _, speaker in diarization.itertracks():
            segments.append(
                {
                    "speaker": speaker,
                    "start": turn.start,
                    "end": turn.end,
                }
            )

        return segments


def opus_to_wav(opus_bytes: bytes) -> bytes:
    """Convert Opus to WAV format for pyannote."""
    with tempfile.NamedTemporaryFile(suffix=".opus", delete=False) as opus_file:
        opus_file.write(opus_bytes)
        opus_file.flush()
        opus_path = opus_file.name

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
        wav_path = wav_file.name

    try:
        subprocess.run(
            ["ffmpeg", "-i", opus_path, "-ar", "16000", "-ac", "1", "-y", wav_path],
            check=True,
            capture_output=True,
        )

        with open(wav_path, "rb") as f:
            return f.read()
    finally:
        import os

        os.unlink(opus_path)
        os.unlink(wav_path)


pipeline = DiarizationPipeline()
