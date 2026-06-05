from __future__ import annotations

import io
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from arq import cron
from arq.connections import RedisSettings, create_pool
from PIL import Image
from sqlalchemy import select, text, update

from app.config import settings
from app.database import async_session_factory
from app.models.db import FaceDetection, MediaFile, RootFolder, ScanJob, TaskTiming
from app.services.media import thumbnail_cache_path, preview_cache_path
from app.services.processor import generate_video_preview as _cpu_transcode

logger = logging.getLogger(__name__)


async def _record_timing(
    task_name: str,
    started_at: datetime,
    duration_ms: int,
    success: bool,
    file_count: int = 1,
) -> None:
    try:
        async with async_session_factory() as s:
            async with s.begin():
                s.add(TaskTiming(
                    task_name=task_name,
                    started_at=started_at,
                    duration_ms=duration_ms,
                    success=success,
                    file_count=file_count,
                ))
    except Exception:
        logger.warning("Failed to record task timing for %s", task_name)


_STAGING_KEY = "ml:batch_staging"
_CAPTION_STAGING_KEY = "ml:caption_staging"
_ASSETS_STAGING_KEY = "assets:gpu_staging"
# Features that run sequentially and are excluded from the fast batch pass.
# They are re-staged to _CAPTION_STAGING_KEY and flushed at a lower cadence.
_SLOW_FEATURES: frozenset[str] = frozenset({"caption"})


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
    """Process one batch from the staging list and send it to the ML service.

    One batch per cron fire. The 30-second cron cadence drives throughput.
    A Redis lock prevents concurrent runs from the same pile-up of stale triggers.
    Lock TTL (600s) is sized to outlast a single batch including ML service latency.
    """
    if not ctx.get("ml_configured"):
        return

    redis = ctx["redis"]

    # Instant no-op for all stale/concurrent triggers while a batch is in flight.
    lock_acquired = await redis.set("ml:flush_lock", "1", nx=True, ex=600)
    if not lock_acquired:
        return

    try:
        # Re-fetch manifest if not loaded yet (ML service may have been down at startup)
        if ctx.get("ml_manifest") is None:
            ctx["ml_manifest"] = await _fetch_manifest()
            if ctx["ml_manifest"] is None:
                return

        manifest: dict = ctx["ml_manifest"]
        batch_size = settings.monet_ml_batch_size

        # Pop exactly one batch
        pipe = redis.pipeline()
        for _ in range(batch_size):
            pipe.lpop(_STAGING_KEY)
        raw_items = await pipe.execute()
        items = [
            r.decode() if isinstance(r, bytes) else r
            for r in raw_items if r is not None
        ]
        if items:
            await _process_batch(items, manifest, redis=redis)
    finally:
        await redis.delete("ml:flush_lock")


async def ml_flush_caption(ctx: dict) -> None:
    """Process caption batches continuously until the queue is empty or time runs out.

    Uses a time-budget loop so the GPU stays busy across multiple batches per job
    instead of sitting idle between 5-minute cron fires. Each batch takes ~66s;
    we run as many as fit within 540s (9s buffer before the 600s job timeout).
    """
    if not ctx.get("ml_configured"):
        return

    redis = ctx["redis"]
    lock_acquired = await redis.set("ml:caption_lock", "1", nx=True, ex=600)
    if not lock_acquired:
        return

    try:
        if ctx.get("ml_manifest") is None:
            ctx["ml_manifest"] = await _fetch_manifest()
            if ctx["ml_manifest"] is None:
                return

        manifest: dict = ctx["ml_manifest"]
        if "caption" not in manifest:
            return

        caption_manifest = {"caption": manifest["caption"]}
        batch_size = settings.monet_ml_batch_size

        import time
        deadline = time.monotonic() + 540  # keep 60s buffer before job_timeout

        while time.monotonic() < deadline:
            pipe = redis.pipeline()
            for _ in range(batch_size):
                pipe.lpop(_CAPTION_STAGING_KEY)
            raw_items = await pipe.execute()
            items = [
                r.decode() if isinstance(r, bytes) else r
                for r in raw_items if r is not None
            ]
            if not items:
                break
            await _process_batch(items, caption_manifest, redis=redis)
    finally:
        await redis.delete("ml:caption_lock")


