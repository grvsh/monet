from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import and_, select, update

logger = logging.getLogger(__name__)

from app.config import settings
from app.database import async_session_factory
from app.models.db import FileMetadata, MediaFile, RootFolder, ScanJob
from app.services.indexer import get_or_create_folder
from app.services.media import get_media_type, is_raw, thumbnail_cache_path, preview_cache_path
from app.services.metadata import extract_metadata as _extract_metadata, parse_denormalized
from app.services.processor import generate_thumbnail_and_preview


def _ml_features_stale(ai_versions: dict | None, manifest: dict) -> bool:
    """Return True if any ML feature is missing or was produced by an older model version."""
    if not ai_versions:
        return True
    return any(
        ai_versions.get(feature) != meta["version"]
        for feature, meta in manifest.items()
    )


async def scan_folder(
    ctx: dict,
    root_folder_id_str: str,
    relative_path: str,
    parent_folder_id_str: str | None,
    scan_job_id_str: str,
) -> None:
    """ARQ task: scan one directory level within a root folder.

    Upserts folder and media file rows, enqueues child folder scans and
    per-file metadata/asset jobs, updates the ScanJob progress counters.
    """
    root_folder_id = uuid.UUID(root_folder_id_str)
    scan_job_id = uuid.UUID(scan_job_id_str)
    parent_folder_id = uuid.UUID(parent_folder_id_str) if parent_folder_id_str else None

    try:
        async with async_session_factory() as session:
            async with session.begin():
                # Bail out immediately if the scan job was cancelled or already finished
                scan_job = await session.get(ScanJob, scan_job_id)
                if not scan_job or scan_job.status not in ("running", "pending"):
                    return

                root = await session.get(RootFolder, root_folder_id)
                if not root or not root.is_active:
                    return

                # Resolve the absolute path for this folder level
                if relative_path:
                    abs_path = str(Path(root.path) / relative_path)
                else:
                    abs_path = root.path

                folder_name = Path(abs_path).name if relative_path else root.name

                folder = await get_or_create_folder(
                    session,
                    root_folder_id,
                    relative_path or "",
                    folder_name,
                    parent_folder_id,
                )
                folder.indexed_at = datetime.now(timezone.utc)

                # Mark the root folder as scanned when processing its top level
                if not relative_path:
                    root.last_scanned_at = datetime.now(timezone.utc)

                # Scan the directory
                try:
                    entries = list(os.scandir(abs_path))
                except PermissionError:
                    return

                subdirs = [
                    e for e in entries
                    if e.is_dir(follow_symlinks=False)
                    and not e.name.startswith('.')
                    and not e.name.startswith('_monet_preview')
                ]
                file_entries = [
                    e for e in entries
                    if e.is_file(follow_symlinks=False)
                    and not e.name.startswith('.')
                ]

                files_found = 0
                files_new = 0
                files_skipped = 0
                found_relative_paths: set[str] = set()

                # Batch-fetch all existing records for this folder in one query.
                # Done before the per-file loop so unchanged files can skip
                # the expensive magic.from_file() call entirely.
                existing_rows = await session.execute(
                    select(MediaFile).where(MediaFile.folder_id == folder.id)
                )
                existing_by_path: dict[str, MediaFile] = {
                    f.path: f for f in existing_rows.scalars().all()
                }

                arq = ctx.get("redis")
                needs_processing_ids: list[uuid.UUID] = []
                needs_ml_ids: list[uuid.UUID] = []
                new_file_rows: list[dict] = []

                # Fetch the ML manifest once per scan_folder call so we can
                # detect stale/missing ML features on already-processed files.
                # Published to Redis by the ml-worker on startup; None when ML
                # is not configured or the ml-worker hasn't started yet.
                ml_manifest: dict | None = None
                if settings.monet_ml_service_url and arq:
                    raw = await arq.get("ml:manifest")
                    if raw:
                        ml_manifest = json.loads(raw)

                for entry in file_entries:
                    ext = Path(entry.path).suffix.lower().lstrip(".")
                    st = entry.stat()
                    mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
                    size = st.st_size
                    rel = str(Path(relative_path) / entry.name) if relative_path else entry.name

                    existing = existing_by_path.get(rel)

                    # For unchanged known files, skip magic entirely — use stored values.
                    if existing is not None and existing.mtime == mtime:
                        found_relative_paths.add(rel)
                        if existing.missing_since is not None:
                            existing.missing_since = None
                        if existing.processed_at is not None:
                            files_found += 1
                            files_skipped += 1
                            # Even though thumbnails are current, ML features may be
                            # missing (first scan after ML was added) or stale (model
                            # version changed). Check manifest and re-enqueue if needed.
                            if ml_manifest and _ml_features_stale(existing.ai_versions, ml_manifest):
                                needs_ml_ids.append(existing.id)
                        else:
                            files_found += 1
                            needs_processing_ids.append(existing.id)
                        continue

                    # New or modified file — check extension then call magic.
                    result = get_media_type(entry.path)
                    if result is None:
                        continue
                    media_type, mime_type = result
                    found_relative_paths.add(rel)

                    # At this point existing is either None (new file) or has a
                    # changed mtime (modified file) — unchanged files were handled above.
                    if existing is not None:
                        # File modified — clear missing flag, reset for reprocessing
                        if existing.missing_since is not None:
                            existing.missing_since = None
                        existing.mtime = mtime
                        existing.processed_at = None
                        existing.is_deleted = False
                        existing.deleted_at = None
                        existing.size_bytes = size
                        files_found += 1
                        needs_processing_ids.append(existing.id)
                    else:
                        # Generate UUID client-side so we know the ID without re-fetching
                        new_id = uuid.uuid4()
                        new_file_rows.append(dict(
                            id=new_id,
                            folder_id=folder.id,
                            root_folder_id=root_folder_id,
                            path=rel,
                            filename=Path(entry.path).name,
                            extension=ext,
                            size_bytes=size,
                            mtime=mtime,
                            media_type=media_type,
                            mime_type=mime_type,
                            is_raw=is_raw(ext),
                        ))
                        needs_processing_ids.append(new_id)
                        files_found += 1
                        files_new += 1

                # Bulk-insert new files in a single statement — no re-fetch needed
                if new_file_rows:
                    from sqlalchemy.dialects.postgresql import insert as pg_insert
                    await session.execute(
                        pg_insert(MediaFile)
                        .values(new_file_rows)
                        .on_conflict_do_nothing()
                    )
                else:
                    await session.flush()

                if arq:
                    for file_id in needs_processing_ids:
                        await arq.enqueue_job(
                            "extract_metadata",
                            str(file_id),
                            scan_job_id_str,
                            _queue_name="arq:asset-queue",
                        )
                        await arq.enqueue_job(
                            "generate_assets",
                            str(file_id),
                            scan_job_id_str,
                            _queue_name="arq:asset-queue",
                        )
                    # ML-only enqueue for files whose thumbnails are current but
                    # whose ML features are missing or stale (e.g. existing library
                    # on first ML-enabled scan, or after a model version upgrade).
                    for file_id in needs_ml_ids:
                        await arq.enqueue_job(
                            "ml_analyze_file",
                            str(file_id),
                            scan_job_id_str,
                            _queue_name="arq:ml-queue",
                        )

                now = datetime.now(timezone.utc)

                # Mark files that disappeared from disk as externally missing.
                # We already have existing_by_path — no second DB query needed.
                files_deleted = 0
                for path, mf in existing_by_path.items():
                    if path not in found_relative_paths and not mf.is_deleted and mf.missing_since is None:
                        mf.missing_since = now
                        files_deleted += 1

                # Update cached counts on the folder
                folder.file_count = files_found
                folder.child_folder_count = len(subdirs)

                # Enqueue child folder scans first so we know the count
                n_enqueued = 0
                arq = ctx.get("redis")
                if arq:
                    for subdir in subdirs:
                        if relative_path:
                            sub_rel = str(Path(relative_path) / subdir.name)
                        else:
                            sub_rel = subdir.name
                        await arq.enqueue_job(
                            "scan_folder",
                            root_folder_id_str,
                            sub_rel,
                            str(folder.id),
                            scan_job_id_str,
                        )
                        n_enqueued += 1

                # Update ScanJob counters atomically.
                # pending_folders: subtract 1 (this folder done), add n_enqueued (children queued).
                # When pending_folders reaches 0 the entire tree has been scanned.
                result = await session.execute(
                    update(ScanJob)
                    .where(ScanJob.id == scan_job_id)
                    .values(
                        folders_scanned=ScanJob.folders_scanned + 1,
                        files_found=ScanJob.files_found + files_found,
                        files_new=ScanJob.files_new + files_new,
                        files_skipped=ScanJob.files_skipped + files_skipped,
                        files_deleted=ScanJob.files_deleted + files_deleted,
                        folders_found=ScanJob.folders_found + len(subdirs),
                        pending_folders=ScanJob.pending_folders - 1 + n_enqueued,
                    )
                    .returning(ScanJob.pending_folders)
                )
                new_pending = result.scalar_one()
                if new_pending == 0:
                    await session.execute(
                        update(ScanJob)
                        .where(ScanJob.id == scan_job_id, ScanJob.status == "running")
                        .values(status="completed", completed_at=now)
                    )
    except Exception:
        logger.exception("scan_folder crashed for root=%s path=%r", root_folder_id_str, relative_path)
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(ScanJob)
                    .where(ScanJob.id == scan_job_id, ScanJob.status == "running")
                    .values(
                        status="failed",
                        completed_at=datetime.now(timezone.utc),
                        error_message=f"Task crashed scanning '{relative_path or '/'}'",
                    )
                )
        raise


