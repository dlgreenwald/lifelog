import ssl

import httpx

from lifelog.config import settings


async def diarize(audio_bytes: bytes) -> list[dict]:
    """Send audio to diarization-service via HTTPS."""
    ssl_context = ssl.create_default_context(cafile=settings.diarization_cert)

    async with httpx.AsyncClient(verify=ssl_context, timeout=300) as client:
        response = await client.post(
            f"{settings.diarization_url}/diarize",
            files={"file": ("audio.opus", audio_bytes, "audio/opus")},
        )
        return response.json()["segments"]
