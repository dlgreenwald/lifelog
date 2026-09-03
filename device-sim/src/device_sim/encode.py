"""Opus encoder wrappers using ffmpeg."""

from __future__ import annotations

import subprocess


def encode_opus(wav_path: str, opus_path: str) -> None:
    """Encode a WAV file to Opus using ffmpeg.

    Args:
        wav_path: input 16-kHz mono WAV.
        opus_path: output path for the Opus file.

    Raises:
        RuntimeError: if ffmpeg returns non-zero.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        wav_path,
        "-c:a",
        "libopus",
        "-b:a",
        "24000",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-application",
        "voip",
        opus_path,
    ]
    result = subprocess.run(cmd, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg encode failed: {result.stderr.decode()}")


def encode_silent_opus(duration_s: float, opus_path: str) -> None:
    """Generate a silent Opus file of the given duration.

    Args:
        duration_s: duration in seconds.
        opus_path: output path for the silent Opus file.

    Raises:
        RuntimeError: if ffmpeg returns non-zero.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=mono:sample_rate=16000",
        "-t",
        str(duration_s),
        "-c:a",
        "libopus",
        "-b:a",
        "24000",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-application",
        "voip",
        opus_path,
    ]
    result = subprocess.run(cmd, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg encode_silent_opus failed: {result.stderr.decode()}"
        )
