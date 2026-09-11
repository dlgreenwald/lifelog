import base64
import json
import time

import httpx
import structlog

from lifelog.config import settings
from lifelog.database import get_all_voiceprints


def serialize_embedding(embedding: list[float] | bytes) -> bytes:
    """Store new float embeddings without losing precision."""
    if isinstance(embedding, bytes):
        return embedding
    return json.dumps(embedding).encode("utf-8")


logger = structlog.get_logger()


async def resolve_speaker(user: dict, segment_audios: list[bytes]) -> dict:
    """Centroid + match for one raw label's segment audio against the user's voiceprints."""
    start = time.monotonic()
    voiceprints = await get_all_voiceprints(user["id"])
    voiceprint_data = []
    for vp in voiceprints:
        embedding = vp["embedding"]
        if isinstance(embedding, bytes):
            try:
                embedding = json.loads(embedding.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                embedding = list(embedding)
        voiceprint_data.append(
            {
                "speaker_id": vp["speaker_id"],
                "name": vp["name"],
                "embedding": list(embedding),
            }
        )
    logger.info(
        "resolving_speaker",
        audio_count=len(segment_audios),
        voiceprint_count=len(voiceprint_data),
        user_id=user["id"],
    )
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            f"{settings.speaker_id_url}/resolve",
            json={
                "audio_b64": [
                    base64.b64encode(audio).decode("ascii") for audio in segment_audios
                ],
                "voiceprints": voiceprint_data,
            },
        )
        if response.status_code == 400:
            logger.warning("speaker_resolve_400", response_body=response.text)
        response.raise_for_status()
        result = response.json()
    duration = time.monotonic() - start
    logger.info(
        "speaker_resolved",
        duration=duration,
        audio_count=len(segment_audios),
        voiceprint_count=len(voiceprint_data),
        matched=result.get("match") is not None,
    )
    return result
