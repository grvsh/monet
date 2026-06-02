from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.loader import load_all_models

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)


def _verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Verify Bearer token when ML_API_KEY is configured."""
    if not settings.ml_api_key:
        return  # no auth required (isolated Docker network)
    if credentials is None or credentials.credentials != settings.ml_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Loading ML models (this may take a minute on first run)...")
    await load_all_models()
    yield
    logger.info("ML service shutting down")


app = FastAPI(title="Monet ML Service", lifespan=lifespan)

# Import routers after app is defined to avoid circular imports with loader
from app.api.analyze import router as analyze_router      # noqa: E402
from app.api.assets import router as assets_router        # noqa: E402
from app.api.health import router as health_router        # noqa: E402
from app.api.transcode import router as transcode_router  # noqa: E402

# Health and manifest are unauthenticated (needed for Docker HEALTHCHECK and
# backend startup probe which may not have the API key at hand).
app.include_router(health_router)

# All inference and transcode endpoints require the API key when configured.
app.include_router(analyze_router, dependencies=[Depends(_verify_api_key)])
app.include_router(assets_router, dependencies=[Depends(_verify_api_key)])
app.include_router(transcode_router, dependencies=[Depends(_verify_api_key)])
