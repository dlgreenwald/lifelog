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


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception as e:
            logger.exception("Unhandled exception in request: %s", request.url.path)
            return JSONResponse(status_code=500, content={"detail": "Internal server error"})
        elapsed_ms = (time.monotonic() - start) * 1000
        safe_path = request.url.path.replace("%", "%25").replace("\n", "%0A")
        logger.info(
            "%s %s → %d (%.1fms)",
            request.method,
            safe_path,
            response.status_code,
            elapsed_ms,
        )
        return response


app.add_middleware(RequestLoggingMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    logger.warning(
        "VALIDATION ERROR: %s %s → 422: %s",
        request.method, request.url.path, exc.errors(),
    )
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    logger.warning(
        "HTTP ERROR: %s %s → %d: %s",
        request.method, request.url.path, exc.status_code, exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(
        "UNHANDLED: %s %s → 500: %s\n%s",
        request.method, request.url.path, exc, traceback.format_exc(),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
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
        "UPLOAD START: utt=%d chunk=%d final=%s file=%s key=%s content_type=%s",
        utterance_id, chunk_index, is_final, filename, x_api_key[:8] + "...",
        file.content_type,
    )

    try:
        audio_bytes = await file.read()
    except Exception as e:
        logger.error("Failed to read upload body: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Read failed: {e}")

    logger.info(
        "UPLOAD READ: utt=%d chunk=%d %d bytes",
        utterance_id, chunk_index, len(audio_bytes),
    )

    if SAVE_FILES:
        utt_dir = os.path.join(UPLOAD_DIR, f"user{user['id']}_utt{utterance_id}")
        try:
            os.makedirs(utt_dir, exist_ok=True)
            basename = os.path.basename(filename)
            if ".." in basename or basename.startswith("/"):
                raise ValueError("bad basename")
            chunk_path = os.path.normpath(os.path.join(utt_dir, f"chunk{chunk_index:03d}_{basename}"))
            if not chunk_path.startswith(utt_dir):
                raise ValueError("path escape attempt")
            with open(chunk_path, "wb") as f:
                f.write(audio_bytes)
            logger.info(
                "UPLOAD SAVED: utt=%d chunk=%d → %s (%d bytes)",
                utterance_id, chunk_index, chunk_path, len(audio_bytes),
            )
        except Exception as e:
            logger.error("Failed to save file: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Save failed: {e}")

    if not is_final:
        logger.debug("UPLOAD CHUNK-ONLY: utt=%d chunk=%d (waiting for more)", utterance_id, chunk_index)
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
        safe_utt_id = str(utterance_id).replace("/", "_").replace("..", "_")
        utt_dir = os.path.join(UPLOAD_DIR, f"user{user['id']}_utt{safe_utt_id}")
        # Guard: resolve and verify the path stays within UPLOAD_DIR
        real_utt_dir = os.path.realpath(utt_dir)
        if not real_utt_dir.startswith(os.path.realpath(UPLOAD_DIR) + os.sep):
            raise ValueError("path escape attempt")
        utt_dir = real_utt_dir  # Use the resolved path for all filesystem operations
        os.makedirs(utt_dir, exist_ok=True)
        chunk_count = len([f for f in os.listdir(utt_dir) if f.startswith("chunk")])
        logger.info(
            "UPLOAD COMPLETE: utt=%d → %d chunks in %s",
            utterance_id, chunk_count, utt_dir,
        )
    return JSONResponse(
        content={"status": "processed", "utterance_id": utterance_id},
        status_code=200,
    )


if __name__ == "__main__":
    import uvicorn

    mode = "SAVE mode" if SAVE_FILES else "log-only mode"
    logger.info("Starting LifeLog Dummy Server on http://0.0.0.0:8444 (%s)", mode)
    logger.info("Usage: python dummy_server.py [--save]")
    uvicorn.run(app, host="0.0.0.0", port=8444, log_level="warning")