async def extract_metadata(ctx: dict, file_id_str: str, scan_job_id_str: str | None = None) -> None:
    """ARQ task: run ExifTool on a file and persist the results to the DB."""
    file_id = uuid.UUID(file_id_str)

    async with async_session_factory() as session:
        async with session.begin():
            media_file = await session.get(MediaFile, file_id)
            if not media_file or media_file.is_deleted:
                return

            root = await session.get(RootFolder, media_file.root_folder_id)
            if not root:
                return

            abs_path = str(Path(root.path) / media_file.path)

            try:
                et = ctx.get("exiftool")
                meta = await _extract_metadata(abs_path, et)
            except Exception:
                logger.exception("extract_metadata failed for %s", abs_path)
                if scan_job_id_str:
                    await session.execute(
                        update(ScanJob)
                        .where(ScanJob.id == uuid.UUID(scan_job_id_str))
                        .values(files_failed=ScanJob.files_failed + 1)
                    )
                return

            # Upsert the file_metadata JSONB row
            stmt = select(FileMetadata).where(FileMetadata.file_id == file_id)
            result = await session.execute(stmt)
            fm = result.scalar_one_or_none()

            if fm:
                fm.data = meta
            else:
                fm = FileMetadata(file_id=file_id, data=meta)
                session.add(fm)

            # Update denormalized fields on media_files
            fields = parse_denormalized(meta)
            for key, value in fields.items():
                if hasattr(media_file, key) and value is not None:
                    setattr(media_file, key, value)

            # Reverse-geocode GPS coordinates if not already stored
            if (
                media_file.gps_lat is not None
                and media_file.gps_lon is not None
                and not media_file.location
            ):
                from app.services.geocoder import reverse_geocode
                location = await reverse_geocode(media_file.gps_lat, media_file.gps_lon)
                if location:
                    media_file.location = location


