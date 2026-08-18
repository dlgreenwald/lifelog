"""Upload Opus chunks to server.

Replicates the firmware's multipart POST format exactly:
  - X-API-Key header for auth
  - Form fields: utterance_id, chunk_index, is_final
  - File field: opus audio data
"""

import time
from pathlib import Path

import httpx

from e2e.config import SERVER_URL, UPLOAD_PATH, API_KEY


def upload_chunks(
    chunks: list,
    utterance_id: int,
    server_url: str = SERVER_URL,
    api_key: str = API_KEY,
) -> list[dict]:
    """Upload all chunks sequentially to the server.
    
    Returns list of response dicts.
    """
    url = f"{server_url}{UPLOAD_PATH}"
    headers = {"X-API-Key": api_key}
    
    responses = []
    total = len(chunks)
    
    for chunk in chunks:
        is_final = chunk.index == total - 1
        
        with open(chunk.opus_path, "rb") as f:
            opus_data = f.read()
        
        files = {"file": ("chunk.opus", opus_data, "application/octet-stream")}
        data = {
            "utterance_id": str(utterance_id),
            "chunk_index": str(chunk.index),
            "is_final": str(is_final).lower(),
        }
        
        t0 = time.monotonic()
        resp = httpx.post(url, headers=headers, files=files, data=data, timeout=30.0)
        elapsed = time.monotonic() - t0
        
        resp.raise_for_status()
        result = resp.json()
        result["elapsed_s"] = elapsed
        result["chunk_index"] = chunk.index
        result["is_final"] = is_final
        
        print(
            f"  Chunk {chunk.index+1}/{total}: {result['status']} "
            f"({elapsed:.2f}s, {len(opus_data)} bytes)"
        )
        
        responses.append(result)
    
    return responses
