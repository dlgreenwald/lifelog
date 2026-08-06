FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first for caching
COPY pyproject.toml .

# Install Python dependencies
RUN pip install --no-cache-dir .

# Copy application code
COPY src/ src/

EXPOSE 8443

CMD ["uvicorn", "speaker_id.main:app", "--host", "0.0.0.0", "--port", "8443"]
