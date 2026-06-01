from __future__ import annotations

from arq.connections import RedisSettings, create_pool
from arq import cron

from app.config import settings
from app.workers.tasks import extract_metadata, geocode_missing, generate_assets, scan_folder, purge_old_trash
import exiftool


async def startup(ctx: dict) -> None:
    """ARQ worker startup: store an ARQ pool so tasks can enqueue child jobs."""
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    # Each concurrent job may open Redis connections while enqueuing child tasks.
    # Set the pool large enough so concurrent workers never timeout waiting.
    redis_settings.conn_timeout = 10
    redis_settings.max_connections = 50
    ctx["redis"] = await create_pool(redis_settings)
    # Keep a single persistent ExifTool process alive for the lifetime of this
    # worker so individual extract_metadata tasks do not pay the per-process
    # startup cost (~300–500 ms each).
    ctx["exiftool"] = exiftool.ExifToolHelper()


async def shutdown(ctx: dict) -> None:
    await ctx["redis"].aclose()
    try:
        ctx["exiftool"].terminate()
    except Exception:
        pass


class WorkerSettings:
    """Scan worker — handles file discovery and housekeeping only.

    extract_metadata is moved to the asset queue so heavy ExifTool jobs
    never starve scan_folder traversal tasks.
    """

    functions = [scan_folder, geocode_missing, purge_old_trash]
    cron_jobs = [
        cron(purge_old_trash, hour=2, minute=0),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = settings.monet_worker_concurrency
    job_timeout = 600
    keep_result = 3600
    queue_name = "arq:queue"


class AssetWorkerSettings:
    """Asset worker — handles thumbnail/preview generation and metadata extraction.

    Uses a separate queue so heavy processing never starves scan_folder tasks.
    """

    functions = [generate_assets, extract_metadata]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = settings.monet_worker_concurrency
    job_timeout = 600
    keep_result = 3600
    queue_name = "arq:asset-queue"
