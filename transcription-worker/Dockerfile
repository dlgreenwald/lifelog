FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ASR_MODEL=large-v3 \
    ASR_DEVICE=cuda \
    TRANSFORMERS_NO_ADVISORY_WARNINGS=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install torch==2.7.1+cu128 torchaudio==2.7.1+cu128 \
        --index-url https://download.pytorch.org/whl/cu128 && \
    python3 -m pip install \
        "fastapi>=0.104.0" "uvicorn[standard]>=0.24.0" "httpx>=0.25.0" \
        "numpy>=1.24.0" "whisperx>=3.3.0" "transformers<5"
COPY audio.py pipeline.py main.py ./

EXPOSE 9000
CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000"]
