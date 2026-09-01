import asyncio
import json
import logging
import logging.config
import time
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from lifelog.config import settings
from lifelog.database import init_pool
from lifelog.rate_limit import limiter
from lifelog.routes import dashboard, speakers, transcription, upload
from lifelog.worker import hourly_reprocess_loop, worker_loop

logger = structlog.get_logger()
_worker_task = None
_hourly_task = None


def _configure_logging() -> None:
    """Load logging.json config and configure structlog."""
    config_path = Path(__file__).resolve().parent.parent.parent / "logging.json"
    if config_path.exists():
        with open(config_path) as f:
            log_config = json.load(f)
        logging.config.dictConfig(log_config)

    # Bridge structlog into stdlib handlers so lifelog's structured logs
    # flow through the existing dictConfig stdout handler.
    stdlib_handler = logging.StreamHandler()
    stdlib_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
            ],
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root_logger = logging.getLogger()
    root_logger.addHandler(stdlib_handler)
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.to_log_record,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker_task, _hourly_task

    _configure_logging()

    # Initialize DB pool (migrations already ran in entrypoint)
    await init_pool()

    logger.info("server_started")
    logger.info(
        "config_loaded",
        speaker_id=settings.speaker_id_url,
        llm_base=settings.openai_base_url,
        llm_model=settings.openai_model,
    )

    try:
        _worker_task = asyncio.create_task(worker_loop())
        logger.info("worker_started")
    except Exception:
        logger.exception("worker_start_failed")

    try:
        _hourly_task = asyncio.create_task(hourly_reprocess_loop())
        logger.info("hourly_loop_started")
    except Exception:
        logger.exception("hourly_loop_start_failed")
    yield

    for task in (_worker_task, _hourly_task):
        if task is not None:
            task.cancel()
    await asyncio.gather(
        *[task for task in (_worker_task, _hourly_task) if task is not None],
        return_exceptions=True,
    )


app = FastAPI(title="LifeLog", lifespan=lifespan)

# Rate limiting (shared instance from lifelog.rate_limit)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    return response


@app.get("/health")
@limiter.exempt
async def health():
    return {"status": "ok"}


# CORS — restrict origins to configured dashboard origin(s)
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

app.include_router(upload.router, prefix="/api/v1", tags=["upload"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(speakers.router, prefix="/api/v1/speakers", tags=["speakers"])
app.include_router(
    transcription.router, prefix="/internal/transcription", tags=["transcription"]
)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
