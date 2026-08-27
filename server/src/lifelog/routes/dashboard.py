import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from lifelog.auth import validate_oidc_token
from lifelog.crypto import audio_crypto
from lifelog.database import (
    create_decision,
    create_todo,
    delete_decision,
    delete_recording,
    delete_todo,
    get_active_session_recording,
    get_daily_summary,
    get_decision_owner,
    get_decisions,
    get_decisions_for_recording,
    get_recording,
    get_recordings_by_date,
    get_todo_owner,
    get_todos,
    get_todos_for_date,
    get_todos_for_recording,
    get_unknown_speakers,
    reset_session_for_reprocessing,
    update_decision_archive,
    update_recording_category,
    update_todo_completion,
)
from lifelog.models import CreateDecision, CreateTodo

logger = logging.getLogger("lifelog.dashboard")


def _normalize_recording(rec: dict) -> dict:
    """Ensure summary is a string — LLM may return {"summary": "..."} instead of "..."."""
    summary = rec.get("summary")
    if isinstance(summary, dict):
        rec["summary"] = summary.get("summary", str(summary))
    elif isinstance(summary, str) and summary.startswith("{"):
        try:
            import json
            parsed = json.loads(summary)
            if isinstance(parsed, dict):
                rec["summary"] = parsed.get("summary", str(parsed))
        except (json.JSONDecodeError, ValueError):
            pass
    return rec


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
    return {"recordings": [_normalize_recording(r) for r in recordings]}


@router.get("/recording/{recording_id}")
async def get_recording_detail(recording_id: int, user: dict = Depends(validate_oidc_token)):
    """Get full recording details including speakers and segments."""
    logger.debug("Recording detail request: user=%d, recording=%d", user["id"], recording_id)
    recording = await get_recording(user["id"], recording_id)
    if not recording:
        logger.warning("Recording %d not found for user %d", recording_id, user["id"])
        raise HTTPException(status_code=404, detail="Recording not found")
    return _normalize_recording(recording)


@router.get("/audio/{filename}")
async def get_audio(filename: str, user: dict = Depends(validate_oidc_token)):
    """Stream decrypted audio file."""
    logger.debug("Audio stream request: user=%d, file=%s", user["id"], filename)
    try:
        audio_bytes = audio_crypto.decrypt_audio(
            filename, user["encryption_secret"], bytes(user["key_salt"])
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return StreamingResponse(
        iter([audio_bytes]),
        media_type="audio/opus",
        headers={"Content-Disposition": f"inline; filename={filename}"},
    )


@router.get("/todos")
async def get_todos_route(user: dict = Depends(validate_oidc_token)):
    """Get all todos across all recordings."""
    todos = await get_todos(user["id"])
    logger.debug("Todos request: user=%d, found=%d", user["id"], len(todos))
    return {"todos": todos}


@router.post("/todos")
async def create_todo_route(body: CreateTodo, user: dict = Depends(validate_oidc_token)):
    """Create a new todo. recording_id is optional (null for standalone)."""
    if body.recording_id is not None:
        recording = await get_recording(user["id"], body.recording_id)
        if not recording:
            raise HTTPException(status_code=404, detail="Recording not found")
    todo_id = await create_todo(
        user_id=user["id"],
        task=body.task,
        owner=body.owner,
        due=body.due,
        priority=body.priority,
        recording_id=body.recording_id,
    )
    return {"id": todo_id}


@router.get("/todos/{date}")
async def get_todos_for_date_route(date: str, user: dict = Depends(validate_oidc_token)):
    """Get todos from recordings on a specific date (YYYY-MM-DD)."""
    todos = await get_todos_for_date(user["id"], date)
    return {"todos": todos}


@router.get("/recording/{recording_id}/todos")
async def get_recording_todos_route(
    recording_id: int, user: dict = Depends(validate_oidc_token)
):
    """Get todos for a specific recording. Verifies user owns the recording."""
    recording = await get_recording(user["id"], recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    todos = await get_todos_for_recording(recording_id)
    return {"todos": todos}


@router.post("/todos/{todo_id}/complete")
async def complete_todo_route(
    todo_id: int, body: dict, user: dict = Depends(validate_oidc_token)
):
    """Mark a todo as completed or incomplete. Verifies user owns the todo."""
    owner = await get_todo_owner(todo_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    if owner != user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    completed = body.get("completed", False)
    await update_todo_completion(todo_id, completed)
    return {"ok": True}


@router.delete("/todos/{todo_id}")
async def delete_todo_route(
    todo_id: int, user: dict = Depends(validate_oidc_token)
):
    """Delete a todo. Verifies user owns the todo."""
    owner = await get_todo_owner(todo_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    if owner != user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    await delete_todo(todo_id)
    return {"ok": True}


@router.get("/decisions")
async def get_decisions_route(
    user: dict = Depends(validate_oidc_token),
    limit: int = 50,
    include_archived: bool = False,
):
    """Get recent decisions across all recordings."""
    decisions = await get_decisions(user["id"], limit, include_archived)
    logger.debug("Decisions request: user=%d, found=%d", user["id"], len(decisions))
    return {"decisions": decisions}


@router.post("/decisions")
async def create_decision_route(body: CreateDecision, user: dict = Depends(validate_oidc_token)):
    """Create a new decision. recording_id is optional (null for standalone)."""
    if body.recording_id is not None:
        recording = await get_recording(user["id"], body.recording_id)
        if not recording:
            raise HTTPException(status_code=404, detail="Recording not found")
    decision_id = await create_decision(
        user_id=user["id"],
        decision=body.decision,
        made_by=body.made_by,
        context=body.context,
        reason=body.reason,
        recording_id=body.recording_id,
    )
    return {"id": decision_id}


@router.get("/recording/{recording_id}/decisions")
async def get_recording_decisions_route(
    recording_id: int, user: dict = Depends(validate_oidc_token)
):
    """Get all decisions for a specific recording."""
    recording = await get_recording(user["id"], recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    decisions = await get_decisions_for_recording(recording_id)
    return {"decisions": decisions}


@router.post("/decisions/{decision_id}/archive")
async def archive_decision_route(
    decision_id: int, body: dict, user: dict = Depends(validate_oidc_token)
):
    """Archive or unarchive a decision."""
    owner = await get_decision_owner(decision_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    if owner != user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    await update_decision_archive(decision_id, body.get("archived", False))
    return {"ok": True}


@router.delete("/decisions/{decision_id}")
async def delete_decision_route(
    decision_id: int, user: dict = Depends(validate_oidc_token)
):
    """Delete a decision."""
    owner = await get_decision_owner(decision_id)
    if owner is None:
        raise HTTPException(status_code=404, detail="Decision not found")
    if owner != user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    await delete_decision(decision_id)
    return {"ok": True}


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
    # Normalize nested objects — LLM may return {"Work": {"summary": "..."}} instead of {"Work": "..."}
    if isinstance(summary, dict) and isinstance(summary.get("daily_summary"), dict):
        for key, val in summary["daily_summary"].items():
            if isinstance(val, dict):
                summary["daily_summary"][key] = val.get("summary", str(val))
    return {"daily_summary": summary}
