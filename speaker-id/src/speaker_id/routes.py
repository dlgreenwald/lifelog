import subprocess
import tempfile

import numpy as np
from fastapi import APIRouter, UploadFile

from speaker_id.config import settings
from speaker_id.embeddings import encoder

router = APIRouter()


@router.post("/identify")
async def identify_speakers(data: dict):
    """Identify speakers in diarized segments using provided voiceprints."""
    segments = data["segments"]
    data.get("voiceprints", [])
    data.get("audio_format", "opus")

    identified_segments = []

    for seg in segments:
        # For now, use a simple matching approach
        # In production, you'd extract audio segments and compare embeddings
        name = "Unknown"

        identified_segments.append(
            {
                **seg,
                "name": name,
            }
        )

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
