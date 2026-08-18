FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files and install deps via stub
COPY pyproject.toml .
RUN mkdir -p src/lifelog && touch src/lifelog/__init__.py
RUN pip install --no-cache-dir .

# Copy real application code (overwrites stub)
COPY src/ src/
COPY alembic.ini .
COPY alembic/ alembic/
COPY migrate.py .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh
ENV PYTHONPATH=/app/src

# Create audio storage and static directories
RUN mkdir -p /data/audio /app/static

# Unbuffered Python output for Docker logging
ENV PYTHONUNBUFFERED=1

EXPOSE 8443

CMD ["./entrypoint.sh"]