_RAW_EXTENSIONS = frozenset(
    {"cr2", "cr3", "nef", "nrw", "dng", "orf", "raf", "arw", "rw2", "pef", "srw"}
)
_HEIF_EXTENSIONS = frozenset({"heic", "heif"})


async def generate_assets(ctx: dict, file_id_str: str, scan_job_id_str: str | None = None) -> None:
    """ARQ task: generate thumbnail and preview JPEGs and update the DB row.

    Standard images are pushed to the GPU staging key and processed in batches
    by flush_gpu_assets (ml-worker cron, every 5 s).  Videos, RAW, HEIF, and
    audio fall through to local CPU processing immediately.
    """
    file_id = uuid.UUID(file_id_str)

    async with async_session_factory() as session:
        async with session.begin():
            media_file = await session.get(MediaFile, file_id)
            if not media_file or media_file.is_deleted:
                return

            if media_file.processed_at is not None:
                return

            root = await session.get(RootFolder, media_file.root_folder_id)
            if not root:
                return

            ext = media_file.extension.lower().lstrip(".")
            is_gpu_image = (
                media_file.media_type == "image"
                and ext not in _RAW_EXTENSIONS
                and ext not in _HEIF_EXTENSIONS
                and settings.monet_ml_service_url
            )

            arq = ctx.get("redis")

            if is_gpu_image and arq:
                # Defer to GPU batch pipeline — flush_gpu_assets will update the DB.
                await arq.rpush(
                    "assets:gpu_staging",
                    f"{file_id_str}:{scan_job_id_str or ''}",
                )
                return

            # ── CPU path (videos, RAW, HEIF, audio, or no ml-service) ──────────
            abs_path = str(Path(root.path) / media_file.path)
            thumb_path = thumbnail_cache_path(file_id, settings.monet_cache_dir)
            preview_path = preview_cache_path(file_id, settings.monet_cache_dir)

            try:
                w, h = await generate_thumbnail_and_preview(
                    abs_path,
                    media_file.media_type,
                    media_file.extension,
                    thumb_path,
                    preview_path,
                    settings.monet_thumb_size,
                    settings.monet_preview_max_width,
                    settings.monet_preview_max_height,
                    settings.monet_thumb_quality,
                    settings.monet_preview_quality,
                )
            except Exception as exc:
                logger.exception("generate_assets failed for %s", abs_path)
                media_file.processed_at = datetime.now(timezone.utc)
                media_file.processing_error = str(exc) or type(exc).__name__
                if scan_job_id_str:
                    await session.execute(
                        update(ScanJob)
                        .where(ScanJob.id == uuid.UUID(scan_job_id_str))
                        .values(files_failed=ScanJob.files_failed + 1)
                    )
                return

            thumb_rel = str(
                thumb_path.relative_to(Path(settings.monet_cache_dir) / "thumbnails")
            )
            preview_rel = str(
                preview_path.relative_to(Path(settings.monet_cache_dir) / "previews")
            )

            media_file.thumbnail_path = thumb_rel
            media_file.preview_path = preview_rel
            if w is not None:
                media_file.width = w
            if h is not None:
                media_file.height = h
            media_file.processed_at = datetime.now(timezone.utc)

            if arq and settings.monet_ml_service_url:
                await arq.enqueue_job(
                    "ml_analyze_file",
                    str(file_id),
                    scan_job_id_str,
                    _queue_name="arq:ml-queue",
                )

            if arq and media_file.media_type == "video" and settings.monet_video_preview_enabled:
                await arq.enqueue_job(
                    "generate_video_preview",
                    str(file_id),
                    _queue_name="arq:ml-queue",
                )


