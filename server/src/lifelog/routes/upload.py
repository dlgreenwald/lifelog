import logging
import time

from fastapi import APIRouter, Depends, Form, UploadFile

from lifelog.auth import validate_api_key
from lifelog import database
from lifelog.database import save_utterance_chunk

logger = logging.getLogger("lifelog.upload")

router = APIRouter()


@router.post("/upload")
async def upload_audio(
    file: UploadFile,
    utterance_id: int = Form(...),
    chunk_index: int = Form(...),
    is_final: bool = Form(...),
    user: dict = Depends(validate_api_key),
):
    """Accept Opus audio chunk. Store it; worker processes on is_final."""
    audio_bytes = await file.read()

    logger.info(
        "Upload: user=%d, utt=%d, chunk=%d, final=%s, size=%d bytes",
        user["id"],
        utterance_id,
        chunk_index,
        is_final,
        len(audio_bytes),
    )

    # Store chunk
    await save_utterance_chunk(
        user["id"], utterance_id, chunk_index, audio_bytes, is_final
    )

    if not is_final:
        return {
            "status": "chunk_stored",
            "utterance_id": utterance_id,
            "chunk_index": chunk_index,
        }

    # Enqueue for background processing
    async with database.pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO utterance_queue (user_id, utterance_id, status)
               VALUES ($1, $2, 'pending')
               ON CONFLICT (user_id, utterance_id) DO NOTHING""",
            user["id"],
            utterance_id,
        )

    logger.info("Utterance %d/%d enqueued for processing", user["id"], utterance_id)

    return {
        "status": "enqueued",
        "utterance_id": utterance_id,
    }


@router.get("/utterance/{utterance_id}/status")
async def get_utterance_status(
    utterance_id: int,
    user: dict = Depends(validate_api_key),
):
    """Check processing status of an utterance."""
    async with database.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT status, error, started_at, completed_at
               FROM utterance_queue
               WHERE user_id = $1 AND utterance_id = $2""",
            user["id"],
            utterance_id,
        )

    if not row:
        return {"status": "unknown", "utterance_id": utterance_id}

    return {
        "status": row["status"],
        "utterance_id": utterance_id,
        "error": row["error"],
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
    }
