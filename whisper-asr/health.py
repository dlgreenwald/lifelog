"""Add /health endpoint to the upstream FastAPI app at import time."""

from app.webservice import app


@app.get("/health")
async def health():
    return {"status": "ok"}
