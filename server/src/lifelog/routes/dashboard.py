import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from lifelog.auth import validate_oidc_token
from lifelog.crypto import audio_crypto
from lifelog.database import (
    delete_recording,
    get_active_session_recording,
    get_daily_summary,
    get_decisions,
    get_recording,
    get_recordings_by_date,
    get_todos,
    get_unknown_speakers,
    reset_session_for_reprocessing,
    update_recording_category,
)

logger = logging.getLogger("lifelog.dashboard")

router = APIRouter()


@router.get("/calendar/{year}/{month}")
async def get_calendar(year: int, month: int, user: dict = Depends(validate_oidc_token)):
    """Get calendar data for a month (days with recordings)."""
    logger.debug("Calendar request: user=%d, year=%d, month=%d", user["id"], year, month)

    from lifelog.database import pool

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DATE(timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York') as date, COUNT(*) as count
            FROM recordings
            WHERE user_id = $1
              AND EXTRACT(YEAR FROM timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York') = $2
              AND EXTRACT(MONTH FROM timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York') = $3
            GROUP BY date
            ORDER BY date
        """,
            user["id"],
            year,
            month,
        )
        return {"dates": [dict(row) for row in rows]}


@router.get("/recordings/{date}")
async def get_day_recordings(
    date: str,
    user: dict = Depends(validate_oidc_token),
    category: str | None = None,
):
    """Get all recordings for a specific day (YYYY-MM-DD).

    Optional query param: category (personal, work, not_meaningful).
    """
    logger.debug("Day recordings request: user=%d, date=%s, category=%s", user["id"], date, category)
    recordings = await get_recordings_by_date(user["id"], date, category=category)
    logger.debug("Found %d recordings for %s", len(recordings), date)
    return {"recordings": recordings}


@router.get("/recording/{recording_id}")
async def get_recording_detail(recording_id: int, user: dict = Depends(validate_oidc_token)):
    """Get full recording details including speakers and segments."""
    logger.debug("Recording detail request: user=%d, recording=%d", user["id"], recording_id)
    recording = await get_recording(user["id"], recording_id)
    if not recording:
        logger.warning("Recording %d not found for user %d", recording_id, user["id"])
        raise HTTPException(status_code=404, detail="Recording not found")
    return recording


@router.get("/audio/{filename}")
async def get_audio(filename: str, user: dict = Depends(validate_oidc_token)):
    """Stream decrypted audio file."""
    logger.debug("Audio stream request: user=%d, file=%s", user["id"], filename)
    audio_bytes = audio_crypto.decrypt_audio(
        filename, user["id"], user["encryption_secret"]
    )
    return StreamingResponse(
        iter([audio_bytes]),
        media_type="audio/opus",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )


@router.get("/todos")
async def get_todos_route(user: dict = Depends(validate_oidc_token)):
    """Get all open TODOs across all recordings."""
    todos = await get_todos(user["id"])
    logger.debug("Todos request: user=%d, found=%d", user["id"], len(todos))
    return {"todos": todos}


@router.get("/decisions")
async def get_decisions_route(user: dict = Depends(validate_oidc_token), limit: int = 20):
    """Get recent decisions across all recordings."""
    decisions = await get_decisions(user["id"], limit)
    logger.debug("Decisions request: user=%d, found=%d", user["id"], len(decisions))
    return {"decisions": decisions}


@router.get("/unknown-speakers")
async def get_unknown_speakers_route(user: dict = Depends(validate_oidc_token)):
    """Get all recordings with unknown speakers for labeling."""
    recordings = await get_unknown_speakers(user["id"])
    logger.debug("Unknown speakers request: user=%d, found=%d", user["id"], len(recordings))
    return {"recordings": recordings}


@router.delete("/recording/{recording_id}")
async def delete_recording_route(recording_id: int, user: dict = Depends(validate_oidc_token)):
    """Delete a recording."""
    deleted = await delete_recording(user["id"], recording_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Recording not found")
    return {"ok": True}


@router.post("/recording/{recording_id}/reprocess")
async def reprocess_recording_route(recording_id: int, user: dict = Depends(validate_oidc_token)):
    """Requeue a recording for reprocessing at the next hourly run.

    Resets the session status to 'ended' and deletes the existing recording.
    The hourly reprocess loop will regenerate it with batch transcription.
    """
    recording = await get_recording(user["id"], recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    session_id = recording.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Recording has no associated session")

    reset = await reset_session_for_reprocessing(session_id)
    if not reset:
        raise HTTPException(status_code=404, detail="Session not found")

    logger.info(
        "Recording %d requeued for reprocessing (session %d)", recording_id, session_id
    )
    return {"ok": True, "session_id": session_id}


@router.post("/recording/{recording_id}/category")
async def update_category_route(
    recording_id: int,
    body: dict,
    user: dict = Depends(validate_oidc_token),
):
    """Update the category classification for a recording."""
    category = body.get("category")
    if category not in ("work", "personal", "not_meaningful", ""):
        raise HTTPException(status_code=400, detail="Invalid category")

    recording = await get_recording(user["id"], recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    await update_recording_category(recording_id, category)
    logger.info("Recording %d category updated to '%s'", recording_id, category)
    return {"ok": True}


@router.get("/active-recording")
async def get_active_recording_route(user: dict = Depends(validate_oidc_token)):
    """Get the current active session as a recording (live view)."""
    recording = await get_active_session_recording(user["id"])
    return recording


@router.get("/daily-summary/{date}")
async def get_daily_summary_route(date: str, user: dict = Depends(validate_oidc_token)):
    """Get the daily summary for a specific date (YYYY-MM-DD)."""
    summary = await get_daily_summary(user["id"], date)
    return {"daily_summary": summary}
