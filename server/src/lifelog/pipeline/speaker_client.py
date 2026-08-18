import logging
import time

import httpx

from lifelog.config import settings
from lifelog.database import get_all_voiceprints

logger = logging.getLogger("lifelog.speaker_id")


async def identify_speakers(
    segments: list[dict], audio_bytes: bytes, user_id: int
) -> list[dict]:
    """Send diarized segments to speaker-id-service."""
    start = time.monotonic()

    # Get voiceprints for this user from database
    voiceprints = await get_all_voiceprints(user_id)

    # Convert voiceprints to format expected by speaker-id service
    voiceprint_data = []
    for vp in voiceprints:
        voiceprint_data.append(
            {
                "name": vp["name"],
                "embedding": list(vp["embedding"]),
            }
        )

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
                "audio_format": "opus",
                "voiceprints": voiceprint_data,
            },
        )
        response.raise_for_status()
        result = response.json()["speakers"]

    duration = time.monotonic() - start
    matched = [s for s in result if s.get("name") and s["name"] != "Unknown"]
    logger.info(
        "Speaker identification complete in %.2fs: %d results, %d matched to voiceprints",
        duration,
        len(result),
        len(matched),
    )

    return result
