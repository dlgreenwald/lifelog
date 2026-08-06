import ssl

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

router = APIRouter()


def extract_speaker_audio(recording: dict, speaker_id: str) -> bytes:
    """Extract audio for a specific speaker segment from the recording."""
    # Decrypt the full audio
    audio_bytes = audio_crypto.decrypt_audio(
        recording["audio_filename"],
        recording["user_id"],
        recording["encryption_secret"],
    )
    return audio_bytes


@router.post("/label")
async def label_speaker(label: SpeakerLabel, user: dict = Depends(validate_oidc_token)):
    """Label an unknown speaker in a recording."""
    recording = await get_recording(user["id"], label.recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    # Update speaker name in database
    await update_speaker_name(label.recording_id, label.speaker_id, label.label)

    # Get embedding from speaker-id service via HTTPS
    ssl_context = ssl.create_default_context(cafile=settings.speaker_id_cert)

    # Extract audio for this speaker segment
    segment_audio = extract_speaker_audio(recording, label.speaker_id)

    async with httpx.AsyncClient(verify=ssl_context, timeout=300) as client:
        response = await client.post(
            f"{settings.speaker_id_url}/enroll",
            params={"name": label.label},
            files={"file": ("segment.wav", segment_audio, "audio/wav")},
        )
        embedding = response.json()["embedding"]

    # Save voiceprint to database (orchestrator owns DB)
    await save_voiceprint(user["id"], label.label, bytes(embedding))

    # Re-run identification on all recordings with unknowns
    await rerun_identification(user)

    return {"status": "labeled", "label": label.label}


async def rerun_identification(user: dict):
    """Re-run speaker identification on all recordings with unknowns."""
    recordings = await get_unknown_speakers(user["id"])
    for recording in recordings:
        audio_bytes = audio_crypto.decrypt_audio(
            recording["audio_filename"],
            user["id"],
            user["encryption_secret"],
        )
        speakers = recording["speakers"]

        identified = await identify_speakers(speakers, audio_bytes, user["id"])

        await update_recording_speakers(recording["id"], identified)
