import asyncio
import time
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Form, Header, HTTPException, UploadFile

from lifelog import database
from lifelog.auth import validate_bearer_token
from lifelog.config import settings
from lifelog.crypto import audio_crypto
from lifelog.database import save_utterance_chunk


def _opus_sample_rate(audio_bytes: bytes) -> int | None:
    """Extract the original sample rate from an OGG/Opus file using opusinfo.

    Parses opusinfo output for "Original sample rate: XXXX Hz".
    Falls back to None if opusinfo is unavailable or parsing fails.
    """
    if len(audio_bytes) < 100:
        return None
    import os
    import re
    import subprocess
    import tempfile

    try:
        with tempfile.NamedTemporaryFile(suffix=".opus", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                ["opusinfo", tmp_path],
                capture_output=True,
                text=True,
                check=False,
            )
            output = result.stdout + result.stderr
            match = re.search(r"Original sample rate:\s*(\d+)\s*Hz", output)
            if match:
                return int(match.group(1))
        finally:
            os.unlink(tmp_path)
    except Exception:  # noqa: BLE001, S110
        pass
    return None


logger = structlog.get_logger()

router = APIRouter()


async def validate_upload_auth(
    authorization: str = Header(...),
) -> dict:
    """Validate upload authentication: Bearer token required."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization[7:]
    return await validate_bearer_token(token)


# Maximum chunk size: 10 MB
MAX_CHUNK_SIZE = 10 * 1024 * 1024

# Utterance tracking TTL: evict entries older than this
UTTERANCE_TTL = 1800  # 30 minutes

# {user_id: {device_utterance_id: {"server_id": int, "last_chunk": int}}}
_active_utterances: dict[int, dict[int, dict]] = {}


def _evict_stale_utterances() -> None:
    """Evict tracking entries older than UTTERANCE_TTL to prevent unbounded growth."""
    now = _current_epoch()
    for uid in list(_active_utterances):
        for dev_id in list(_active_utterances[uid]):
            entry = _active_utterances[uid][dev_id]
            if now - entry.get("last_seen", now) > UTTERANCE_TTL:
                logger.warning(
                    "evicting_stale_utterance", user_id=uid, device_id=dev_id
                )
                _active_utterances[uid].pop(dev_id)
        if not _active_utterances[uid]:
            del _active_utterances[uid]


def _current_epoch() -> int:
    """Current epoch seconds.  Mock this in tests."""
    return int(time.time())


async def _finalize_utterance(
    user_id: int, server_utt_id: int, device_timestamp: datetime | None = None
) -> None:
    """Enqueue a completed utterance for processing if not already queued."""
    async with database.pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO utterance_queue (user_id, utterance_id, status, recorded_at)
               VALUES ($1, $2, 'pending', $3)
               ON CONFLICT (user_id, utterance_id) DO NOTHING""",
            user_id,
            server_utt_id,
            device_timestamp,
        )
    logger.info("utterance_enqueued", user_id=user_id, utterance_id=server_utt_id)
    # Trigger transcription immediately — don't wait for the 60s poll loop.
    # Import lazily to avoid circular import.
    from lifelog.worker import process_utterance

    asyncio.create_task(process_utterance(user_id, server_utt_id))


