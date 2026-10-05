"""Standalone HTTP-polling transcription worker."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import threading
import time
from contextlib import asynccontextmanager

import httpx
import numpy as np
import soundfile as sf
import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic_settings import BaseSettings, SettingsConfigDict

from audio import concatenate_segments, concatenate_segments_with_spans
from pipeline import (  # load_models called via model_manager.load()
    release_gpu_cache,
    transcribe_audio,
)

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=False,
)
logger = structlog.get_logger()

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


def _spectral_flatness(audio: np.ndarray) -> float:
    """Compute spectral flatness: geometric_mean / arithmetic_mean of power spectrum.

    - ~0.0 = pure tone / structured (speech formants)
    - ~1.0 = white/pink noise (impulsive, click-like)
    - Speech typically: 0.1–0.4
    - Clicks/transients: 0.5–1.0
    """
    if len(audio) < 64:
        return 1.0
    windowed = audio * np.hanning(len(audio))
    fft = np.fft.rfft(windowed)
    power = np.abs(fft) ** 2
    power = power[power > 1e-12]  # avoid log(0)
    if len(power) == 0:
        return 1.0
    geometric_mean = np.exp(np.mean(np.log(power)))
    arithmetic_mean = np.mean(power)
    return geometric_mean / arithmetic_mean if arithmetic_mean > 1e-12 else 1.0


def _chunk_impulsive(audio_np: np.ndarray, sr: int) -> bool:
    """Return True if the audio chunk appears to be an impulsive transient, not real speech.

    Clicks and pops are broadband impulses: high spectral flatness (~0.6–1.0).
    Real speech has formant structure: low spectral flatness (~0.1–0.4).

    For longer chunks (>1s) we check the most-energetic 300ms window to avoid
    averaging across silence/pauses in real speech.
    """
    FLATNESS_THRESHOLD = 0.55

    duration = len(audio_np) / sr
    if duration <= 1.0:
        flatness = _spectral_flatness(audio_np)
    else:
        # Find the most-energetic 300ms window
        window_size = int(0.3 * sr)
        step = window_size // 4
        best_rms = -np.inf
        best_window = audio_np[:window_size]
        for i in range(0, len(audio_np) - window_size + 1, step):
            window = audio_np[i : i + window_size]
            rms = float(np.mean(window**2))
            if rms > best_rms:
                best_rms = rms
                best_window = window
        flatness = _spectral_flatness(best_window)

    return flatness > FLATNESS_THRESHOLD


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

    def clear_align_cache(self):
        """Drop per-language alignment models to free GPU memory.

        The _align_cache dict holds wav2vec2 alignment models loaded lazily
        for each detected non-default language.  These are loaded onto the GPU
        and accumulate without bound across jobs.  Clearing the cache after
        each job prevents memory growth while leaving the primary ASR and
        diarization models untouched, so subsequent jobs do not need a full
        model reload.
        """
        with self._lock:
            cache = self._models.get("_align_cache")
            if cache:
                cache.clear()

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


@app.websocket("/ws/instant/{session_id}")
async def ws_instant(websocket: WebSocket, session_id: int):
    """Receive Opus audio from server, transcribe with faster-whisper, stream partial results.

    Uses the existing model_manager (same GPU context and model weights as finalize-path jobs).
    Server sends compressed Opus bytes; transcription-worker decodes internally via soundfile.
    Partial transcripts sent as JSON:
        {"type": "segment", "segments": [{start, end, text}, ...]}
    """
    await websocket.accept()
    model_manager.record_activity()
    import time

    # Per-session language cache — detect once, reuse for all subsequent utterances
    session_language: str | None = os.getenv("INSTANT_ASR_LANGUAGE") or None

    try:
        while True:
            opus_data = await websocket.receive_bytes()
            model_manager.begin_job()
            model_manager.record_activity()
            chunk_start = time.monotonic()
            try:
                # Decode Opus/OGG to float32 numpy via soundfile (in-process, no subprocess)
                audio_np, sr = sf.read(io.BytesIO(opus_data), dtype="float32")
                audio_duration_s = len(audio_np) / sr if sr else 0.0

                # Audio metrics (float32 normalized to [-1.0, 1.0])
                decoded_samples = 0
                audio_max_abs = 0.0
                audio_mean = 0.0
                if audio_np.size > 0:
                    decoded_samples = audio_np.size
                    audio_max_abs = float(np.max(np.abs(audio_np)))
                    audio_mean = float(np.mean(audio_np.astype(np.float64)))
                    rms = float(np.sqrt(np.mean(audio_np.astype(np.float64) ** 2)))
                    rms_dbfs = (20 * np.log10(rms)) if rms > 0 else -96.0
                    peak = float(np.max(np.abs(audio_np)))
                    peak_dbfs = (20 * np.log10(peak)) if peak > 0 else -96.0
                    clipping_samples = int(np.sum(np.abs(audio_np) > 0.99))
                    clipping_pct = round(100 * clipping_samples / audio_np.size, 2)
                else:
                    rms_dbfs = peak_dbfs = -96.0
                    clipping_pct = 0.0

                logger.debug(
                    "instant_audio_received",
                    session_id=session_id,
                    audio_duration_s=round(audio_duration_s, 2),
                    decoded_samples=decoded_samples,
                    sample_rate=sr,
                    audio_max_abs=round(audio_max_abs, 6),
                    audio_mean=round(audio_mean, 6),
                    rms_dbfs=round(rms_dbfs, 1),
                    peak_dbfs=round(peak_dbfs, 1),
                    clipping_pct=clipping_pct,
                )

                # Guard against Whisper hallucinating on near-silence.
                # Silent audio (rms_dbfs < -70) is rejected before hitting the ASR model.
                # This prevents the common faster-whisper artefact of producing
                # "Thank you" / "Thanks" on dead-air chunks.
                SILENCE_RMS_DBFS_THRESHOLD = -70.0
                SILENCE_MAX_DURATION_S = 3.0
                if (
                    rms_dbfs < SILENCE_RMS_DBFS_THRESHOLD
                    and audio_duration_s < SILENCE_MAX_DURATION_S
                ):
                    logger.info(
                        "instant_silence_rejected",
                        session_id=session_id,
                        audio_duration_s=round(audio_duration_s, 2),
                        decoded_samples=decoded_samples,
                        sample_rate=sr,
                        audio_max_abs=round(audio_max_abs, 6),
                        rms_dbfs=round(rms_dbfs, 1),
                    )
                    # Tell the server this utterance is silent so it can:
                    # - Skip inserting into session_utterances (preserves gap detection)
                    # - Skip starting/continuing a session with silence
                    await websocket.send_json(
                        {"type": "segment", "segments": [], "is_silent": True}
                    )
                    model_manager.end_job()
                    continue

                # Guard: short audio chunks (<1s) are unreliable for instant transcription —
                # both false positives ("Thank you") and true negatives (silence) cluster below
                # this threshold. The chunk is still streamed for final transcription; we just
                # don't show it live.
                if audio_duration_s < 1.0:
                    logger.info(
                        "instant_short_chunk_rejected",
                        session_id=session_id,
                        audio_duration_s=round(audio_duration_s, 2),
                        decoded_samples=decoded_samples,
                        sample_rate=sr,
                        audio_max_abs=round(audio_max_abs, 6),
                        rms_dbfs=round(rms_dbfs, 1),
                        peak_dbfs=round(peak_dbfs, 1),
                    )
                    await websocket.send_json(
                        {"type": "segment", "segments": [], "is_silent": False}
                    )
                    model_manager.end_job()
                    continue

                # Get the already-loaded faster-whisper model
                models = model_manager.get_models()
                whisper_model = models.get("asr") if models else None
                if not whisper_model:
                    # Models not loaded yet — load now (triggers watchdog keepalive)
                    models = model_manager.load()
                    whisper_model = models.get("asr")

                if not whisper_model:
                    raise RuntimeError("ASR model not available after load")

                # Sanity check: confirm decoded audio has real signal before wasting GPU cycles.
                # Catches soundfile Opus decode failures that silently produce zeros.
                if audio_max_abs < 1e-5:
                    logger.warning(
                        "instant_zero_audio_rejected",
                        session_id=session_id,
                        audio_duration_s=round(audio_duration_s, 2),
                        decoded_samples=decoded_samples,
                        sample_rate=sr,
                        audio_max_abs=audio_max_abs,
                        audio_mean=audio_mean,
                        rms_dbfs=round(rms_dbfs, 1),
                    )
                    await websocket.send_json(
                        {"type": "segment", "segments": [], "is_silent": True}
                    )
                    model_manager.end_job()
                    continue

                # Transcribe — use cached session language; detect on first utterance only
                segments = []
                transcript_error = None
                no_speech_prob = None
                avg_log_prob = None
                compression_ratio = None
                info_duration = None
                try:
                    result = whisper_model.transcribe(
                        audio_np,
                        language=session_language,
                    )
                    # whisperx may return a named tuple or dict depending on version
                    if hasattr(result, "get"):
                        segments = result.get("segments", []) if result else []
                    elif isinstance(result, (list, tuple)) and len(result) > 0:
                        first = result[0]
                        if isinstance(first, list):
                            segments = first
                        elif isinstance(first, dict):
                            segments = first.get("segments", [])
                        else:
                            segments = []
                    else:
                        segments = []

                    # Extract TranscriptionInfo diagnostics from the result tuple.
                    # faster-whisper returns (segments_generator, info) when word_timestamps
                    # is False (default). info contains no_speech_prob, avg_log_prob, etc.
                    # These fields help diagnose why Whisper returns empty segments.
                    if isinstance(result, tuple) and len(result) > 1:
                        info = result[1]
                        no_speech_prob = getattr(info, "no_speech_prob", None)
                        avg_log_prob = getattr(info, "avg_log_prob", None)
                        compression_ratio = getattr(info, "compression_ratio", None)
                        info_duration = getattr(info, "duration", None)

                    # Detect whether Whisper applied its combined no-speech rejection.
                    # Condition: no_speech_prob > 0.6 AND avg_log_prob < -1.0 simultaneously.
                    # If true, Whisper considers the audio silence even if it has energy.
                    whisper_rejected_as_silence = (
                        no_speech_prob is not None
                        and avg_log_prob is not None
                        and no_speech_prob > 0.6
                        and avg_log_prob < -1.0
                    )

                    logger.debug(
                        "instant_whisper_info",
                        session_id=session_id,
                        audio_duration_s=round(audio_duration_s, 2),
                        info_duration=round(info_duration, 2)
                        if info_duration
                        else None,
                        no_speech_prob=round(no_speech_prob, 4)
                        if no_speech_prob is not None
                        else None,
                        avg_log_prob=round(avg_log_prob, 4)
                        if avg_log_prob is not None
                        else None,
                        compression_ratio=round(compression_ratio, 4)
                        if compression_ratio is not None
                        else None,
                        segment_count=len(segments),
                        whisper_rejected_as_silence=whisper_rejected_as_silence,
                    )
                except Exception as e:
                    transcript_error = f"{type(e).__name__}: {e}"

                elapsed_s = time.monotonic() - chunk_start

                full_text = " ".join(
                    s["text"].strip() for s in segments if s.get("text", "").strip()
                )

                # Hallucination detection: compute spectral flatness to distinguish
                # impulsive transients (clicks/pops that fired device VAD) from real speech.
                # Flatness: ~0.0 = structured/speech, ~1.0 = impulsive/noise.
                # Impulsive chunks (clicks) tend to flatness > 0.55.
                chunk_flatness = round(_spectral_flatness(audio_np), 4)
                chunk_impulsive = _chunk_impulsive(audio_np, sr)

                # On first successful transcription, cache detected language for session
                if session_language is None and segments:
                    detected = None
                    if hasattr(result, "get"):
                        detected = result.get("language", None)
                    if (
                        not detected
                        and isinstance(result, (list, tuple))
                        and len(result) > 1
                    ):
                        second = result[1]
                        if isinstance(second, dict):
                            detected = second.get("language", None)
                    if detected:
                        session_language = detected
                        logger.info(
                            "instant_language_detected",
                            session_id=session_id,
                            language=detected,
                        )

                logger.info(
                    "instant_transcribe",
                    session_id=session_id,
                    audio_duration_s=round(audio_duration_s, 2),
                    decoded_samples=decoded_samples,
                    sample_rate=sr,
                    audio_max_abs=round(audio_max_abs, 6),
                    audio_mean=round(audio_mean, 6),
                    rms_dbfs=round(rms_dbfs, 1),
                    peak_dbfs=round(peak_dbfs, 1),
                    clipping_pct=clipping_pct,
                    segment_count=len(segments),
                    transcript=full_text[:500],
                    language=session_language or "auto",
                    elapsed_s=round(elapsed_s, 3),
                    rt_factor=round(audio_duration_s / elapsed_s, 2)
                    if elapsed_s > 0
                    else 0,
                    transcript_error=transcript_error,
                    chunk_flatness=chunk_flatness,
                    chunk_impulsive=chunk_impulsive,
                    # Whisper TranscriptionInfo diagnostics
                    no_speech_prob=round(no_speech_prob, 4)
                    if no_speech_prob is not None
                    else None,
                    avg_log_prob=round(avg_log_prob, 4)
                    if avg_log_prob is not None
                    else None,
                    compression_ratio=round(compression_ratio, 4)
                    if compression_ratio is not None
                    else None,
                    info_duration=round(info_duration, 2)
                    if info_duration is not None
                    else None,
                    whisper_rejected_as_silence=whisper_rejected_as_silence,
                )

                if transcript_error:
                    logger.warning(
                        "instant_transcribe_warning",
                        session_id=session_id,
                        audio_duration_s=round(audio_duration_s, 2),
                        decoded_samples=decoded_samples,
                        sample_rate=sr,
                        audio_max_abs=round(audio_max_abs, 6),
                        rms_dbfs=round(rms_dbfs, 1),
                        peak_dbfs=round(peak_dbfs, 1),
                        error=transcript_error,
                        chunk_flatness=chunk_flatness,
                        chunk_impulsive=chunk_impulsive,
                        no_speech_prob=round(no_speech_prob, 4)
                        if no_speech_prob is not None
                        else None,
                        avg_log_prob=round(avg_log_prob, 4)
                        if avg_log_prob is not None
                        else None,
                    )
                else:
                    await websocket.send_json(
                        {
                            "type": "segment",
                            "segments": [
                                {
                                    "start": s["start"],
                                    "end": s["end"],
                                    "text": s["text"],
                                }
                                for s in segments
                            ],
                            # Also flag as silent if Whisper ran but found no speech.
                            # This catches audio that passed the RMS guard but produced
                            # no transcript segments (e.g. very quiet real speech).
                            "is_silent": len(segments) == 0,
                        }
                    )
            except Exception as e:
                # Catch unexpected errors so the websocket stays open
                logger.error(
                    "instant_transcribe_error",
                    session_id=session_id,
                    audio_duration_s=round(audio_duration_s, 2)
                    if "audio_duration_s" in dir()
                    else None,
                    decoded_samples=decoded_samples
                    if "decoded_samples" in dir()
                    else None,
                    sample_rate=sr if "sr" in dir() else None,
                    audio_max_abs=round(audio_max_abs, 6)
                    if "audio_max_abs" in dir()
                    else None,
                    rms_dbfs=round(rms_dbfs, 1) if "rms_dbfs" in dir() else None,
                    peak_dbfs=round(peak_dbfs, 1) if "peak_dbfs" in dir() else None,
                    error=f"{type(e).__name__}: {e}",
                    chunk_flatness=chunk_flatness
                    if "chunk_flatness" in dir()
                    else None,
                    chunk_impulsive=chunk_impulsive
                    if "chunk_impulsive" in dir()
                    else None,
                )
            finally:
                model_manager.end_job()
    except WebSocketDisconnect:
        pass


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
    except Exception as exc:
        total_bytes = (
            sum(len(s) for s in audio_segments) if "audio_segments" in dir() else 0
        )
        logger.error(
            "transcription_failed",
            job_id=job_id,
            session_id=job.get("session_id"),
            job_type=job_type,
            language=language,
            audio_segment_count=len(audio_segments)
            if "audio_segments" in dir()
            else None,
            total_audio_bytes=total_bytes,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        try:
            await client.post(
                f"{SERVER_URL}/internal/transcription/fail/{job_id}",
                json={
                    "error": f"{type(exc).__name__}: {exc}",
                    "job_type": job_type,
                    "language": language,
                    "audio_segment_count": len(audio_segments)
                    if "audio_segments" in dir()
                    else None,
                    "total_audio_bytes": total_bytes,
                    "session_id": job.get("session_id"),
                },
            )
        except Exception:
            logger.exception("failed_to_mark_job_failed job_id=%d", job_id)
        raise
    finally:
        model_manager.end_job()
        # Post-job release: the allocator's full-session high-water mark
        # (~12 GiB on a 16 GiB card) would otherwise stay reserved until
        # process exit, starving speaker-id and ollama on the shared GPU.
        release_gpu_cache()
        logger.info(
            "gpu_cache_released job_id=%d allocated_mib=%d",
            job_id,
            _cuda_allocated_mib(),
        )


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
