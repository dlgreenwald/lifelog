"""
Dummy LifeLog server for smoke testing firmware uploads.
Mimics the real server's upload endpoint signature with utterance chunk support.
Use --save flag to save uploaded files to ./uploads/
"""
import os
import sys
import time
import logging
import traceback
from fastapi import FastAPI, File, Form, UploadFile, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

SAVE_FILES = "--save" in sys.argv
UPLOAD_DIR = "uploads"

if SAVE_FILES:
    os.makedirs(UPLOAD_DIR, exist_ok=True)

# Configure structured logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("dummy-server")

app = FastAPI(title="LifeLog Dummy Server")


def _safe_path(value: str) -> str:
    """Escape log injection chars from user-supplied strings."""
    return value.replace("%", "%%").replace("\n", "\\0") if isinstance(value, str) else value


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.error(
                "request_exception",
                method=request.method,
                path=_safe_path(request.url.path),
                elapsed_ms=elapsed_ms,
                error=str(e),
                exc_info=True,
            )
            return JSONResponse(status_code=500, content={"detail": "Internal server error"})
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "request_complete",
            method=request.method,
            path=_safe_path(request.url.path),
            status=response.status_code,
            elapsed_ms=elapsed_ms,
        )
        return response


app.add_middleware(RequestLoggingMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    logger.warning(
        "validation_error",
        method=request.method,
        path=_safe_path(request.url.path),
        errors=exc.errors(),
    )
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    logger.warning(
        "http_error",
        method=request.method,
        path=_safe_path(request.url.path),
        status_code=exc.status_code,
        detail=exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(
        "unhandled_exception",
        method=request.method,
        path=_safe_path(request.url.path),
        error=str(exc),
        traceback=traceback.format_exc(),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/")
async def root():
    return {"status": "ok", "message": "LifeLog Dummy Server", "save_files": SAVE_FILES}


@app.post("/api/v1/upload")
async def upload_audio(
    file: UploadFile = File(...),
    utterance_id: int = Form(...),
    chunk_index: int = Form(...),
    is_final: bool = Form(...),
    x_api_key: str = Header(...),
):
    user = {"id": 1, "name": "Device"}
    filename = file.filename or f"chunk_{chunk_index}.opus"

    logger.info(
        "upload_start",
        utterance_id=utterance_id,
        chunk_index=chunk_index,
        is_final=is_final,
        filename=_safe_path(filename),
        content_type=file.content_type,
    )

    try:
        audio_bytes = await file.read()
    except Exception as e:
        logger.error("upload_read_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Read failed")

    logger.info(
        "upload_read",
        utterance_id=utterance_id,
        chunk_index=chunk_index,
        byte_count=len(audio_bytes),
    )

    if SAVE_FILES:
        utt_dir = os.path.join(UPLOAD_DIR, f"user{user['id']}_utt{utterance_id}")
        # Guard: resolve path and verify it stays within UPLOAD_DIR
        real_utt_dir = os.path.realpath(utt_dir)
        if not real_utt_dir.startswith(os.path.realpath(UPLOAD_DIR) + os.sep):
            raise ValueError("path escape attempt")
        utt_dir = real_utt_dir  # Use resolved path for all operations
        try:
            os.makedirs(utt_dir, exist_ok=True)
            basename = os.path.basename(filename)
            if ".." in basename or basename.startswith("/"):
                raise ValueError("bad basename")
            chunk_path = os.path.join(utt_dir, f"chunk{chunk_index:03d}_{basename}")
            # Assert chunk_path stays within utt_dir
            if not os.path.realpath(chunk_path).startswith(utt_dir + os.sep):
                raise ValueError("path escape in chunk_path")
            with open(chunk_path, "wb") as f:
                f.write(audio_bytes)
            logger.info(
                "upload_saved",
                utterance_id=utterance_id,
                chunk_index=chunk_index,
                path=chunk_path,
                byte_count=len(audio_bytes),
            )
        except Exception as e:
            logger.error("upload_save_failed", error=str(e), exc_info=True)
            raise HTTPException(status_code=500, detail="Save failed")

    if not is_final:
        logger.debug(
            "upload_chunk_pending",
            utterance_id=utterance_id,
            chunk_index=chunk_index,
        )
        return JSONResponse(
            content={
                "status": "chunk_stored",
                "utterance_id": utterance_id,
                "chunk_index": chunk_index,
            },
            status_code=200,
        )

    # Utterance complete
    if SAVE_FILES:
        utt_dir = os.path.join(UPLOAD_DIR, f"user{user['id']}_utt{utterance_id}")
        real_utt_dir = os.path.realpath(utt_dir)
        if not real_utt_dir.startswith(os.path.realpath(UPLOAD_DIR) + os.sep):
            raise ValueError("path escape attempt")
        utt_dir = real_utt_dir
        chunk_count = len([f for f in os.listdir(utt_dir) if f.startswith("chunk")])
        logger.info(
            "upload_complete",
            utterance_id=utterance_id,
            chunk_count=chunk_count,
            dir=utt_dir,
        )

    return JSONResponse(
        content={"status": "processed", "utterance_id": utterance_id},
        status_code=200,
    )


if __name__ == "__main__":
    import uvicorn

    mode = "SAVE mode" if SAVE_FILES else "log-only mode"
    logger.info("server_starting", host="0.0.0.0", port=8444, mode=mode)
    logger.info("server_usage", note="python dummy_server.py [--save]")
    uvicorn.run(app, host="0.0.0.0", port=8444, log_level="warning")
