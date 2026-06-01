from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.core.limiter import limiter
from app.redis_client import close_redis, get_redis

logging.basicConfig(level=settings.monet_log_level.upper())
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ------------------------------------------------------------------ startup
    logger.info("Monet starting up")
    await get_redis()

    from app.core import clip_encoder
    clip_encoder.preload()

    # Start watchdog observers for all active root folders
    if settings.monet_watch_enabled:
        try:
            from sqlalchemy import select
            from app.database import async_session_factory
            from app.models.db import RootFolder
            from app.services.watcher import watcher_manager
            from app.api.root_folders import _on_file_change
            import asyncio

            loop = asyncio.get_event_loop()
            async with async_session_factory() as session:
                result = await session.execute(
                    select(RootFolder).where(RootFolder.is_active == True)  # noqa: E712
                )
                roots = result.scalars().all()
                for root in roots:
                    watcher_manager.start(
                        str(root.id),
                        root.path,
                        _on_file_change,
                        settings.monet_file_settle_seconds,
                        loop,
                    )
                    logger.info("Watching %s (%s)", root.name, root.path)
        except Exception as exc:
            logger.warning("Could not start file watchers: %s", exc)

    yield

    # ----------------------------------------------------------------- shutdown
    logger.info("Monet shutting down")
    try:
        from app.services.watcher import watcher_manager
        watcher_manager.stop_all()
    except Exception:
        pass
    await close_redis()


app = FastAPI(title="Monet", version="0.1.0", lifespan=lifespan)

# ── Rate limiting ────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ─────────────────────────────────────────────────────────────────────
# Restrict to the exact HTTP methods and headers the frontend actually uses.
# Never use allow_methods="*" or allow_headers="*" with allow_credentials=True.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.monet_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# ---- API routers -----------------------------------------------------------
from app.api import albums, auth, files, folders, fs_browse, index, root_folders, search, thumbnails, users  # noqa: E402

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(root_folders.router, prefix="/api/root-folders", tags=["root-folders"])
app.include_router(fs_browse.router, prefix="/api/fs", tags=["filesystem"])
app.include_router(folders.router, prefix="/api/folders", tags=["folders"])
app.include_router(files.router, prefix="/api/files", tags=["files"])
app.include_router(thumbnails.router, prefix="/api", tags=["media"])
app.include_router(index.router, prefix="/api/index", tags=["indexing"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(albums.router, prefix="/api/albums", tags=["albums"])

# ---- Serve built frontend (if present) ------------------------------------
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
    logger.info("Serving frontend from %s", frontend_dist)
