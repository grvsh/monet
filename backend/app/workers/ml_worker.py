from __future__ import annotations

import io
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from arq import cron
from arq.connections import RedisSettings, create_pool
from PIL import Image
from sqlalchemy import select, update

from app.config import settings
from app.database import async_session_factory
from app.models.db import FaceDetection, MediaFile, RootFolder, ScanJob

logger = logging.getLogger(__name__)

_STAGING_KEY = "ml:batch_staging"


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------


async def ml_startup(ctx: dict) -> None:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    redis_settings.conn_timeout = 10
    redis_settings.max_connections = 50
    ctx["redis"] = await create_pool(redis_settings)
    ctx["ml_configured"] = bool(settings.monet_ml_service_url)
    ctx["ml_manifest"] = None

    if ctx["ml_configured"]:
        ctx["ml_manifest"] = await _fetch_manifest()
        if ctx["ml_manifest"]:
            logger.info("ML service ready, features: %s", list(ctx["ml_manifest"].keys()))
            # Publish manifest to Redis so scan_folder can check feature staleness
            # without needing to call the ML service directly.
            await ctx["redis"].set("ml:manifest", json.dumps(ctx["ml_manifest"]))
        else:
            logger.warning("ML service unreachable at startup; will retry per batch")


async def ml_shutdown(ctx: dict) -> None:
    await ctx["redis"].aclose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    if settings.monet_ml_api_key:
        headers["Authorization"] = f"Bearer {settings.monet_ml_api_key}"
    return headers