@router.post("/upload")
async def upload_audio(
    file: UploadFile,
    utterance_id: int = Form(...),
    chunk_index: int = Form(...),
    is_final: bool = Form(...),
    recorded_at: int | None = Form(None),
    user: dict = Depends(validate_upload_auth),
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
    if len(audio_bytes) > MAX_CHUNK_SIZE:
        raise HTTPException(status_code=413, detail="Chunk too large")
    user_id = user["id"]

    # Compute wall-clock timestamp from device, if provided and sane
    device_timestamp: datetime | None = None
    if recorded_at is not None:
        now = _current_epoch()
        # Reject timestamps obviously wrong (device clock drifted years off)
        if recorded_at <= now + 300 and recorded_at >= now - 604800:
            device_timestamp = datetime.fromtimestamp(recorded_at, tz=UTC).replace(
                tzinfo=None
            )
        else:
            logger.warning("device_time_rejected", recorded_at=recorded_at, now=now)

    # Evict stale utterance tracking entries
    _evict_stale_utterances()

    logger.info(
        "upload_chunk",
        user_id=user_id,
        device_utt=utterance_id,
        chunk_index=chunk_index,
        is_final=is_final,
        size_bytes=len(audio_bytes),
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
        user_utterances[device_utt] = {
            "server_id": server_utt_id,
            "last_chunk": chunk_index,
            "last_seen": _current_epoch(),
        }
    else:
        entry = user_utterances[device_utt]
        # New utterance on same device id: chunk_index resets to 0 after
        # prior chunk was > 0
        if chunk_index == 0 and entry["last_chunk"] > 0:
            # Finalize old utterance
            await _finalize_utterance(user_id, entry["server_id"])
            server_utt_id = _current_epoch()
            user_utterances[device_utt] = {
                "server_id": server_utt_id,
                "last_chunk": 0,
                "last_seen": _current_epoch(),
            }
        elif chunk_index < entry["last_chunk"]:
            # Device restarted — lower chunk_index without reset to 0
            # shouldn't happen per firmware contract, but handle defensively
            await _finalize_utterance(user_id, entry["server_id"])
            server_utt_id = _current_epoch()
            user_utterances[device_utt] = {
                "server_id": server_utt_id,
                "last_chunk": chunk_index,
                "last_seen": _current_epoch(),
            }
        else:
            # Continuation of same utterance
            server_utt_id = entry["server_id"]
            entry["last_chunk"] = chunk_index
            entry["last_seen"] = _current_epoch()

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
            user_utterances[device_utt] = {
                "server_id": server_utt_id,
                "last_chunk": 0,
                "last_seen": _current_epoch(),
            }

    # Store chunk
    await save_utterance_chunk(
        user_id, server_utt_id, chunk_index, audio_bytes, is_final
    )

    if is_final:
        rate = _opus_sample_rate(audio_bytes)
        logger.info(
            "upload_final",
            user_id=user_id,
            device_utt=utterance_id,
            server_utt=server_utt_id,
            size_bytes=len(audio_bytes),
            sample_rate=rate,
        )
        await _finalize_utterance(user_id, server_utt_id, device_timestamp)
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
    user: dict = Depends(validate_upload_auth),
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
        "completed_at": row["completed_at"].isoformat()
        if row["completed_at"]
        else None,
    }


@router.post("/upload/offline")
async def upload_offline(
    file: UploadFile,
    session_id: int | None = Form(None),
    recorded_at: int = Form(...),
    duration_s: float | None = Form(None),
    user: dict = Depends(validate_upload_auth),
):
    """Accept an offline-recorded Opus audio file.

    Stores the recording with its original backdated ``recorded_at`` timestamp
    and groups it into an offline session. The firmware signals end-of-burst
    separately via POST /upload/offline/burst-end.
    """
    audio_bytes = await file.read()
    if len(audio_bytes) > MAX_CHUNK_SIZE:
        raise HTTPException(status_code=413, detail="File too large")
    user_id = user["id"]

    # Convert Unix epoch to naive UTC datetime — accept any positive value
    recorded_at_dt = datetime.fromtimestamp(recorded_at, tz=UTC).replace(tzinfo=None)

    # Resolve or create offline session:
    # Case 1: session_id provided and session is active → extend it
    # Case 2: session_id provided but session ended → if recorded_at within range,
    #          add to that session (firmware lost s_offlineSessionId after WiFi drop)
    # Case 3: no session_id → look up most recent active offline session and check
    #          time gap (same grouping as live /upload path)
    # Case 4: no active session with overlap → create new session
    resolved_session_id = None
    if session_id is not None:
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, status, started_at, ended_at
                FROM sessions
                WHERE id = $1 AND user_id = $2 AND offline = true
                """,
                session_id,
                user_id,
            )
        if row is not None:
            if row["status"] == "active":
                # Case 1/2a: active session — extend and use it
                resolved_session_id = row["id"]
                await database.update_offline_session_range(
                    resolved_session_id, recorded_at_dt
                )
            elif row["status"] == "ended":
                # Case 2b: ended session — if recorded_at overlaps, add to it
                started_at = row["started_at"] or recorded_at_dt
                ended_at = row["ended_at"] or recorded_at_dt
                if started_at <= recorded_at_dt <= ended_at:
                    # recorded_at falls within this ended session — add to it
                    resolved_session_id = row["id"]
                    # Don't update session range since it's ended

    if resolved_session_id is None:
        # Case 3: no session_id from firmware, or session ended with no overlap.
        # Look up the most recent active offline session and check time proximity
        # (same grouping logic as the live /upload path).
        active = await database.get_active_offline_session(user_id)
        if active is not None:
            # Get the most recent recording in this session to compute gap
            last_rec = await database.get_last_offline_recording_time(active["id"])
            ref_time = last_rec if last_rec is not None else active["started_at"]
            gap_minutes = (
                recorded_at_dt - ref_time.replace(tzinfo=None)
            ).total_seconds() / 60
            if gap_minutes <= settings.session_gap_minutes:
                # Within gap threshold — extend and reuse this session
                resolved_session_id = active["id"]
                await database.update_offline_session_range(
                    resolved_session_id, recorded_at_dt
                )
            else:
                # Gap too large — end old session, create new one
                await database.end_offline_session(
                    active["id"],
                    datetime.now(UTC).replace(tzinfo=None),
                )
                resolved_session_id = await database.create_offline_session(
                    user_id, recorded_at_dt
                )
        else:
            # No active offline session — create one
            resolved_session_id = await database.create_offline_session(
                user_id, recorded_at_dt
            )
    session_id = resolved_session_id

    # Encrypt and save audio — user from validate_upload_auth already has encryption_secret/key_salt
    audio_filename = audio_crypto.encrypt_audio(
        audio_bytes,
        user["encryption_secret"],
        bytes(user["key_salt"]),
    )

    # Save recording with backdated timestamp
    recording_id = await database.save_offline_recording(
        user_id,
        audio_filename,
        session_id,
        recorded_at_dt,
    )

    logger.info(
        "upload_offline",
        user_id=user_id,
        session_id=session_id,
        recording_id=recording_id,
        recorded_at=recorded_at,
        size_bytes=len(audio_bytes),
    )
    return {"status": "ok", "session_id": session_id, "recording_id": recording_id}


@router.post("/upload/offline/burst-end")
async def burst_end(
    session_id: int = Form(...),
    user: dict = Depends(validate_upload_auth),
):
    """Signal end of an offline upload burst.

    Closes the offline session and fires asynchronous transcription processing.
    """
    user_id = user["id"]

    # Verify session belongs to user and is offline
    async with database.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, user_id FROM sessions
            WHERE id = $1 AND user_id = $2 AND offline = true AND status = 'active'
            """,
            session_id,
            user_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Active offline session not found")

    # End session with current server time
    ended_at = datetime.now(UTC).replace(tzinfo=None)
    await database.end_offline_session(session_id, ended_at)

    # Fire-and-forget: run full transcription pipeline
    from lifelog.worker import _process_offline_session

    session = {"id": session_id, "user_id": user_id}
    asyncio.create_task(_process_offline_session(session))

    logger.info("offline_burst_end", user_id=user_id, session_id=session_id)
    return {"status": "ok", "session_id": session_id}
