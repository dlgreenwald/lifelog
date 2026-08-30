import base64
import math
import os
import subprocess
import tempfile

import numpy as np
from fastapi import APIRouter, UploadFile

from speaker_id.config import settings
from speaker_id.embeddings import encoder

router = APIRouter()


def _extract_segment_wav(
    audio_bytes: bytes, audio_format: str, start: float, end: float
) -> bytes:
    """Extract one diarized range as mono 16-bit WAV."""
    if end <= start:
        return b""
    suffix = ".wav" if audio_format == "wav" else ".opus"
    with tempfile.TemporaryDirectory(prefix="speaker-segment-") as directory:
        source = os.path.join(directory, f"source{suffix}")
        target = os.path.join(directory, "segment.wav")
        with open(source, "wb") as output:
            output.write(audio_bytes)
        process = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(start),
                "-to",
                str(end),
                "-i",
                source,
                "-ar",
                "16000",
                "-ac",
                "1",
                "-y",
                target,
            ],
            capture_output=True,
            check=False,
        )
        if process.returncode or not os.path.exists(target):
            return b""
        with open(target, "rb") as input_file:
            return input_file.read()


@router.post("/identify")
async def identify_speakers(data: dict):
    """Identify diarized speakers from supplied audio and voiceprints."""
    segments = data.get("segments", [])
    voiceprints = data.get("voiceprints", [])
    encoded_audio = data.get("audio_bytes")
    audio_format = data.get("audio_format", "opus")
    audio_bytes = None
    if encoded_audio and voiceprints:
        try:
            audio_bytes = base64.b64decode(encoded_audio, validate=True)
        except (ValueError, TypeError):
            audio_bytes = None

    identified_segments = []
    for segment in segments:
        item = dict(segment)
        original_label = segment.get("speaker", "Unknown")
        name = original_label
        if audio_bytes and voiceprints:
            try:
                start = float(segment["start"])
                end = float(segment["end"])
                if (
                    math.isfinite(start)
                    and math.isfinite(end)
                    and start >= 0
                    and end > start
                ):
                    wav_bytes = _extract_segment_wav(
                        audio_bytes, audio_format, start, end
                    )
                    if wav_bytes:
                        embedding = encoder.extract_embedding(wav_bytes)
                        name = match_voiceprint(embedding, voiceprints)
            except (
                KeyError,
                TypeError,
                ValueError,
                OverflowError,
                RuntimeError,
                OSError,
            ):
                name = original_label
        item["name"] = name
        identified_segments.append(item)
    return {"speakers": identified_segments}


def match_voiceprint(
    embedding: np.ndarray,
    voiceprints: list[dict],
    threshold: float = settings.similarity_threshold,
) -> str:
    """Match embedding against provided voiceprints."""
    best_name = "Unknown"
    best_sim = 0

    for vp in voiceprints:
        vp_embedding = np.array(vp["embedding"])
        sim = cosine_similarity(embedding, vp_embedding)
        if sim > best_sim:
            best_sim = sim
            best_name = vp["name"]

    return best_name if best_sim > threshold else "Unknown"


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


@router.post("/enroll")
async def enroll_speaker(name: str, file: UploadFile):
    """Enroll a new speaker from audio sample."""
    audio_bytes = await file.read()

    # Convert to wav for embedding extraction
    wav_bytes = opus_to_wav(audio_bytes)

    # Extract embedding
    embedding = encoder.extract_embedding(wav_bytes)

    # Return embedding to orchestrator (which saves to DB)
    return {"name": name, "embedding": embedding.tolist()}


def opus_to_wav(opus_bytes: bytes) -> bytes:
    """Convert Opus to WAV format."""
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
