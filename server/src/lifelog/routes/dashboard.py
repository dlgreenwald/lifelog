from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from lifelog.auth import validate_oidc_token
from lifelog.crypto import audio_crypto
from lifelog.database import (
    get_decisions,
    get_recording,
    get_recordings_by_date,
    get_todos,
    get_unknown_speakers,
)

router = APIRouter()


@router.get("/calendar/{year}/{month}")
async def get_calendar(year: int, month: int, user: dict = Depends(validate_oidc_token)):
    """Get calendar data for a month (days with recordings)."""

    from lifelog.database import pool

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DATE(timestamp) as date, COUNT(*) as count
            FROM recordings
            WHERE user_id = $1
              AND EXTRACT(YEAR FROM timestamp) = $2
              AND EXTRACT(MONTH FROM timestamp) = $3
            GROUP BY DATE(timestamp)
            ORDER BY date
        """,
            user["id"],
            year,
            month,
        )
        return {"dates": [dict(row) for row in rows]}


@router.get("/recordings/{date}")
async def get_day_recordings(date: str, user: dict = Depends(validate_oidc_token)):
    """Get all recordings for a specific day (YYYY-MM-DD)."""
    recordings = await get_recordings_by_date(user["id"], date)
    return {"recordings": recordings}


@router.get("/recording/{recording_id}")
async def get_recording_detail(recording_id: int, user: dict = Depends(validate_oidc_token)):
    """Get full recording details including speakers and segments."""
    recording = await get_recording(user["id"], recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    return recording


@router.get("/audio/{filename}")
async def get_audio(filename: str, user: dict = Depends(validate_oidc_token)):
    """Stream decrypted audio file."""
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
    return {"todos": todos}


@router.get("/decisions")
async def get_decisions_route(user: dict = Depends(validate_oidc_token), limit: int = 20):
    """Get recent decisions across all recordings."""
    decisions = await get_decisions(user["id"], limit)
    return {"decisions": decisions}


@router.get("/unknown-speakers")
async def get_unknown_speakers_route(user: dict = Depends(validate_oidc_token)):
    """Get all recordings with unknown speakers for labeling."""
    recordings = await get_unknown_speakers(user["id"])
    return {"recordings": recordings}