async def _process_batch(raw_items: list[str], manifest: dict, redis=None) -> None:
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

    # Split fast features (batched GPU) from slow ones (caption: sequential LM),
    # but only when the manifest itself contains fast features. When called from
    # ml_flush_caption the manifest is caption-only, so the split is skipped and
    # captions are sent directly to the ML service.
    has_fast_in_manifest = bool(set(manifest.keys()) - _SLOW_FEATURES)

    # Files re-staged for captions must not have their pending counter decremented
    # here — caption processing will do it. Tracking them avoids a double-decrement
    # that causes ml_files_pending to go negative.
    caption_restage_ids: set[uuid.UUID] = set()

    if has_fast_in_manifest:
        caption_restage: list[tuple[uuid.UUID, uuid.UUID | None]] = []
        fast_ordered: list[tuple[uuid.UUID, uuid.UUID | None, list[str], bytes | None]] = []
        for file_id, scan_job_id, feats, img_bytes in ordered:
            fast_feats = [f for f in feats if f not in _SLOW_FEATURES]
            slow_feats = [f for f in feats if f in _SLOW_FEATURES]
            if slow_feats:
                caption_restage.append((file_id, scan_job_id))
                caption_restage_ids.add(file_id)
            if fast_feats:
                fast_ordered.append((file_id, scan_job_id, fast_feats, img_bytes))

        if caption_restage and redis is not None:
            for file_id, scan_job_id in caption_restage:
                await redis.rpush(_CAPTION_STAGING_KEY, f"{file_id}:{scan_job_id or ''}")

        if not fast_ordered:
            return
        ordered = fast_ordered

    # Union of features needed across the batch
    all_features: list[str] = sorted({f for _, _, feats, _ in ordered for f in feats})

    # Build multipart payload
    files_payload: list[tuple[str, tuple[str, bytes, str]]] = []
    valid_ordered: list[tuple[uuid.UUID, uuid.UUID | None, list[str]]] = []
    for file_id, scan_job_id, feats, img_bytes in ordered:
        if img_bytes is None:
            logger.warning("No preview for file %s, skipping ML analysis", file_id)
            await _set_ml_file_error(file_id, "No preview image available")
            await _update_scan_counter(scan_job_id, failed=1, pending=-1)
            continue
        idx = len(files_payload)
        files_payload.append(("images", (f"img_{idx}.jpg", img_bytes, "image/jpeg")))
        valid_ordered.append((file_id, scan_job_id, feats))

    if not files_payload:
        return

    # POST to ML service
    _t0 = time.monotonic()
    _started_at = datetime.now(timezone.utc)
    _task_label = "caption_batch" if not has_fast_in_manifest else "ml_batch"
    try:
        async with httpx.AsyncClient(timeout=540) as client:
            resp = await client.post(
                f"{settings.monet_ml_service_url}/analyze",
                files=files_payload,
                data={"features": ",".join(all_features)},
                headers=_build_headers(),
            )
            resp.raise_for_status()
            ml_results: list[dict] = resp.json()["results"]
    except Exception as exc:
        logger.exception("ML service batch call failed (%d files)", len(files_payload))
        await _record_timing(_task_label, _started_at, int((time.monotonic() - _t0) * 1000), False, len(valid_ordered))
        for file_id, scan_job_id, _ in valid_ordered:
            await _set_ml_file_error(file_id, f"ML service request failed: {exc!s}"[:500])
            await _update_scan_counter(scan_job_id, failed=1, pending=-1)
        return
    await _record_timing(_task_label, _started_at, int((time.monotonic() - _t0) * 1000), True, len(valid_ordered))

    # Persist results — one transaction per file so a failure on one doesn't
    # roll back the whole batch.
    now = datetime.now(timezone.utc)
    for (file_id, scan_job_id, feats), ml_result in zip(valid_ordered, ml_results):
        restaged = file_id in caption_restage_ids
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    mf = await session.get(MediaFile, file_id)
                    if mf:
                        _apply_ml_result(mf, ml_result, manifest, feats, now, session)
            if not restaged:
                await _update_scan_counter(scan_job_id, done=1, pending=-1)
        except Exception as exc:
            logger.exception("Failed to persist ML result for file %s", file_id)
            await _set_ml_file_error(file_id, f"Failed to save ML result: {exc!s}"[:500])
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
    mf.ml_error = None


