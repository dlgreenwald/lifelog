import io
import logging
import time

import httpx

from lifelog.config import settings

logger = logging.getLogger("lifelog.transcribe")


async def transcribe(audio_bytes: bytes) -> dict:
    """Transcribe audio via whisper-asr-webservice with diarization.

    Returns dict with keys: text, segments (with speaker labels), language.
    """
    logger.info("Transcribing %d bytes of audio", len(audio_bytes))
    start = time.monotonic()

    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            f"{settings.whisper_asr_url}/asr",
            params={
                "output": "json",
                "diarize": "true",
                "language": "en",
            },
            files={"audio_file": ("audio.opus", io.BytesIO(audio_bytes), "audio/opus")},
        )
        response.raise_for_status()
        result = response.json()

    duration = time.monotonic() - start
    text = result.get("text", "")
    segments = result.get("segments", [])
    speakers = {seg.get("speaker") for seg in segments if seg.get("speaker")}

    logger.info(
        "Transcription complete in %.2fs: %d chars, %d segments, %d speakers (%s)",
        duration,
        len(text),
        len(segments),
        len(speakers),
        ", ".join(sorted(speakers)) if speakers else "none",
    )

    return result
