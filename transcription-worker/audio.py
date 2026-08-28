"""Audio decoding and timestamp-aware waveform assembly for transcription."""

from __future__ import annotations

import io
import subprocess
import wave
from datetime import datetime

import numpy as np


def decode_audio(audio_bytes: bytes) -> tuple[np.ndarray, int]:
    """Decode an Opus/Ogg or WAV payload to mono float32 samples."""
    if not audio_bytes:
        raise ValueError("audio input is empty")
    process = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", "pipe:0", "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"],
        input=audio_bytes,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0 or not process.stdout:
        detail = process.stderr.decode(errors="replace").strip()[:300]
        raise ValueError(f"unable to decode audio: {detail or 'ffmpeg returned no output'}")
    try:
        with wave.open(io.BytesIO(process.stdout), "rb") as wav:
            sample_rate = wav.getframerate()
            frames = wav.readframes(wav.getnframes())
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
    except (EOFError, wave.Error) as exc:
        raise ValueError("ffmpeg produced an invalid WAV payload") from exc
    if sample_rate <= 0 or not frames or sample_width != 2:
        raise ValueError("decoded audio has no usable 16-bit samples")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1, dtype=np.float32)
    return samples, sample_rate


def _timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def concatenate_segments(
    audio_segments: list[bytes], timestamps: list[str]
) -> tuple[np.ndarray, int]:
    """Decode segments and place them at their relative timestamps."""
    if not audio_segments or not timestamps:
        raise ValueError("audio segments and timestamps are required")
    if len(audio_segments) != len(timestamps):
        raise ValueError("audio segments and timestamps must have equal lengths")
    decoded = [decode_audio(segment) for segment in audio_segments]
    sample_rate = decoded[0][1]
    if any(rate != sample_rate for _, rate in decoded):
        raise ValueError("audio segments have different sample rates")
    start_time = _timestamp(timestamps[0])
    placements = []
    total_samples = 0
    for samples, _ in decoded:
        offset = max(0.0, (_timestamp(timestamps[len(placements)]) - start_time).total_seconds())
        begin = round(offset * sample_rate)
        placements.append((begin, samples))
        total_samples = max(total_samples, begin + len(samples))
    if total_samples <= 0:
        raise ValueError("decoded audio contains no samples")
    output = np.zeros(total_samples, dtype=np.float32)
    for begin, samples in placements:
        output[begin:begin + len(samples)] = samples
    return output, sample_rate


def waveform_to_numpy(waveform: np.ndarray) -> np.ndarray:
    """Normalize a waveform to WhisperX's one-dimensional float32 format."""
    array = np.asarray(waveform)
    if array.ndim == 0:
        array = array.reshape(1)
    elif array.ndim > 1:
        array = array.reshape(-1)
    if array.dtype != np.float32:
        array = array.astype(np.float32)
    return array
