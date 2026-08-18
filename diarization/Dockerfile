FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install Python 3.11, pip, and system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-dev \
    python3-pip \
    gcc \
    ffmpeg \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install all Python dependencies from pyproject.toml
# Create stub so pip can resolve the package and install its deps
COPY pyproject.toml .
RUN mkdir -p src/diarization && touch src/diarization/__init__.py
RUN pip install --no-cache-dir .

# Downgrade torch to 2.5.1 (pip install above pulls 2.13 which needs Python 3.12)
RUN pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cu124

# Copy real application code (overwrites stub, PYTHONPATH ensures it's found first)
COPY src/ src/
ENV PYTHONPATH=/app/src

EXPOSE 8443

CMD ["uvicorn", "diarization.main:app", "--host", "0.0.0.0", "--port", "8443"]
