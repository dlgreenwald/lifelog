"""
Dummy LifeLog server for smoke testing firmware uploads.
Mimics the real server's upload endpoint signature with utterance chunk support.
Use --save flag to save uploaded files to ./uploads/
"""
import os
import sys
import time
from fastapi import FastAPI, File, Form, UploadFile, Header, HTTPException
from fastapi.responses import JSONResponse

SAVE_FILES = "--save" in sys.argv
UPLOAD_DIR = "uploads"

if SAVE_FILES:
    os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="LifeLog Dummy Server")


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

    audio_bytes = await file.read()

    if SAVE_FILES:
        # Each utterance gets its own directory: uploads/user{N}_utt{M}/
        utt_dir = os.path.join(UPLOAD_DIR, f"user{user['id']}_utt{utterance_id}")
        os.makedirs(utt_dir, exist_ok=True)

        basename = os.path.basename(file.filename or f"chunk_{chunk_index}.opus")
        chunk_path = os.path.join(utt_dir, f"chunk{chunk_index:03d}_{basename}")
        with open(chunk_path, "wb") as f:
            f.write(audio_bytes)
        print(
            f"[CHUNK] {user['name']}: utt={utterance_id} chunk={chunk_index} "
            f"final={is_final} ({len(audio_bytes)} bytes) -> {chunk_path}"
        )

    if not is_final:
        return JSONResponse(
            content={
                "status": "chunk_stored",
                "utterance_id": utterance_id,
                "chunk_index": chunk_index,
            },
            status_code=200,
        )

    # Utterance complete — count chunks on disk
    if SAVE_FILES:
        utt_dir = os.path.join(UPLOAD_DIR, f"user{user['id']}_utt{utterance_id}")
        chunk_count = len([f for f in os.listdir(utt_dir) if f.startswith("chunk")])
        print(
            f"[UTTERANCE] {user['name']}: utt={utterance_id} "
            f"complete ({chunk_count} chunks in {utt_dir})"
        )

    return JSONResponse(
        content={"status": "processed", "utterance_id": utterance_id},
        status_code=200,
    )


if __name__ == "__main__":
    import uvicorn

    mode = "SAVE mode" if SAVE_FILES else "log-only mode"
    print(f"LifeLog Dummy Server on http://0.0.0.0:8444 ({mode})")
    print("Usage: python dummy_server.py [--save]")
    uvicorn.run(app, host="0.0.0.0", port=8444)
