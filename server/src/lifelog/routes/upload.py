import logging
import time

from fastapi import APIRouter, Depends, Form, UploadFile

from lifelog import database
from lifelog.auth import validate_api_key
from lifelog.database import save_utterance_chunk

logger = logging.getLogger("lifelog.upload")

router = APIRouter()

# {user_id: {device_utterance_id: {"server_id": int, "last_chunk": int}}}
_active_utterances: dict[int, dict[int, dict]] = {}


def _current_epoch() -> int:
    """Current epoch seconds.  Mock this in tests."""
    return int(time.time())


async def _finalize_utterance(user_id: int, server_utt_id: int) -> None:
    """Enqueue a completed utterance for processing if not already queued."""
    async with database.pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO utterance_queue (user_id, utterance_id, status)
               VALUES ($1, $2, 'pending')
               ON CONFLICT (user_id, utterance_id) DO NOTHING""",
            user_id,
            server_utt_id,
        )
    logger.info("Utterance %d/%d enqueued for processing", user_id, server_utt_id)


@router.post("/upload")
async def upload_audio(
    file: UploadFile,
    utterance_id: int = Form(...),
    chunk_index: int = Form(...),
    is_final: bool = Form(...),
    user: dict = Depends(validate_api_key),
):
    """Accept Opus audio chunk. Store it; worker processes on is_final.

    The device sends its own ``utterance_id`` (file counter, resets on
    reboot) with each chunk.  The server assigns a monotonic
    ``server_utt_id`` based on ``time.time()`` millis when it sees the
    first chunk of a new utterance, detecting boundaries via:
      - ``chunk_index == 0`` while a prior chunk exists for same device id
      - device ``utterance_id`` lower than any currently tracked (reboot)
    """
    audio_bytes = await file.read()
    user_id = user["id"]

    logger.info(
        "Upload: user=%d, device_utt=%d, chunk=%d, final=%s, size=%d bytes",
        user_id,
        utterance_id,
        chunk_index,
        is_final,
        len(audio_bytes),
    )

    user_utterances = _active_utterances.setdefault(user_id, {})
    device_utt = utterance_id

    # Detect utterance boundary and assign server ID
    if device_utt not in user_utterances:
        # New device utterance ID — possibly new utterance.
        # If chunk_index == 0 and there are other active entries, check
        # whether an existing entry for a DIFFERENT device id has chunks.
        # If chunk_index > 0 with no entry, firmware bug — still assign.
        server_utt_id = _current_epoch()
        user_utterances[device_utt] = {"server_id": server_utt_id, "last_chunk": chunk_index}
    else:
        entry = user_utterances[device_utt]
        # New utterance on same device id: chunk_index resets to 0 after
        # prior chunk was > 0
        if chunk_index == 0 and entry["last_chunk"] > 0:
            # Finalize old utterance
            await _finalize_utterance(user_id, entry["server_id"])
            server_utt_id = _current_epoch()
            user_utterances[device_utt] = {"server_id": server_utt_id, "last_chunk": 0}
        elif chunk_index < entry["last_chunk"]:
            # Device restarted — lower chunk_index without reset to 0
            # shouldn't happen per firmware contract, but handle defensively
            await _finalize_utterance(user_id, entry["server_id"])
            server_utt_id = _current_epoch()
            user_utterances[device_utt] = {"server_id": server_utt_id, "last_chunk": chunk_index}
        else:
            # Continuation of same utterance
            server_utt_id = entry["server_id"]
            entry["last_chunk"] = chunk_index

    # Handle device reboot: utterance_id went backwards relative to max
    max_known = max(user_utterances.keys()) if user_utterances else None
    if max_known is not None and device_utt < max_known and chunk_index == 0:
        # Finalize all other active utterances for this user
        for dev_id, info in list(user_utterances.items()):
            if dev_id != device_utt:
                await _finalize_utterance(user_id, info["server_id"])
                del user_utterances[dev_id]
        # Re-assign for the rebooted device
        if device_utt not in user_utterances:
            server_utt_id = _current_epoch()
            user_utterances[device_utt] = {"server_id": server_utt_id, "last_chunk": 0}

    # Store chunk
    await save_utterance_chunk(
        user_id, server_utt_id, chunk_index, audio_bytes, is_final
    )

    if is_final:
        await _finalize_utterance(user_id, server_utt_id)
        user_utterances.pop(device_utt, None)
        return {"status": "enqueued", "utterance_id": server_utt_id}

    return {
        "status": "chunk_stored",
        "utterance_id": server_utt_id,
        "chunk_index": chunk_index,
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
