from fastapi import APIRouter, UploadFile

from diarization.pipeline import pipeline

router = APIRouter()


@router.post("/diarize")
async def diarize_audio(file: UploadFile):
    """Perform speaker diarization on audio."""
    audio_bytes = await file.read()
    segments = pipeline.diarize(audio_bytes)
    return {"segments": segments}


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}
