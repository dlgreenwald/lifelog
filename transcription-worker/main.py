"""Standalone HTTP-polling transcription worker."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import threading
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict

from audio import concatenate_segments, concatenate_segments_with_spans
from pipeline import transcribe_audio  # load_models called via model_manager.load()

logger = logging.getLogger("transcription-worker")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

SERVER_URL = os.getenv("SERVER_URL", "http://server:8443").rstrip("/")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "5"))
_poll_task: asyncio.Task | None = None


def _cuda_allocated_mib() -> int:
    """Return CUDA allocated bytes in MiB for watchdog diagnostics. Falls
    back to 0 if CUDA is not available."""
    try:
        import torch
        if torch.cuda.is_available():
            return int(torch.cuda.memory_allocated() / 1024 / 1024)
    except Exception as e:
        logger.debug("Could not get CUDA memory: %s", e)
    return 0


class Settings(BaseSettings):
    idle_unload_seconds: int = 300  # 0 disables unloading; matches speaker-id default
    warm_keepalive_seconds: int = (
        60  # additional time to wait after idle_unload before unloading
    )
    idle_process_restart_seconds: int = 900  # 0 disables; exit-after-unload safety net

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()


class ModelManager:
    def __init__(self):
        self._models: dict = {}
        # RLock so that begin_job (which holds the lock) can safely
        # nest inside load() / get_models() / shutdown() which also use
        # the same lock — preventing the watchdog from unloading while
        # a job is loading models.
        self._lock = threading.RLock()
        self._last_activity = time.time()
        self._active_jobs = 0  # count of jobs currently being processed
        self._watchdog_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._watchdog_interval = 30
        self._start_watchdog()

    def _start_watchdog(self):
        def watchdog_loop():
            while not self._stop_event.wait(self._watchdog_interval):
                self._check_idle()

        self._watchdog_thread = threading.Thread(
            target=watchdog_loop, daemon=True, name="tw-watchdog"
        )
        self._watchdog_thread.start()
        logger.info(
            "Idle-unload watchdog started (interval=%ds, idle_timeout=%ds, warm_keepalive=%ds)",
            self._watchdog_interval,
            settings.idle_unload_seconds,
            settings.warm_keepalive_seconds,
        )

    def _check_idle(self):
        if settings.idle_unload_seconds == 0:
            return
        with self._lock:
            # Re-check _active_jobs under lock — begin_job() now
            # increments under the same lock, so this is authoritative
            # and prevents the race where a job arrives between the
            # out-of-lock check above and the lock acquisition here.
            if self._active_jobs > 0:
                return
            idle = time.time() - self._last_activity
            threshold = settings.idle_unload_seconds + settings.warm_keepalive_seconds
            if idle < threshold:
                return
            # First-stage: in-process unload. Drops ASR/align/diarize
            # models and releases most cached GPU blocks via
            # ``gc.collect`` + ``torch.cuda.empty_cache`` (see
            # ``pipeline.unload_models``). Keeps an extra ~400 MiB
            # baseline pinned by CTranslate2 / pyannote internals
            # that no in-process reclaim can free.
            if self._models:
                logger.info(
                    "Models idle for %.1fs (timeout=%ds), "
                    "keys before unload=%d, cuda_allocated=%dMiB, unloading",
                    idle,
                    settings.idle_unload_seconds,
                    len(self._models),
                    _cuda_allocated_mib(),
                )
                from pipeline import unload_models

                try:
                    unload_models(self._models)
                except Exception as exc:
                    logger.error(
                        "unload_models raised %s — forcing restart to "
                        "recover CUDA state: %s",
                        type(exc).__name__,
                        exc,
                    )
                    import os as _os

                    _os._exit(1)
                logger.info(
                    "Models unloaded — keys after=%d, cuda_allocated=%dMiB",
                    len(self._models),
                    _cuda_allocated_mib(),
                )
            # Second-stage: process restart. If idleness exceeds
            # ``idle_process_restart_seconds`` AND unload has run at
            # least once, raise SystemExit so docker-compose's
            # ``restart: unless-stopped`` policy resurrects the
            # container with a fully reclaimed GPU. ``os._exit`` is
            # used so atexit handlers / FastAPI shutdown hooks do
            # not hang on the CTranslate2 + pyannote ``__del__``
            # chain (which is what is keeping GPU pinned).
            restart_threshold = int(settings.idle_process_restart_seconds or 0)
            if restart_threshold > 0 and idle >= restart_threshold:
                logger.warning(
                    "Idle for %.1fs exceeds restart threshold %ds — "
                    "exiting so container can be resurrected and "
                    "release pinned GPU memory",
                    idle,
                    restart_threshold,
                )
                # os._exit prevents dangling CTranslate2 / pyannote
                # __del__ chains from holding the shutdown open.
                import os as _os

                _os._exit(0)

    def load(self) -> dict:
        """Load models, acquiring the lock. Updates last_activity."""
        with self._lock:
            self._last_activity = time.time()
            if not self._models:
                from pipeline import load_models as _load

                try:
                    self._models = _load()
                    logger.info("WhisperX models loaded")
                except Exception:
                    self._models = {}
                    raise
            return self._models

    def get_models(self) -> dict:
        """Get the current models dict without reloading. Thread-safe."""
        with self._lock:
            return self._models

    def record_activity(self):
        """Call on each job claim to reset idle timer."""
        self._last_activity = time.time()

    def begin_job(self):
        # Hold the lock so the watchdog's re-check inside _check_idle
        # (also under the same lock) sees _active_jobs > 0 and skips
        # the unload.  The lock is reentrant (RLock) so nested
        # acquisition from load() / get_models() / shutdown() is safe.
        with self._lock:
            self._active_jobs += 1

    def end_job(self):
        with self._lock:
            self._active_jobs -= 1

    def shutdown(self):
        self._stop_event.set()
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=5)
        with self._lock:
            if self._models:
                from pipeline import unload_models

                unload_models(self._models)
                logger.info("ModelManager shut down")


model_manager = ModelManager()

app = FastAPI(title="LifeLog transcription worker")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "models_loaded": bool(model_manager.get_models()),
        "last_activity": model_manager._last_activity,
    }


async def _post_stage(client: httpx.AsyncClient, job_id: int, stage: str) -> None:
    response = await client.post(
        f"{SERVER_URL}/internal/transcription/stage/{job_id}", json={"stage": stage}
    )
    response.raise_for_status()


async def _process_job(client: httpx.AsyncClient, job: dict) -> None:
    job_id = job["job_id"]
    job_type = job.get("job_type", "full")
    language = job.get("language", "auto")
    if language == "auto":
        language = None
    audio_response = await client.get(
        f"{SERVER_URL}/internal/transcription/audio/{job_id}"
    )
    audio_response.raise_for_status()
    payload = audio_response.json()
    audio_segments = [base64.b64decode(value) for value in payload["audio_segments"]]
    # Fallback: if utterance_ids not in job result (overwritten by prior run), try audio response
    utterance_ids = (job.get("result") or {}).get("utterance_ids") or []
    if not utterance_ids and "utterance_ids" in payload:
        utterance_ids = payload["utterance_ids"]
    model_manager.begin_job()
    model_manager.record_activity()
    try:
        models = model_manager.load()
        if job_type == "quick":
            # Quick jobs run ASR+align+diarization over a per-utterance
            # concatenation; emit combined-stream spans alongside the
            # segments so the server can map each segment back to the
            # utterance that produced it without re-deriving offsets
            # from wall-clock timestamps.
            timestamps = payload.get("timestamps") or [job["window_start"]]
            audio_np, sample_rate, spans = concatenate_segments_with_spans(
                audio_segments, timestamps
            )
            complete = transcribe_audio(
                models, audio_np, sample_rate, language=language
            )
            complete["utterance_spans"] = [
                {
                    "utterance_id": utterance_ids[i],
                    "start": round(spans[i][0], 6),
                    "end": round(spans[i][1], 6),
                }
                for i in range(min(len(spans), len(utterance_ids)))
            ]
            # Preserve utterance_ids in result so apply loop can find them
            complete["utterance_ids"] = utterance_ids
        else:
            await _post_stage(client, job_id, "concatenating")
            audio_np, sample_rate = concatenate_segments(
                audio_segments, payload["timestamps"]
            )
            await _post_stage(client, job_id, "transcribing")
            await _post_stage(client, job_id, "diarizing")
            complete = transcribe_audio(
                models, audio_np, sample_rate, language=language
            )
            complete["utterance_spans"] = []
            await _post_stage(client, job_id, "done")
        response = await client.post(
            f"{SERVER_URL}/internal/transcription/complete/{job_id}", json=complete
        )
        response.raise_for_status()
    except Exception:
        logger.exception("transcription_failed job_id=%d", job_id)
        try:
            await client.post(
                f"{SERVER_URL}/internal/transcription/fail/{job_id}", json={}
            )
        except Exception:
            logger.exception("failed_to_mark_job_failed job_id=%d", job_id)
        raise
    finally:
        model_manager.end_job()


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
            logger.exception(
                "Unable to report transcription job %s failure", job.get("job_id")
            )
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: do not preload — let idle mechanism handle first load
    _poll_task_local = asyncio.create_task(_poll_loop())
    globals()["_poll_task"] = _poll_task_local
    try:
        yield
    finally:
        # Shutdown: cancel poll task, then unload models
        if _poll_task_local is not None:
            _poll_task_local.cancel()
            await asyncio.gather(_poll_task_local, return_exceptions=True)
        model_manager.shutdown()


app.router.lifespan_context = lifespan