async def _set_ml_file_error(file_id: uuid.UUID, error: str) -> None:
    async with async_session_factory() as s:
        async with s.begin():
            await s.execute(
                update(MediaFile).where(MediaFile.id == file_id).values(ml_error=error[:500])
            )


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
# Face clustering
# ---------------------------------------------------------------------------

_CLUSTER_LOCK = "ml:cluster_faces_lock"
_CLUSTER_LOCK_TTL = 3600  # 1 hour max for a cluster run
_CLUSTER_PROGRESS = "ml:cluster_faces_progress"
_CLUSTER_PROGRESS_TTL = 3600


async def _set_progress(redis: object | None, step: str, pct: int) -> None:
    if redis:
        import json
        await redis.set(  # type: ignore[attr-defined]
            _CLUSTER_PROGRESS,
            json.dumps({"step": step, "pct": pct}),
            ex=_CLUSTER_PROGRESS_TTL,
        )


async def cluster_faces(ctx: dict) -> None:
    """DBSCAN cluster all stored face embeddings and assign person_id.

    Runs nightly.  Preserves existing person names by matching new cluster
    centroids to existing ones (cosine similarity ≥ 0.85).
    """
    redis = ctx.get("redis")
    if redis and not await redis.set(_CLUSTER_LOCK, "1", nx=True, ex=_CLUSTER_LOCK_TTL):
        logger.info("cluster_faces: another run in progress, skipping")
        return

    try:
        await _do_cluster_faces(redis)
    finally:
        if redis:
            await redis.delete(_CLUSTER_LOCK)
            await redis.delete(_CLUSTER_PROGRESS)


async def _do_cluster_faces(redis: object | None = None) -> None:
    import numpy as np
    from sklearn.cluster import DBSCAN
    from sqlalchemy import func

    from app.models.db import FaceDetection, Person

    async with async_session_factory() as session:
        async with session.begin():
            # ── 1. Load all face embeddings ──────────────────────────────────
            await _set_progress(redis, "Loading faces", 5)
            result = await session.execute(
                select(FaceDetection).where(FaceDetection.embedding.isnot(None))
            )
            all_faces: list[FaceDetection] = result.scalars().all()

            if len(all_faces) < 2:
                logger.info("cluster_faces: fewer than 2 faces, nothing to cluster")
                return

            logger.info("cluster_faces: clustering %d face embeddings", len(all_faces))

            await _set_progress(redis, "Preparing embeddings", 15)
            embeddings = np.array([f.embedding for f in all_faces], dtype=np.float32)

            # ── 2. L2-normalise (euclidean on unit vecs == cosine distance) ──
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            normalized = embeddings / (norms + 1e-10)

            # ── 3. DBSCAN ────────────────────────────────────────────────────
            # eps=0.95 on L2-normalised ≈ cosine distance 0.45 threshold
            await _set_progress(redis, "Clustering faces", 30)
            clustering = DBSCAN(
                eps=0.95,
                min_samples=2,
                metric="euclidean",
                algorithm="ball_tree",
                n_jobs=-1,
            ).fit(normalized)
            labels: np.ndarray = clustering.labels_

            n_clusters = len(set(labels) - {-1})
            logger.info("cluster_faces: found %d clusters, %d noise points",
                        n_clusters, int((labels == -1).sum()))

            # ── 4. Load existing persons for centroid matching ───────────────
            await _set_progress(redis, f"Matching {n_clusters} clusters", 60)
            persons_result = await session.execute(
                select(Person).where(Person.centroid.isnot(None))
            )
            existing_persons: list[Person] = persons_result.scalars().all()

            if existing_persons:
                existing_centroids = np.array(
                    [p.centroid for p in existing_persons], dtype=np.float32
                )
            else:
                existing_centroids = np.empty((0, 512), dtype=np.float32)

            # ── 5. Match new clusters → persons ──────────────────────────────
            unique_labels = sorted(set(labels.tolist()) - {-1})
            label_to_person: dict[int, Person] = {}
            matched_person_ids: set = set()

            for label in unique_labels:
                mask = labels == label
                cluster_embs = normalized[mask]
                centroid = cluster_embs.mean(axis=0)
                centroid /= np.linalg.norm(centroid) + 1e-10

                matched_person: Person | None = None
                if len(existing_persons) > 0:
                    sims = existing_centroids @ centroid  # cosine similarities
                    best_idx = int(np.argmax(sims))
                    if (
                        float(sims[best_idx]) >= 0.85
                        and existing_persons[best_idx].id not in matched_person_ids
                    ):
                        matched_person = existing_persons[best_idx]
                        matched_person_ids.add(matched_person.id)
                        matched_person.centroid = centroid.tolist()

                if matched_person is None:
                    matched_person = Person(centroid=centroid.tolist())
                    session.add(matched_person)
                    await session.flush()
                    existing_persons.append(matched_person)
                    existing_centroids = np.vstack([existing_centroids, centroid])

                label_to_person[label] = matched_person

            # ── 6. Bulk-update face assignments ──────────────────────────────
            await _set_progress(redis, "Saving assignments", 85)
            for i, face in enumerate(all_faces):
                label = int(labels[i])
                face.person_id = label_to_person[label].id if label != -1 else None

            await session.flush()

            # ── 7. Delete orphaned persons ───────────────────────────────────
            await _set_progress(redis, "Cleaning up", 95)
            used_ids = {p.id for p in label_to_person.values()}
            for person in existing_persons:
                if person.id in used_ids:
                    continue
                count_result = await session.execute(
                    select(func.count()).where(FaceDetection.person_id == person.id)
                )
                if count_result.scalar_one() == 0:
                    await session.delete(person)

    logger.info("cluster_faces: done")


