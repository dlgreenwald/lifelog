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

# Install GPU-enabled torch (must precede pip install of speechbrain to link CUDA libs)
RUN python3.11 -m pip install --no-cache-dir torch==2.10.0 --index-url https://download.pytorch.org/whl/cu128

# Copy dependency files and install deps via stub
COPY pyproject.toml .
RUN mkdir -p src/speaker_id && touch src/speaker_id/__init__.py
RUN python3.11 -m pip install --no-cache-dir .

# Copy real application code (overwrites stub)
COPY src/ src/
ENV PYTHONPATH=/app/src

EXPOSE 8443

CMD ["uvicorn", "speaker_id.main:app", "--host", "0.0.0.0", "--port", "8443"]