async def _fetch_manifest() -> dict | None:
    """Fetch the model version manifest from the ML service."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.monet_ml_service_url}/manifest",
                headers=_build_headers(),
            )
            resp.raise_for_status()
            return resp.json()
    except Exception:
        logger.exception("Failed to fetch ML manifest")
        return None


def _stale_features(stored: dict | None, manifest: dict) -> list[str]:
    """Return features whose stored model version differs from the current manifest."""
    if stored is None:
        return list(manifest.keys())
    stale = [f for f, meta in manifest.items() if stored.get(f) != meta["version"]]
    # Expand depends_on: if a dependency is stale, its dependent must also recompute.
    dep_stale: set[str] = set(stale)
    for feature, meta in manifest.items():
        if any(dep in dep_stale for dep in meta.get("depends_on", [])):
            dep_stale.add(feature)
    return list(dep_stale)


def _resize_for_ml(img: Image.Image, max_side: int) -> bytes:
    """Resize image so the longest side ≤ max_side, return JPEG bytes."""
    img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue()


def _preview_path(media_file: MediaFile) -> Path | None:
    if media_file.preview_path:
        return Path(settings.monet_cache_dir) / "previews" / media_file.preview_path
    if media_file.thumbnail_path:
        return Path(settings.monet_cache_dir) / "thumbnails" / media_file.thumbnail_path
    return None


# ---------------------------------------------------------------------------
# ARQ task: lightweight staging (one per file, enqueued by generate_assets)
# ---------------------------------------------------------------------------


async def ml_analyze_file(
    ctx: dict,
    file_id_str: str,
    scan_job_id_str: str | None = None,
) -> None:
    """Push a file into the ML batch staging list and update the scan job counter."""
    if not ctx.get("ml_configured"):
        return

    redis = ctx["redis"]
    await redis.rpush(_STAGING_KEY, f"{file_id_str}:{scan_job_id_str or ''}")

    if scan_job_id_str:
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    await session.execute(
                        update(ScanJob)
                        .where(ScanJob.id == uuid.UUID(scan_job_id_str))
                        .values(ml_files_pending=ScanJob.ml_files_pending + 1)
                    )
        except Exception:
            logger.exception("Failed to update ml_files_pending for job %s", scan_job_id_str)


# ---------------------------------------------------------------------------
# ARQ cron: batch flusher (runs every 10 seconds)
# ---------------------------------------------------------------------------


async def ml_flush_batch(ctx: dict) -> None:
    """Drain the staging list in batches and send each batch to the ML service."""
    if not ctx.get("ml_configured"):
        return

    # Re-fetch manifest if not loaded yet (ML service may have been down at startup)
    if ctx.get("ml_manifest") is None:
        ctx["ml_manifest"] = await _fetch_manifest()
        if ctx["ml_manifest"] is None:
            return

    manifest: dict = ctx["ml_manifest"]
    batch_size = settings.monet_ml_batch_size
    redis = ctx["redis"]

    while True:
        # Pop up to batch_size items from the staging list
        pipe = redis.pipeline()
        for _ in range(batch_size):
            pipe.lpop(_STAGING_KEY)
        raw_items = await pipe.execute()
        items = [
            r.decode() if isinstance(r, bytes) else r
            for r in raw_items if r is not None
        ]
        if not items:
            break
        await _process_batch(items, manifest)


async def _process_batch(raw_items: list[str], manifest: dict) -> None:
    """Load preview images, POST to ML service, persist results."""
    # Parse staging entries
    pairs: list[tuple[uuid.UUID, uuid.UUID | None]] = []
    for item in raw_items:
        parts = item.split(":", 1)
        file_id = uuid.UUID(parts[0])
        scan_job_id = uuid.UUID(parts[1]) if parts[1] else None
        pairs.append((file_id, scan_job_id))

    file_ids = [p[0] for p in pairs]

    # Load file rows from DB
    async with async_session_factory() as session:
        result = await session.execute(
            select(MediaFile).where(
                MediaFile.id.in_(file_ids),
                MediaFile.is_deleted == False,  # noqa: E712
            )
        )
        files_by_id: dict[uuid.UUID, MediaFile] = {f.id: f for f in result.scalars().all()}

    if not files_by_id:
        return

    # Build per-file feature lists and image payloads
    ordered: list[tuple[uuid.UUID, uuid.UUID | None, list[str], bytes | None]] = []
    for file_id, scan_job_id in pairs:
        mf = files_by_id.get(file_id)
        if not mf:
            continue
        stale = _stale_features(mf.ai_versions, manifest)
        if not stale:
            # Nothing to recompute — decrement pending, increment done
            await _update_scan_counter(scan_job_id, done=1, pending=-1)
            continue
        img_bytes = _load_image_bytes(mf)
        ordered.append((file_id, scan_job_id, stale, img_bytes))

    if not ordered:
        return

    # Union of all features needed across the batch
    all_features: list[str] = sorted({f for _, _, feats, _ in ordered for f in feats})

    # Build multipart payload
    files_payload: list[tuple[str, tuple[str, bytes, str]]] = []
    valid_ordered: list[tuple[uuid.UUID, uuid.UUID | None, list[str]]] = []
    for file_id, scan_job_id, feats, img_bytes in ordered:
        if img_bytes is None:
            logger.warning("No preview for file %s, skipping ML analysis", file_id)
            await _update_scan_counter(scan_job_id, failed=1, pending=-1)
            continue
        idx = len(files_payload)
        files_payload.append(("images", (f"img_{idx}.jpg", img_bytes, "image/jpeg")))
        valid_ordered.append((file_id, scan_job_id, feats))

    if not files_payload:
        return

    # POST to ML service
    try:
        async with httpx.AsyncClient(timeout=1800) as client:
            resp = await client.post(
                f"{settings.monet_ml_service_url}/analyze",
                files=files_payload,
                data={"features": ",".join(all_features)},
                headers=_build_headers(),
            )
            resp.raise_for_status()
            ml_results: list[dict] = resp.json()["results"]
    except Exception:
        logger.exception("ML service batch call failed (%d files)", len(files_payload))
        for _, scan_job_id, _ in valid_ordered:
            await _update_scan_counter(scan_job_id, failed=1, pending=-1)
        return

    # Persist results — one transaction per file so a failure on one doesn't
    # roll back the whole batch.
    now = datetime.now(timezone.utc)
    for (file_id, scan_job_id, feats), ml_result in zip(valid_ordered, ml_results):
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    mf = await session.get(MediaFile, file_id)
                    if mf:
                        _apply_ml_result(mf, ml_result, manifest, feats, now, session)
            await _update_scan_counter(scan_job_id, done=1, pending=-1)
        except Exception:
            logger.exception("Failed to persist ML result for file %s", file_id)
            await _update_scan_counter(scan_job_id, failed=1, pending=-1)


def _load_image_bytes(mf: MediaFile) -> bytes | None:
    path = _preview_path(mf)
    if not path or not path.exists():
        return None
    try:
        img = Image.open(path)
        return _resize_for_ml(img, settings.monet_ml_image_size)
    except Exception:
        logger.warning("Failed to load/resize image for file %s", mf.id)
        return None


def _apply_ml_result(
    mf: MediaFile,
    result: dict,
    manifest: dict,
    requested_features: list[str],
    now: datetime,
    session,  # required for session.add(FaceDetection)
) -> None:
    """Write ML result fields onto the MediaFile row and insert face detections."""
    versions: dict = dict(mf.ai_versions or {})

    if "clip_embedding" in result and result["clip_embedding"] is not None:
        mf.clip_embedding = result["clip_embedding"]
        versions["clip_embedding"] = manifest["clip_embedding"]["version"]

    if "dino_embedding" in result and result["dino_embedding"] is not None:
        mf.dino_embedding = result["dino_embedding"]
        versions["dino_embedding"] = manifest["dino_embedding"]["version"]

    if "caption" in result and result["caption"] is not None:
        mf.caption = result["caption"]
        versions["caption"] = manifest["caption"]["version"]

    if "objects" in result and result["objects"] is not None:
        mf.ai_objects = result["objects"]
        versions["objects"] = manifest["objects"]["version"]

    if "aesthetic_score" in result and result["aesthetic_score"] is not None:
        mf.aesthetic_score = result["aesthetic_score"]
        versions["aesthetic_score"] = manifest["aesthetic_score"]["version"]

    if "faces" in result and result["faces"] is not None:
        versions["faces"] = manifest["faces"]["version"]
        for face_data in result["faces"]:
            fd = FaceDetection(
                file_id=mf.id,
                bbox=face_data["bbox"],
                embedding=face_data.get("embedding"),
                confidence=face_data.get("confidence"),
            )
            session.add(fd)

    mf.ai_versions = versions
    mf.ai_analyzed_at = now


async def _update_scan_counter(
    scan_job_id: uuid.UUID | None,
    done: int = 0,
    failed: int = 0,
    pending: int = 0,
) -> None:
    if not scan_job_id:
        return
    values: dict = {}
    if done:
        values["ml_files_done"] = ScanJob.ml_files_done + done
    if failed:
        values["ml_files_failed"] = ScanJob.ml_files_failed + failed
    if pending:
        values["ml_files_pending"] = ScanJob.ml_files_pending + pending
    if not values:
        return

    async with async_session_factory() as s:
        async with s.begin():
            await s.execute(update(ScanJob).where(ScanJob.id == scan_job_id).values(**values))


# ---------------------------------------------------------------------------
# Worker settings
# ---------------------------------------------------------------------------


class MLWorkerSettings:
    """ML worker — stages files for batch ML analysis and flushes batches every 30s."""

    functions = [ml_analyze_file, ml_flush_batch]
    cron_jobs = [
        cron(ml_flush_batch, second={0, 30}),
    ]
    on_startup = ml_startup
    on_shutdown = ml_shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 16
    job_timeout = 1800
    keep_result = 3600
    queue_name = "arq:ml-queue"
