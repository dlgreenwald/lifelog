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

# Upgrade pip first so it can resolve dependencies correctly.
RUN python3 -m pip install --upgrade pip

# Install nvidia cuda_runtime stubs before torch so the CUDA 12.8 stubs
# are available when torch links — prevents pip from pulling a mismatched
# CUDA version from PyPI.
RUN python3 -m pip install --no-cache-dir nvidia-cuda-runtime-cu12

# torch 2.10.0+cu128 requires CUDA 13.1 libs absent from the 12.8 base
# image. Use 2.8.0+cu128 (CUDA 12.8) which matches the base image and is
# confirmed working in production. Both torch and torchaudio are installed
# in the same command so pip resolves them both from the cu128 index.
RUN python3 -m pip install --no-cache-dir \
        torch==2.8.0+cu128 \
        torchaudio==2.8.0+cu128 \
        --index-url https://download.pytorch.org/whl/cu128

RUN python3 -m pip install --no-cache-dir \
        "fastapi>=0.104.0" "uvicorn[standard]>=0.24.0" "httpx>=0.25.0" \
        "numpy>=1.24.0" "whisperx>=3.3.0" "transformers>=5.5.0" "pydantic-settings>=2.1.0"

COPY audio.py pipeline.py main.py ./

EXPOSE 9000
CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000"]
