import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException

from lifelog.auth import validate_oidc_token
from lifelog.database import delete_speaker, merge_speakers, rename_speaker
from lifelog.models import SpeakerMerge, SpeakerRename

logger = structlog.get_logger()

router = APIRouter()


@router.post("/rename")
async def rename_speaker_route(
    body: SpeakerRename, user: dict = Depends(validate_oidc_token)
):
    """Rename a speaker across its voiceprints and recordings."""
    try:
        renamed = await rename_speaker(user["id"], body.speaker_id, body.name)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="Speaker name already exists")
    if not renamed:
        raise HTTPException(status_code=404, detail="Speaker not found")
    logger.info(
        "speaker_renamed",
        user_id=user["id"],
        speaker_id=body.speaker_id,
        name=body.name,
    )
    return {"ok": True, "speaker_id": body.speaker_id, "name": body.name}


@router.post("/merge")
async def merge_speakers_route(
    body: SpeakerMerge, user: dict = Depends(validate_oidc_token)
):
    """Merge one speaker into another."""
    if body.source_id == body.target_id:
        raise HTTPException(
            status_code=400, detail="Cannot merge a speaker into itself"
        )
    merged = await merge_speakers(user["id"], body.source_id, body.target_id)
    if not merged:
        raise HTTPException(status_code=404, detail="Speaker not found")
    logger.info(
        "speakers_merged",
        user_id=user["id"],
        source_id=body.source_id,
        target_id=body.target_id,
    )
    return {"ok": True, "speaker_id": body.target_id}


@router.delete("/{speaker_id}")
async def delete_speaker_route(
    speaker_id: int, user: dict = Depends(validate_oidc_token)
):
    """Delete an enrolled speaker; recordings revert to raw labels."""
    deleted = await delete_speaker(user["id"], speaker_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Speaker not found")
    logger.info("speaker_deleted", user_id=user["id"], speaker_id=speaker_id)
    return {"ok": True}
