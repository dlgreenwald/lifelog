import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException

from lifelog.auth import validate_oidc_token
from lifelog.config import settings
from lifelog.crypto import audio_crypto
from lifelog.database import (
    get_recording,
    get_unknown_speakers,
    save_voiceprint,
    update_recording_speaker_data,
    update_recording_speakers,
    update_speaker_name,
)
from lifelog.models import SpeakerLabel
from lifelog.pipeline.speaker_client import identify_speakers, serialize_embedding

logger = logging.getLogger("lifelog.speakers")

router = APIRouter()


def extract_speaker_audio(recording: dict, speaker_id: str) -> bytes:
    """Decrypt and return the first matching stored speaker segment.

    Legacy recordings without segment metadata use the full recording audio.
    """
    secret = recording["encryption_secret"]
    salt = bytes(recording["key_salt"])
    for segment in recording.get("speaker_segments") or []:
        label = segment.get("speaker") or segment.get("name")
        if label != speaker_id or not segment.get("audio_filename"):
            continue
        try:
            return audio_crypto.decrypt_audio(segment["audio_filename"], secret, salt)
        except Exception:
            logger.warning("Skipping unavailable speaker segment %s", segment.get("audio_filename"), exc_info=True)
    if recording.get("speaker_segments"):
        raise ValueError("speaker has no stored audio")
    filename = recording.get("audio_filename")
    if not filename:
        filenames = recording.get("audio_filenames") or []
        filename = filenames[0] if filenames else None
    if not filename:
        raise ValueError("recording has no audio")
    return audio_crypto.decrypt_audio(filename, secret, salt)


@router.post("/label")
async def label_speaker(label: SpeakerLabel, user: dict = Depends(validate_oidc_token)):
    """Label an unknown speaker in a recording."""
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

    # Keep credentials private to this in-memory copy; never return them to the dashboard.
    recording_for_audio = dict(recording)
    recording_for_audio["encryption_secret"] = user["encryption_secret"]
    recording_for_audio["key_salt"] = user.get("key_salt", recording.get("key_salt", b""))
    segment_audio = extract_speaker_audio(recording_for_audio, label.speaker_id)
    logger.info("Enrolling voiceprint for '%s' (%d bytes audio)", label.label, len(segment_audio))

    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            f"{settings.speaker_id_url}/enroll",
            params={"name": label.label},
            files={"file": ("segment.opus", segment_audio, "audio/opus")},
        )
        response.raise_for_status()
        embedding = response.json()["embedding"]

    await save_voiceprint(user["id"], label.label, serialize_embedding(embedding))
    logger.info("Voiceprint saved for '%s'", label.label)

    return {"status": "labeled", "label": label.label}


async def rerun_identification(user: dict):
    """Re-run identification on unresolved recordings and segment audio."""
    recordings = await get_unknown_speakers(user["id"])
    logger.info("Re-identifying speakers on %d recordings", len(recordings))
    for index, recording in enumerate(recordings):
        segments = recording.get("speaker_segments") or []
        if not segments:
            audio_bytes = audio_crypto.decrypt_audio(
                recording["audio_filename"], user["encryption_secret"], bytes(user["key_salt"])
            )
            identified = await identify_speakers(recording["speakers"], audio_bytes, user["id"])
            await update_recording_speakers(recording["id"], identified)
        else:
            updated_segments = []
            for segment in segments:
                item = dict(segment)
                raw = item.get("speaker") or item.get("name") or "Unknown"
                if item.get("audio_filename"):
                    try:
                        audio = audio_crypto.decrypt_audio(
                            item["audio_filename"], user["encryption_secret"], bytes(user["key_salt"])
                        )
                        identified = await identify_speakers(
                            [{"speaker": raw, "start": 0, "end": 1}],
                            audio, user["id"], audio_format="wav",
                        )
                        item["speaker"] = identified[0].get("name", raw) if identified else raw
                    except Exception:
                        logger.warning("Unable to re-identify segment for '%s'", raw, exc_info=True)
                updated_segments.append(item)
            await update_recording_speaker_data(
                recording["id"],
                [
                    {"id": index, "name": segment["speaker"], "start": segment.get("start", 0),
                     "end": segment.get("end", 0), "text": segment.get("text", "")}
                    for index, segment in enumerate(updated_segments)
                ],
                updated_segments,
            )
        logger.debug("Re-identified recording %d/%d (id=%d)", index + 1, len(recordings), recording["id"])
