"""Standalone HTTP-polling transcription worker."""

from __future__ import annotations

import asyncio
import base64
import logging
import os

import httpx
from fastapi import FastAPI

from audio import concatenate_segments
from pipeline import load_models, transcribe_audio

logger = logging.getLogger("transcription-worker")
SERVER_URL = os.getenv("SERVER_URL", "http://server:8443").rstrip("/")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "5"))
models = {}
_poll_task: asyncio.Task | None = None

app = FastAPI(title="LifeLog transcription worker")


@app.get("/health")
async def health():
    return {"status": "ok", "models_loaded": bool(models)}


async def _post_stage(client: httpx.AsyncClient, job_id: int, stage: str) -> None:
    response = await client.post(f"{SERVER_URL}/internal/transcription/stage/{job_id}", json={"stage": stage})
    response.raise_for_status()


async def _process_job(client: httpx.AsyncClient, job: dict) -> None:
    job_id = job["job_id"]
    job_type = job.get("job_type", "full")
    language = job.get("language", "auto")
    if language == "auto":
        language = None
    audio_response = await client.get(f"{SERVER_URL}/internal/transcription/audio/{job_id}")
    audio_response.raise_for_status()
    payload = audio_response.json()
    audio_segments = [base64.b64decode(value) for value in payload["audio_segments"]]
    if job_type == "quick":
        # Use timestamps from payload for proper offset-based concatenation
        timestamps = payload.get("timestamps") or [job["window_start"]]
        audio_np, sample_rate = concatenate_segments(audio_segments, timestamps)
        complete = transcribe_audio(models, audio_np, sample_rate, language=language)
    else:
        await _post_stage(client, job_id, "concatenating")
        audio_np, sample_rate = concatenate_segments(audio_segments, payload["timestamps"])
        await _post_stage(client, job_id, "transcribing")
        await _post_stage(client, job_id, "diarizing")
        complete = transcribe_audio(models, audio_np, sample_rate, language=language)
        await _post_stage(client, job_id, "done")
    response = await client.post(
        f"{SERVER_URL}/internal/transcription/complete/{job_id}", json=complete
    )
    response.raise_for_status()


async def poll_once(client: httpx.AsyncClient) -> bool:
    response = await client.post(f"{SERVER_URL}/internal/transcription/claim")
    if response.status_code == 204:
        return False
    response.raise_for_status()
    job = response.json()
    try:
        await _process_job(client, job)
    except Exception as exc:
        logger.exception("Transcription job %s failed", job.get("job_id"))
        try:
            failed = await client.post(
                f"{SERVER_URL}/internal/transcription/fail/{job['job_id']}",
                json={"error": str(exc)},
            )
            failed.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Unable to report transcription job %s failure", job.get("job_id"))
    return True


async def _poll_loop() -> None:
    limits = httpx.Limits(
        max_keepalive_connections=2,
        keepalive_expiry=max(1.0, POLL_INTERVAL - 1.0),
    )
    async with httpx.AsyncClient(timeout=300, limits=limits) as http_client:
        while True:
            try:
                await poll_once(http_client)
            except httpx.HTTPError:
                logger.exception("Transcription worker server transport failure")
            except Exception:
                logger.exception("Transcription worker poll failure")
            await asyncio.sleep(POLL_INTERVAL)


@app.on_event("startup")
async def startup() -> None:
    global models, _poll_task
    models = load_models()
    _poll_task = asyncio.create_task(_poll_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    if _poll_task is not None:
        _poll_task.cancel()
        await asyncio.gather(_poll_task, return_exceptions=True)
