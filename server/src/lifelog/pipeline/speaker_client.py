import base64
import json
import logging
import time

import httpx

from lifelog.config import settings
from lifelog.database import get_all_voiceprints


def serialize_embedding(embedding: list[float] | bytes) -> bytes:
    """Store new float embeddings without losing precision."""
    if isinstance(embedding, bytes):
        return embedding
    return json.dumps(embedding).encode("utf-8")


logger = logging.getLogger("lifelog.speaker_id")


async def identify_speakers(
    segments: list[dict], audio_bytes: bytes, user_id: int, audio_format: str = "opus"
) -> list[dict]:
    """Send diarized segments and encoded audio to speaker-id-service."""
    start = time.monotonic()
    voiceprints = await get_all_voiceprints(user_id)
    voiceprint_data = []
    for vp in voiceprints:
        embedding = vp["embedding"]
        if isinstance(embedding, bytes):
            try:
                embedding = json.loads(embedding.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                embedding = list(embedding)
        voiceprint_data.append({"name": vp["name"], "embedding": list(embedding)})
    logger.info(
        "Identifying speakers: %d segments, %d voiceprints for user %d",
        len(segments),
        len(voiceprint_data),
        user_id,
    )
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            f"{settings.speaker_id_url}/identify",
            json={
                "segments": segments,
                "audio_format": audio_format,
                "audio_bytes": base64.b64encode(audio_bytes).decode("ascii"),
                "voiceprints": voiceprint_data,
            },
        )
        response.raise_for_status()
        result = response.json()["speakers"]
    duration = time.monotonic() - start
    matched = [
        speaker
        for speaker in result
        if speaker.get("name") and speaker["name"] != "Unknown"
    ]
    logger.info(
        "Speaker identification complete in %.2fs: %d results, %d matched to voiceprints",
        duration,
        len(result),
        len(matched),
    )
    return result
