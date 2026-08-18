from contextlib import asynccontextmanager

from fastapi import FastAPI

from speaker_id.embeddings import encoder
from speaker_id.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan events."""
    # Startup: encoder is already initialized as singleton
    yield
    # Shutdown: stop watchdog and release GPU memory
    encoder.shutdown()


app = FastAPI(title="Speaker ID Service", lifespan=lifespan)
app.include_router(router)

# Run with HTTPS:
# uvicorn speaker_id.main:app --host 0.0.0.0 --port 8443 \
#   --ssl-keyfile=certs/server.key --ssl-certfile=certs/server.crt
