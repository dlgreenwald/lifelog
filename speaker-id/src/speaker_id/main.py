from fastapi import FastAPI

from speaker_id.routes import router

app = FastAPI(title="Speaker ID Service")
app.include_router(router)

# Run with HTTPS:
# uvicorn speaker_id.main:app --host 0.0.0.0 --port 8443 \
#   --ssl-keyfile=certs/server.key --ssl-certfile=certs/server.crt
