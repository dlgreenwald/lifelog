import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from lifelog.config import settings
from lifelog.database import init_pool
from lifelog.routes import dashboard, speakers, upload
from lifelog.worker import worker_loop

logger = logging.getLogger("lifelog")
_worker_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker_task

    # Configure logging after uvicorn starts (alembic reconfigured it)
    LOG_LEVEL = getattr(logging, settings.log_level.upper(), logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    for name in ["lifelog", "lifelog.transcribe", "lifelog.speaker_id",
                 "lifelog.llm", "lifelog.upload", "lifelog.worker",
                 "lifelog.speakers", "lifelog.dashboard"]:
        log = logging.getLogger(name)
        log.handlers.clear()
        log.addHandler(handler)
        log.setLevel(LOG_LEVEL)

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
