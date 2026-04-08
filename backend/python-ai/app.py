from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ml_service import PM10MLService
from routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    App lifespan:
      - Load ML artifacts ONCE at startup
      - Keep in app.state.ml_service
      - Cleanup on shutdown
    """
    artifacts_root = Path(__file__).parent / "artifacts"
    service = PM10MLService(artifacts_root=artifacts_root)
    service.load_all()
    app.state.ml_service = service

    yield

    service.close()
    app.state.ml_service = None


app = FastAPI(
    title="PM10 Forecast API",
    version="1.0.0",
    lifespan=lifespan
)

# Adjust as needed for your frontend domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # lock down in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "pm10-forecast"}