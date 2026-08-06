FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first for caching
COPY pyproject.toml .

# Install Python dependencies
RUN pip install --no-cache-dir .

# Copy application code
COPY src/ src/

# Create audio storage directory
RUN mkdir -p /data/audio

EXPOSE 8443

CMD ["uvicorn", "lifelog.main:app", "--host", "0.0.0.0", "--port", "8443"]
