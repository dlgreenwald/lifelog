from fastapi import FastAPI

from diarization.routes import router

app = FastAPI(title="Diarization Service")
app.include_router(router)

# Run with HTTPS:
# uvicorn diarization.main:app --host 0.0.0.0 --port 8443 \
#   --ssl-keyfile=certs/server.key --ssl-certfile=certs/server.crt
