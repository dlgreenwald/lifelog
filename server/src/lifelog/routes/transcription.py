import base64

import structlog
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from lifelog import database as db
from lifelog.crypto import audio_crypto

logger = structlog.get_logger()
router = APIRouter()


class StageUpdate(BaseModel):
    stage: str


class UtteranceSpan(BaseModel):
    utterance_id: int
    start: float
    end: float


class JobResult(BaseModel):
    segments: list[dict]
    full_transcript: dict
    speaker_segments: list[dict] = Field(default_factory=list)
    speaker_map: dict
    utterance_spans: list[UtteranceSpan] = Field(default_factory=list)


class JobError(BaseModel):
    error: str


_ALLOWED_STAGES = {
    "queued",
    "concatenating",
    "transcribing",
    "diarizing",
    "identifying",
    "done",
}


def _iso(value):
    return value.isoformat() if value is not None else None


def _json_value(value, default):
    if isinstance(value, str):
        import json

        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return default
    return value if value is not None else default


async def _job_owner(job: dict) -> dict:
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT u.encryption_secret, u.key_salt
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.id = $1
            """,
            job["session_id"],
        )
    return dict(row) if row else None


@router.post("/claim")
async def claim_job():
    job = await db.claim_transcription_job()
    if job is None:
        return Response(status_code=204)
    return {
        "job_id": job["id"],
        "session_id": job["session_id"],
        "window_start": _iso(job.get("window_start")),
        "window_end": _iso(job.get("window_end")),
        "chunk_index": job.get("chunk_index"),
        "job_type": job.get("job_type") or "full",
        "result": _json_value(job.get("result"), {}),
    }


@router.get("/audio/{job_id}")
async def get_job_audio(job_id: int):
    job = await db.get_transcription_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "processing":
        raise HTTPException(status_code=409, detail="Job is not processing")

    owner = await _job_owner(job)
    if not owner:
        raise HTTPException(status_code=404, detail="Session not found")
    secret = owner["encryption_secret"]
    salt = bytes(owner["key_salt"])
    result = _json_value(job.get("result"), {})

    if (job.get("job_type") or "full") == "quick":
        # Session-level quick job: result contains utterance_ids for all utterances to batch
        utterance_ids = result.get("utterance_ids")
        if utterance_ids:
            # Fetch all utterances in the session window and filter to those in our job
            utterances = await db.get_session_utterances_in_range(
                job["session_id"], job["window_start"], job["window_end"]
            )
            utterances = [u for u in utterances if u["utterance_id"] in utterance_ids]
            audio_segments = []
            timestamps = []
            for utterance in utterances:
                fname = utterance.get("audio_filename")
                if not fname:
                    continue
                try:
                    audio = audio_crypto.decrypt_audio(fname, secret, salt)
                except Exception:
                    logger.warning(
                        "audio_unavailable",
                        filename=fname,
                        job_id=job_id,
                        exc_info=True,
                    )
                    continue
                audio_segments.append(base64.b64encode(audio).decode("ascii"))
                timestamps.append(_iso(utterance["created_at"]))
            if not audio_segments:
                raise HTTPException(
                    status_code=404, detail="No usable audio for session quick job"
                )
            return {
                "audio_segments": audio_segments,
                "timestamps": timestamps,
                "utterances": [],
            }
        # Legacy single-utterance quick job
        filename = result.get("audio_filename")
        try:
            audio = audio_crypto.decrypt_audio(filename, secret, salt)
        except Exception as exc:
            logger.exception("quick_job_decrypt_error", job_id=job_id)
            raise HTTPException(
                status_code=500, detail="Unable to decrypt quick job audio"
            ) from exc
        return {
            "audio_segments": [base64.b64encode(audio).decode("ascii")],
            "timestamps": [],
            "utterances": [],
        }

    utterances = await db.get_session_utterances_in_range(
        job["session_id"], job["window_start"], job["window_end"]
    )
    audio_segments = []
    timestamps = []
    metadata = []
    for utterance in utterances:
        filename = utterance.get("audio_filename")
        if not filename:
            continue
        try:
            audio = audio_crypto.decrypt_audio(filename, secret, salt)
        except Exception:
            logger.warning(
                "audio_unavailable_for_job",
                filename=filename,
                job_id=job_id,
                exc_info=True,
            )
            continue
        audio_segments.append(base64.b64encode(audio).decode("ascii"))
        created_at = utterance["created_at"]
        timestamps.append(_iso(created_at))
        metadata.append(
            {
                "utterance_id": utterance["utterance_id"],
                "audio_filename": filename,
                "created_at": _iso(created_at),
            }
        )
    if not audio_segments:
        raise HTTPException(status_code=404, detail="No usable audio for job")
    return {
        "audio_segments": audio_segments,
        "timestamps": timestamps,
        "utterances": metadata,
    }


@router.post("/stage/{job_id}")
async def update_stage(job_id: int, body: StageUpdate):
    if body.stage not in _ALLOWED_STAGES:
        raise HTTPException(status_code=422, detail="Invalid transcription stage")
    await db.update_job_stage(job_id, body.stage)
    return {"status": "ok"}


@router.post("/complete/{job_id}")
async def complete_job(job_id: int, body: JobResult):
    await db.complete_transcription_job(
        job_id,
        {
            "segments": body.segments,
            "full_transcript": body.full_transcript,
            "speaker_map": body.speaker_map,
            "speaker_segments": body.speaker_segments,
            "utterance_spans": [
                {
                    "utterance_id": span.utterance_id,
                    "start": span.start,
                    "end": span.end,
                }
                for span in body.utterance_spans
            ],
        },
    )
    return {"status": "ok"}


@router.post("/fail/{job_id}")
async def fail_job(job_id: int, body: JobError):
    await db.fail_transcription_job(job_id, body.error)
    return {"status": "ok"}


@router.get("/status")
async def worker_status():
    return {"status": "ok"}
