import ssl

import httpx

from lifelog.config import settings
from lifelog.database import get_all_voiceprints


async def identify_speakers(
    segments: list[dict], audio_bytes: bytes, user_id: int
) -> list[dict]:
    """Send diarized segments to speaker-id-service via HTTPS."""
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

    ssl_context = ssl.create_default_context(cafile=settings.speaker_id_cert)

    async with httpx.AsyncClient(verify=ssl_context, timeout=300) as client:
        response = await client.post(
            f"{settings.speaker_id_url}/identify",
            json={
                "segments": segments,
                "audio_format": "opus",
                "voiceprints": voiceprint_data,
            },
        )
        return response.json()["speakers"]
