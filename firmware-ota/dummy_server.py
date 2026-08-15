"""
Dummy LifeLog server for smoke testing firmware uploads.
Mimics the real server's upload endpoint signature.
Use --save flag to save uploaded files to ./uploads/
"""
import os
import sys
import time
from fastapi import FastAPI, File, UploadFile, Header, HTTPException
from fastapi.responses import JSONResponse

SAVE_FILES = "--save" in sys.argv
UPLOAD_DIR = "uploads"

if SAVE_FILES:
    os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="LifeLog Dummy Server")

API_KEYS = {
    "test-api-key-1234": {"id": 1, "name": "Test Device"},
    "lifelog-key": {"id": 2, "name": "LifeLog Device"},
}


@app.get("/")
async def root():
    return {"status": "ok", "message": "LifeLog Dummy Server", "save_files": SAVE_FILES}


@app.post("/api/v1/upload")
async def upload_audio(
    file: UploadFile = File(...),
    x_api_key: str = Header(...),
):
    user = API_KEYS.get(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")

    audio_bytes = await file.read()

    if SAVE_FILES:
        import os
        basename = os.path.basename(file.filename or f"{int(time.time())}.opus")
        filepath = os.path.join(UPLOAD_DIR, basename)
        with open(filepath, "wb") as f:
            f.write(audio_bytes)
        print(f"[UPLOAD] {user['name']}: {file.filename} ({len(audio_bytes)} bytes) -> saved")
    else:
        print(f"[UPLOAD] {user['name']}: {file.filename} ({len(audio_bytes)} bytes)")

    return JSONResponse(
        content={"status": "processed", "recording_id": hash(str(time.time())) % 100000},
        status_code=200,
    )


if __name__ == "__main__":
    import uvicorn
    mode = "SAVE mode" if SAVE_FILES else "log-only mode"
    print(f"LifeLog Dummy Server on http://0.0.0.0:8443 ({mode})")
    print("Usage: python dummy_server.py [--save]")
    uvicorn.run(app, host="0.0.0.0", port=8443)
