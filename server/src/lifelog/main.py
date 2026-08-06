from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from lifelog.database import init_db
from lifelog.routes import dashboard, speakers, upload


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="LifeLog", lifespan=lifespan)

# API routes
app.include_router(upload.router, prefix="/api/v1", tags=["upload"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(speakers.router, prefix="/api/v1/speakers", tags=["speakers"])

# Serve static dashboard files
app.mount("/", StaticFiles(directory="static", html=True), name="static")

# Run with HTTPS:
# uvicorn lifelog.main:app --host 0.0.0.0 --port 8443 \
#   --ssl-keyfile=certs/server.key --ssl-certfile=certs/server.crt
