from fastapi import APIRouter, Depends, UploadFile

from lifelog.auth import validate_api_key
from lifelog.crypto import audio_crypto
from lifelog.database import save_recording
from lifelog.pipeline.diarize_client import diarize
from lifelog.pipeline.llm import summarize
from lifelog.pipeline.speaker_client import identify_speakers
from lifelog.pipeline.transcribe import transcribe

router = APIRouter()


def merge_speakers(
    transcript: dict, diarization: list[dict], speakers: list[dict]
) -> list[dict]:
    """Merge transcript text with diarization timing and speaker names."""
    named_segments = []
    for i, speaker in enumerate(speakers):
        segment = {
            "id": i,
            "name": speaker.get("name", "Unknown"),
            "start": speaker.get("start", 0),
            "end": speaker.get("end", 0),
            "text": "",
        }

        # Try to match with transcript segments
        if "segments" in transcript:
            for tseg in transcript["segments"]:
                t_start = tseg.get("start", 0)
                t_end = tseg.get("end", 0)
                # Overlap check
                if t_start < segment["end"] and t_end > segment["start"]:
                    segment["text"] += tseg.get("text", "") + " "

        segment["text"] = segment["text"].strip()
        named_segments.append(segment)

    return named_segments


@router.post("/upload")
async def upload_audio(file: UploadFile, user: dict = Depends(validate_api_key)):
    """Accept Opus audio, run full pipeline."""
    audio_bytes = await file.read()

    # Encrypt and save audio file with per-user key
    audio_filename = audio_crypto.encrypt_audio(
        audio_bytes, user["id"], user["encryption_secret"]
    )

    # Step 1: Transcribe via Wyoming
    transcript = transcribe(audio_bytes)

    # Step 2: Diarize (who spoke when)
    diarization = await diarize(audio_bytes)

    # Step 3: Identify speakers (pass user_id for voiceprint lookup)
    speakers = await identify_speakers(diarization, audio_bytes, user["id"])

    # Step 4: Merge transcript with speaker names
    named_segments = merge_speakers(transcript, diarization, speakers)

    # Step 5: LLM summarization
    result = summarize(named_segments)

    # Step 6: Store in PostgreSQL (linked to user)
    recording_id = await save_recording(
        user["id"], transcript, named_segments, result, audio_filename
    )

    return {"status": "processed", "recording_id": recording_id}