# ---------------------------------------------------------------------------
# GPU asset generation batch flush (thumbnails + previews)
# ---------------------------------------------------------------------------


async def flush_gpu_assets(ctx: dict) -> None:
    """Cron: pop a batch of images from staging, call /assets/generate/batch,
    update the DB. Falls back to local CPU for any item that fails.

    Runs every 5 s; a Redis lock prevents concurrent runs.
    """
    if not settings.monet_ml_service_url:
        return

    redis = ctx["redis"]
    lock = await redis.set("assets:flush_lock", "1", nx=True, ex=120)
    if not lock:
        return

    try:
        pipe = redis.pipeline()
        for _ in range(settings.monet_ml_batch_size):
            pipe.lpop(_ASSETS_STAGING_KEY)
        raw = await pipe.execute()
        items = [
            (r.decode() if isinstance(r, bytes) else r)
            for r in raw if r is not None
        ]
        if not items:
            return

        # Build per-file info from DB
        file_ids_scan = []
        for entry in items:
            fid, *rest = entry.split(":")
            file_ids_scan.append((uuid.UUID(fid), rest[0] if rest and rest[0] else None))

        requests = []
        meta: list[tuple] = []  # (file_id, scan_job_id, thumb_path, preview_path)
        async with async_session_factory() as session:
            for file_id, scan_job_id in file_ids_scan:
                mf = await session.get(MediaFile, file_id)
                if not mf or mf.is_deleted or mf.processed_at is not None:
                    continue
                root = await session.get(RootFolder, mf.root_folder_id)
                if not root:
                    continue
                abs_path = str(Path(root.path) / mf.path)
                thumb_path = thumbnail_cache_path(file_id, settings.monet_cache_dir)
                preview_path = preview_cache_path(file_id, settings.monet_cache_dir)
                requests.append({
                    "src": abs_path,
                    "thumb_path": str(thumb_path),
                    "preview_path": str(preview_path),
                    "media_type": mf.media_type,
                    "extension": mf.extension,
                    "thumb_size": settings.monet_thumb_size,
                    "preview_max_w": settings.monet_preview_max_width,
                    "preview_max_h": settings.monet_preview_max_height,
                    "thumb_quality": settings.monet_thumb_quality,
                    "preview_quality": settings.monet_preview_quality,
                })
                meta.append((file_id, scan_job_id, thumb_path, preview_path))

        if not requests:
            return

        # Call batch endpoint
        gpu_results: list[dict | None] = [None] * len(requests)
        _t0 = time.monotonic()
        _started_at = datetime.now(timezone.utc)
        _gpu_success = True
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(
                    f"{settings.monet_ml_service_url}/assets/generate/batch",
                    json={"items": requests},
                    headers=_build_headers(),
                )
                resp.raise_for_status()
                gpu_results = resp.json()
        except Exception:
            logger.warning("GPU asset batch failed — falling back to CPU for all items")
            _gpu_success = False
        await _record_timing("gpu_assets_batch", _started_at, int((time.monotonic() - _t0) * 1000), _gpu_success, len(requests))

        # Update DB; CPU-fallback for failures
        now = datetime.now(timezone.utc)
        async with async_session_factory() as session:
            async with session.begin():
                for i, (file_id, scan_job_id, thumb_path, preview_path) in enumerate(meta):
                    mf = await session.get(MediaFile, file_id)
                    if not mf:
                        continue

                    result = gpu_results[i] if i < len(gpu_results) else None
                    # Verify files actually landed — gpu-machine may not have the cache mounted
                    # and can return success while writing to an ephemeral overlay layer.
                    gpu_ok = (
                        result is not None
                        and not result.get("error")
                        and thumb_path.exists()
                        and preview_path.exists()
                    )

                    if not gpu_ok:
                        # CPU fallback
                        root = await session.get(RootFolder, mf.root_folder_id)
                        if root:
                            try:
                                from app.services.processor import generate_thumbnail_and_preview
                                abs_path = str(Path(root.path) / mf.path)
                                w, h = await generate_thumbnail_and_preview(
                                    abs_path, mf.media_type, mf.extension,
                                    thumb_path, preview_path,
                                    settings.monet_thumb_size,
                                    settings.monet_preview_max_width,
                                    settings.monet_preview_max_height,
                                    settings.monet_thumb_quality,
                                    settings.monet_preview_quality,
                                )
                                result = {"width": w, "height": h}
                            except Exception:
                                logger.exception("CPU fallback failed for %s", file_id)
                                mf.processed_at = now
                                mf.processing_error = "asset generation failed"
                                continue

                    thumb_rel = str(
                        thumb_path.relative_to(Path(settings.monet_cache_dir) / "thumbnails")
                    )
                    preview_rel = str(
                        preview_path.relative_to(Path(settings.monet_cache_dir) / "previews")
                    )
                    mf.thumbnail_path = thumb_rel
                    mf.preview_path = preview_rel
                    if result and result.get("width"):
                        mf.width = result["width"]
                    if result and result.get("height"):
                        mf.height = result["height"]
                    mf.processed_at = now

                    if scan_job_id:
                        try:
                            await session.execute(
                                update(ScanJob)
                                .where(ScanJob.id == uuid.UUID(scan_job_id))
                                .values(files_failed=ScanJob.files_failed + (0 if gpu_ok else 1))
                            )
                        except Exception:
                            pass

                    # Kick off ML analysis now that the preview exists
                    await redis.enqueue_job(
                        "ml_analyze_file",
                        str(file_id),
                        scan_job_id,
                        _queue_name="arq:ml-queue",
                    )
    finally:
        await redis.delete("assets:flush_lock")


