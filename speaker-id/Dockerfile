FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3.11-distutils \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.11 /usr/local/bin/python

# Bootstrap pip for Python 3.11 (ensurepip disabled on Ubuntu/Debian)
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11

# Upgrade pip so it resolves deps correctly.
RUN python3.11 -m pip install --upgrade pip

# Install nvidia cuda_runtime stubs BEFORE torch so CUDA 12.8 stubs
# are in place when torch links — prevents pip from pulling a mismatched
# CUDA version from PyPI.
RUN python3.11 -m pip install --no-cache-dir nvidia-cuda-runtime-cu12

# Install the package (speechbrain dep) WITHOUT torch/torchaudio yet.
# speechbrain lists torchaudio as a dep without strict version pins;
# installing it first means pip cannot "helpfully" upgrade torch/torchaudio
# to a different version afterward.
COPY pyproject.toml .
RUN mkdir -p src/speaker_id && touch src/speaker_id/__init__.py
RUN python3.11 -m pip install --no-cache-dir .

# Install torch+torchaudio LAST and in the same command so pip resolves
# them together from the cu128 index and cannot substitute a PyPI version.
# torch 2.10.0+cu128 requires CUDA 13.1 libs absent from the 12.8 base
# image — use 2.8.0+cu128 (CUDA 12.8, matches transcription-worker image).
RUN python3.11 -m pip install --no-cache-dir \
        torch==2.8.0+cu128 \
        torchaudio==2.8.0+cu128 \
        --index-url https://download.pytorch.org/whl/cu128

# Copy real application code
COPY src/ src/
ENV PYTHONPATH=/app/src

EXPOSE 8443

CMD ["uvicorn", "speaker_id.main:app", "--host", "0.0.0.0", "--port", "8443"]
