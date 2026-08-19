import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from lifelog.config import settings
from lifelog.database import init_pool
from lifelog.routes import dashboard, speakers, upload
from lifelog.worker import daily_reprocess_loop, hourly_reprocess_loop, worker_loop

logger = logging.getLogger("lifelog")
_worker_task = None
_hourly_task = None
_daily_task = None


def _configure_logging() -> None:
    """Load logging.json and apply per-level overrides from settings."""
    config_path = Path(__file__).resolve().parent.parent.parent / "logging.json"
    if config_path.exists():
        with open(config_path) as f:
            log_config = json.load(f)
        LOG_LEVEL = getattr(logging, settings.log_level.upper(), logging.INFO)
        for logger_cfg in log_config.get("loggers", {}).values():
            logger_cfg["level"] = LOG_LEVEL
        logging.config.dictConfig(log_config)
    else:
        logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker_task, _hourly_task, _daily_task

    _configure_logging()

    # Initialize DB pool (migrations already ran in entrypoint)
    await init_pool()

    logger.info("Starting LifeLog server")
    logger.info(
        "Config: whisper_asr=%s, speaker_id=%s, llm=%s/%s",
        settings.whisper_asr_url,
        settings.speaker_id_url,
        settings.openai_base_url,
        settings.openai_model,
    )

    try:
        _worker_task = asyncio.create_task(worker_loop())
        logger.info("Background worker started")
    except Exception:
        logger.exception("Failed to start worker")

    try:
        _hourly_task = asyncio.create_task(hourly_reprocess_loop())
        logger.info("Hourly reprocess loop started")
    except Exception:
        logger.exception("Failed to start hourly reprocess loop")

    try:
        _daily_task = asyncio.create_task(daily_reprocess_loop())
        logger.info("Daily reprocess loop started")
    except Exception:
        logger.exception("Failed to start daily reprocess loop")

    yield


app = FastAPI(title="LifeLog", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    logger.info(
        "%s %s → %d (%.0fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(upload.router, prefix="/api/v1", tags=["upload"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(speakers.router, prefix="/api/v1/speakers", tags=["speakers"])
app.mount("/", StaticFiles(directory="static", html=True), name="static")
