FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files and install deps via stub
COPY pyproject.toml .
RUN mkdir -p src/speaker_id && touch src/speaker_id/__init__.py
RUN pip install --no-cache-dir .

# Copy real application code (overwrites stub)
COPY src/ src/
ENV PYTHONPATH=/app/src

EXPOSE 8443

CMD ["uvicorn", "speaker_id.main:app", "--host", "0.0.0.0", "--port", "8443"]
