"""
Dummy LifeLog server for smoke testing firmware uploads.
Mimics the real server's upload endpoint signature.
"""
import os
import time
from fastapi import FastAPI, File, UploadFile, Header, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="LifeLog Dummy Server")

# Fake API keys for testing
API_KEYS = {
    "test-api-key-1234": {"id": 1, "name": "Test Device"},
    "lifelog-key": {"id": 2, "name": "LifeLog Device"},
}

# Storage directory
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.get("/")
async def root():
    return {"status": "ok", "message": "LifeLog Dummy Server"}


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": time.time()}


@app.post("/api/v1/upload")
async def upload_audio(
    file: UploadFile = File(...),
    x_api_key: str = Header(...),
):
    """Accept Opus audio uploads from firmware devices."""
    # Validate API key
    user = API_KEYS.get(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Read audio data
    audio_bytes = await file.read()

    # Generate filename (use basename only)
    import os
    basename = os.path.basename(file.filename or "audio.opus")
    timestamp = int(time.time() * 1000)
    filename = f"{timestamp}_{user['id']}_{basename}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    # Save file
    with open(filepath, "wb") as f:
        f.write(audio_bytes)

    recording_id = hash(filename) % 100000

    print(f"[UPLOAD] Received from {user['name']}: {filename} ({len(audio_bytes)} bytes)")

    return JSONResponse(
        content={
            "status": "processed",
            "recording_id": recording_id,
            "filename": filename,
            "size": len(audio_bytes),
        },
        status_code=200,
    )


@app.get("/api/v1/recordings")
async def list_recordings(x_api_key: str = Header(...)):
    """List uploaded recordings."""
    user = API_KEYS.get(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")

    files = []
    for f in os.listdir(UPLOAD_DIR):
        if f.endswith(".opus"):
            filepath = os.path.join(UPLOAD_DIR, f)
            files.append({
                "filename": f,
                "size": os.path.getsize(filepath),
            })

    return {"recordings": files, "count": len(files)}


if __name__ == "__main__":
    import uvicorn
    print("LifeLog Dummy Server starting on http://0.0.0.0:8443")
    print("API Keys:", list(API_KEYS.keys()))
    print("Upload endpoint: POST /api/v1/upload")
    print("  Header: X-API-Key: <key>")
    print("  Body: multipart/form-data with 'file' field")
    uvicorn.run(app, host="0.0.0.0", port=8443)