# ---------------------------------------------------------------------------
# Video preview generation (GPU on ml-service, CPU fallback)
# ---------------------------------------------------------------------------


async def generate_video_preview(ctx: dict, file_id_str: str) -> None:
    """ARQ task: transcode a video to a web-optimised 1080p H.264/AAC MP4.

    First tries GPU NVENC via the ml-service /video/transcode endpoint.
    Falls back to local CPU ffmpeg (libx264) if the service is unreachable
    or returns an error.
    """
    file_id = uuid.UUID(file_id_str)

    async with async_session_factory() as session:
        async with session.begin():
            media_file = await session.get(MediaFile, file_id)
            if not media_file or media_file.is_deleted or media_file.media_type != "video":
                return

            root = await session.get(RootFolder, media_file.root_folder_id)
            if not root:
                return

            abs_src = str(Path(root.path) / media_file.path)
            stem = Path(media_file.filename).stem
            video_dir = Path(media_file.path).parent
            preview_rel = str(video_dir / "_monet_preview_videos" / f"{stem}_preview.mp4")
            abs_dst = Path(root.path) / preview_rel

            if media_file.video_preview_path and abs_dst.exists():
                return

            gpu_ok = await _try_gpu_transcode(abs_src, str(abs_dst))
            if not gpu_ok:
                try:
                    await _cpu_transcode(
                        abs_src,
                        abs_dst,
                        crf=settings.monet_video_preview_crf,
                        preset=settings.monet_video_preview_preset,
                    )
                except Exception:
                    logger.exception("CPU transcode fallback failed for %s", abs_src)
                    return

            media_file.video_preview_path = preview_rel
            media_file.video_preview_gpu = gpu_ok


