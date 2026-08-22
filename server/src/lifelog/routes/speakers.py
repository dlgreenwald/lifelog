import logging
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException

from lifelog.auth import validate_oidc_token
from lifelog.config import settings
from lifelog.crypto import audio_crypto
from lifelog.database import (
    get_recording,
    get_unknown_speakers,
    save_voiceprint,
    update_recording_speakers,
    update_speaker_name,
)
from lifelog.models import SpeakerLabel
from lifelog.pipeline.speaker_client import identify_speakers

logger = logging.getLogger("lifelog.speakers")

router = APIRouter()


def extract_speaker_audio(recording: dict, speaker_id: str) -> bytes:
    """Extract audio for a specific speaker segment from the recording."""
    # Decrypt the full audio
    audio_bytes = audio_crypto.decrypt_audio(
        recording["audio_filename"],
        recording["encryption_secret"],
        bytes(recording["key_salt"]),
    )
    return audio_bytes


@router.post("/label")
async def label_speaker(label: SpeakerLabel, user: dict = Depends(validate_oidc_token)):
    """Label an unknown speaker in a recording."""
    start = time.monotonic()
    logger.info(
        "Labeling speaker: recording=%d, speaker=%s → '%s'",
        label.recording_id,
        label.speaker_id,
        label.label,
    )

    recording = await get_recording(user["id"], label.recording_id)
    if not recording:
        logger.warning("Recording %d not found for user %d", label.recording_id, user["id"])
        raise HTTPException(status_code=404, detail="Recording not found")

    # Update speaker name in database
    await update_speaker_name(label.recording_id, label.speaker_id, label.label)

    # Extract audio for this speaker segment
    segment_audio = extract_speaker_audio(recording, label.speaker_id)
    logger.info("Enrolling voiceprint for '%s' (%d bytes audio)", label.label, len(segment_audio))

    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            f"{settings.speaker_id_url}/enroll",
            params={"name": label.label},
            files={"file": ("segment.wav", segment_audio, "audio/wav")},
        )
        response.raise_for_status()
        embedding = response.json()["embedding"]

    # Save voiceprint to database (orchestrator owns DB)
    await save_voiceprint(user["id"], label.label, bytes(embedding))
    logger.info("Voiceprint saved for '%s'", label.label)

    # Re-run identification on all recordings with unknowns
    rerun_start = time.monotonic()
    await rerun_identification(user)
    rerun_duration = time.monotonic() - rerun_start

    total_duration = time.monotonic() - start
    logger.info(
        "Speaker labeling complete in %.2fs (re-identification: %.2fs)",
        total_duration,
        rerun_duration,
    )

    return {"status": "labeled", "label": label.label}


async def rerun_identification(user: dict):
    """Re-run speaker identification on all recordings with unknowns."""
    recordings = await get_unknown_speakers(user["id"])
    logger.info("Re-identifying speakers on %d recordings", len(recordings))

    for i, recording in enumerate(recordings):
        audio_bytes = audio_crypto.decrypt_audio(
            recording["audio_filename"],
            user["encryption_secret"],
            bytes(user["key_salt"]),
        )
        speakers = recording["speakers"]

        identified = await identify_speakers(speakers, audio_bytes, user["id"])
        await update_recording_speakers(recording["id"], identified)
        logger.debug("Re-identified recording %d/%d (id=%d)", i + 1, len(recordings), recording["id"])
