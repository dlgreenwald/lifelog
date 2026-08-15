"""
Dummy LifeLog server for smoke testing firmware uploads.
Mimics the real server's upload endpoint signature.
Logs uploads and discards files — not for real integration testing.
"""
import time
from fastapi import FastAPI, File, UploadFile, Header, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="LifeLog Dummy Server")

API_KEYS = {
    "test-api-key-1234": {"id": 1, "name": "Test Device"},
    "lifelog-key": {"id": 2, "name": "LifeLog Device"},
}


@app.get("/")
async def root():
    return {"status": "ok", "message": "LifeLog Dummy Server"}


@app.post("/api/v1/upload")
async def upload_audio(
    file: UploadFile = File(...),
    x_api_key: str = Header(...),
):
    """Accept Opus audio uploads — log and discard."""
    user = API_KEYS.get(x_api_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")

    audio_bytes = await file.read()
    print(f"[UPLOAD] {user['name']}: {file.filename} ({len(audio_bytes)} bytes)")

    return JSONResponse(
        content={"status": "processed", "recording_id": hash(str(time.time())) % 100000},
        status_code=200,
    )


if __name__ == "__main__":
    import uvicorn
    print("LifeLog Dummy Server on http://0.0.0.0:8443")
    uvicorn.run(app, host="0.0.0.0", port=8443)