async def geocode_missing(ctx: dict) -> None:
    """ARQ task: reverse-geocode all GPS-tagged files that have no location yet."""
    from app.services.geocoder import reverse_geocode

    async with async_session_factory() as session:
        stmt = select(MediaFile.id, MediaFile.gps_lat, MediaFile.gps_lon).where(
            and_(
                MediaFile.gps_lat.isnot(None),
                MediaFile.location.is_(None),
                MediaFile.is_deleted == False,  # noqa: E712
            )
        )
        result = await session.execute(stmt)
        rows = result.all()

    for file_id, lat, lon in rows:
        location = await reverse_geocode(lat, lon)
        if location:
            async with async_session_factory() as session:
                async with session.begin():
                    f = await session.get(MediaFile, file_id)
                    if f:
                        f.location = location


async def purge_old_trash(ctx: dict) -> None:
    """ARQ cron task: permanently delete files trashed more than 30 days ago."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    async with async_session_factory() as session:
        stmt = select(MediaFile).where(
            MediaFile.is_deleted == True,  # noqa: E712
            MediaFile.deleted_at <= cutoff,
        )
        result = await session.execute(stmt)
        files = result.scalars().all()

        for f in files:
            # Remove cached assets
            for cache_path in (f.thumbnail_path, f.preview_path):
                if cache_path:
                    try:
                        Path(cache_path).unlink(missing_ok=True)
                    except OSError:
                        pass
            await session.delete(f)

        await session.commit()
