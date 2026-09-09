import base64
import logging
import subprocess
import tempfile

import numpy as np
import torch
from fastapi import APIRouter, HTTPException

from speaker_id.config import settings
from speaker_id.embeddings import encoder

logger = logging.getLogger(__name__)

router = APIRouter()


def compute_centroid(embeddings: list[np.ndarray]) -> np.ndarray:
    """L2-normalize each embedding, take the mean, renormalize."""
    import torch
    import torch.nn.functional as F

    emb = torch.tensor(np.stack(embeddings), dtype=torch.float32)
    emb = F.normalize(emb, p=2, dim=1)  # L2-normalize each
    centroid = F.normalize(emb.mean(dim=0), p=2, dim=0)  # renormalize the mean
    return centroid.cpu().numpy()


def match_centroid(
    centroid: np.ndarray,
    voiceprints: list[dict],
    threshold: float = settings.similarity_threshold,
) -> dict | None:
    """Match a centroid against voiceprints; return best match above threshold."""
    best: dict | None = None
    best_sim = 0.0

    for vp in voiceprints:
        vp_embedding = np.array(vp["embedding"])
        sim = cosine_similarity(centroid, vp_embedding)
        if sim > best_sim:
            best_sim = sim
            best = {"speaker_id": vp["speaker_id"], "name": vp["name"]}

    if best is None or best_sim <= threshold:
        return None
    best["similarity"] = best_sim
    return best


@router.post("/resolve")
async def resolve_speaker(data: dict):
    """Compute a centroid for one raw label's segments and match it to a speaker."""
    encoded_audios = data.get("audio_b64", [])
    voiceprints = data.get("voiceprints", [])

    embeddings: list[np.ndarray] = []
    for encoded in encoded_audios:
        try:
            audio_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            continue
        if audio_bytes.startswith(b"RIFF"):
            wav_bytes = audio_bytes
        else:
            wav_bytes = opus_to_wav(audio_bytes)
        try:
            embeddings.append(encoder.extract_embedding(wav_bytes))
        except torch.OutOfMemoryError:
            # The CUDA caching allocator already retried internally before
            # raising; one more attempt after empty_cache can still fit when
            # driver memory frees between failures (a concurrent request
            # completing, or the transcription worker's post-job release).
            logger.warning("cuda_oom_retrying_segment")
            torch.cuda.empty_cache()
            try:
                embeddings.append(encoder.extract_embedding(wav_bytes))
            except (RuntimeError, OSError) as retry_exc:
                logger.warning("segment_skipped_after_oom_retry error=%s", retry_exc)
                continue
        except (RuntimeError, OSError) as exc:
            logger.warning("segment_skipped_embedding_failed error=%s", exc)
            continue

    if not embeddings:
        raise HTTPException(status_code=400, detail="no valid audio")

    centroid = compute_centroid(embeddings)
    match = match_centroid(centroid, voiceprints) if voiceprints else None
    return {"centroid": centroid.tolist(), "match": match}


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


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