async def _try_gpu_transcode(abs_src: str, abs_dst: str) -> bool:
    """POST to ml-service /video/transcode. Returns True on success."""
    if not settings.monet_ml_service_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=3600) as client:
            resp = await client.post(
                f"{settings.monet_ml_service_url}/video/transcode",
                json={
                    "src": abs_src,
                    "dst": abs_dst,
                    "crf": settings.monet_video_preview_crf,
                    "preset": "p5",
                },
                headers=_build_headers(),
            )
            resp.raise_for_status()
            return True
    except Exception:
        logger.warning(
            "GPU transcode unavailable for %s — falling back to CPU", abs_src,
            exc_info=True,
        )
        return False


# ---------------------------------------------------------------------------
# Self-healing: re-stage files whose ml_analyze_file ARQ job expired
# ---------------------------------------------------------------------------

_RESTAGE_LIMIT = 500  # max files pushed per run to avoid queue spikes


async def ml_restage_lost(ctx: dict) -> None:
    """Cron: re-push files that were ingested but never reached the ML staging queue.

    ml_analyze_file ARQ jobs have a 1-hour TTL. If the ml-worker was busy or
    down when they were enqueued, the jobs expire silently and the files are
    left with processed_at set but ai_analyzed_at NULL and no ml_error. This
    cron detects them (age > 10 min to avoid racing in-flight work) and pushes
    them back into ml:batch_staging so the next ml_flush_batch picks them up.
    """
    if not ctx.get("ml_configured"):
        return

    redis = ctx["redis"]

    async with async_session_factory() as session:
        result = await session.execute(
            select(MediaFile.id).where(
                MediaFile.is_deleted == False,  # noqa: E712
                MediaFile.processed_at.isnot(None),
                MediaFile.thumbnail_path.isnot(None),
                MediaFile.ai_analyzed_at.is_(None),
                MediaFile.ml_error.is_(None),
                MediaFile.processed_at < text("NOW() - INTERVAL '10 minutes'"),
            ).limit(_RESTAGE_LIMIT)
        )
        file_ids = [row.id for row in result.all()]

    if not file_ids:
        return

    pipe = redis.pipeline()
    for fid in file_ids:
        pipe.rpush(_STAGING_KEY, f"{fid}:")
    await pipe.execute()
    logger.info("ml_restage_lost: re-staged %d files into %s", len(file_ids), _STAGING_KEY)


# ---------------------------------------------------------------------------
# Worker settings
# ---------------------------------------------------------------------------


class MLWorkerSettings:
    """ML worker — fast features every 30s, captions every 5 minutes, face clustering nightly."""

    functions = [ml_analyze_file, ml_flush_batch, ml_flush_caption, cluster_faces, generate_video_preview, flush_gpu_assets, ml_restage_lost]
    cron_jobs = [
        cron(ml_flush_batch, second={0, 30}),
        cron(ml_flush_caption, second=0),  # every minute; lock prevents overlap
        cron(cluster_faces, hour=3, minute=0),  # nightly at 03:00
        cron(flush_gpu_assets, second={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        cron(ml_restage_lost, minute={0, 10, 20, 30, 40, 50}),  # every 10 minutes
    ]
    on_startup = ml_startup
    on_shutdown = ml_shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 16
    job_timeout = 3600  # video transcode can take up to ~1 h for long clips
    keep_result = 3600
    queue_name = "arq:ml-queue"
