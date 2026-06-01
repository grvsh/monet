from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import get_current_user, require_admin
from app.database import get_session
from app.models.db import MediaFile, RootFolder, ScanJob, User
from app.models.schemas import ScanEnqueueResponse, ScanJobResponse, ScanStatusResponse, ProcessingStatusResponse, FailedFileInfo
from app.redis_client import get_redis

router = APIRouter()


async def _enqueue_root_scan(
    root: RootFolder,
    trigger_user_id: uuid.UUID | None,
    trigger_type: str,
    session: AsyncSession,
) -> ScanJob:
    """Create a ScanJob row and enqueue the ARQ scan_folder task."""
    job = ScanJob(
        root_folder_id=root.id,
        triggered_by=trigger_user_id,
        trigger_type=trigger_type,
        status="running",
        pending_folders=1,
    )
    session.add(job)
    await session.flush()  # Get the generated ID

    # Enqueue via ARQ
    try:
        from arq.connections import create_pool, RedisSettings
        from app.config import settings

        arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await arq.enqueue_job(
            "scan_folder",
            str(root.id),
            "",           # relative_path (root level)
            None,         # parent_folder_id
            str(job.id),
        )
        await arq.aclose()
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
        job.completed_at = datetime.now(timezone.utc)

    return job


@router.post("/scan", response_model=ScanEnqueueResponse, status_code=202)
async def scan_all(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ScanEnqueueResponse:
    """Enqueue a scan for all active root folders."""
    result = await session.execute(
        select(RootFolder).where(RootFolder.is_active == True)  # noqa: E712
    )
    roots = result.scalars().all()

    if not roots:
        raise HTTPException(status_code=404, detail="No active root folders configured")

    jobs = []
    for root in roots:
        job = await _enqueue_root_scan(root, admin.id, "manual", session)
        jobs.append(job)
    await session.commit()

    return ScanEnqueueResponse(
        scan_job_ids=[j.id for j in jobs],
        message=f"Enqueued scan for {len(jobs)} root folder(s)",
    )


@router.post("/scan/{root_folder_id}", response_model=ScanEnqueueResponse, status_code=202)
async def scan_one(
    root_folder_id: uuid.UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ScanEnqueueResponse:
    """Enqueue a scan for a single root folder."""
    root = await session.get(RootFolder, root_folder_id)
    if not root:
        raise HTTPException(status_code=404, detail="Root folder not found")
    if not root.is_active:
        raise HTTPException(status_code=400, detail="Root folder is not active")

    job = await _enqueue_root_scan(root, admin.id, "manual", session)
    await session.commit()

    return ScanEnqueueResponse(
        scan_job_ids=[job.id],
        message=f"Enqueued scan for root folder '{root.name}'",
    )


@router.get("/status", response_model=ScanStatusResponse)
async def scan_status_all(
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ScanStatusResponse:
    """Return the latest scan job per root folder."""
    # Get the latest scan job for each root folder using a subquery approach
    result = await session.execute(
        select(ScanJob)
        .order_by(ScanJob.root_folder_id, ScanJob.started_at.desc())
    )
    all_jobs = result.scalars().all()

    # Deduplicate: keep only the latest per root_folder_id
    seen: set[uuid.UUID | None] = set()
    latest_jobs: list[ScanJob] = []
    for job in all_jobs:
        key = job.root_folder_id
        if key not in seen:
            seen.add(key)
            latest_jobs.append(job)

    return ScanStatusResponse(
        jobs=[ScanJobResponse.model_validate(j) for j in latest_jobs]
    )


@router.get("/status/{root_folder_id}", response_model=ScanJobResponse)
async def scan_status_root(
    root_folder_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ScanJobResponse:
    """Return the latest scan job for a specific root folder."""
    result = await session.execute(
        select(ScanJob)
        .where(ScanJob.root_folder_id == root_folder_id)
        .order_by(ScanJob.started_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="No scan job found for this root folder")

    return ScanJobResponse.model_validate(job)


@router.get("/processing-status/{root_folder_id}", response_model=ProcessingStatusResponse)
async def processing_status(
    root_folder_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    redis=Depends(get_redis),
) -> ProcessingStatusResponse:
    """Return asset processing and ML analysis progress for a root folder."""
    total_result = await session.execute(
        select(func.count()).where(
            MediaFile.root_folder_id == root_folder_id,
            MediaFile.is_deleted == False,  # noqa: E712
        )
    )
    total = total_result.scalar_one()

    processed_result = await session.execute(
        select(func.count()).where(
            MediaFile.root_folder_id == root_folder_id,
            MediaFile.is_deleted == False,  # noqa: E712
            MediaFile.processed_at.isnot(None),
        )
    )
    processed = processed_result.scalar_one()

    failed_result = await session.execute(
        select(MediaFile.id, MediaFile.path, MediaFile.processing_error).where(
            MediaFile.root_folder_id == root_folder_id,
            MediaFile.is_deleted == False,  # noqa: E712
            MediaFile.processing_error.isnot(None),
        )
    )
    failed_rows = failed_result.all()
    failed_files = [
        FailedFileInfo(id=row.id, path=row.path, error=row.processing_error)
        for row in failed_rows
    ]

    # ML counters derived from MediaFile state — authoritative and immune to
    # the double-increment bug that inflated the scan job's ml_files_done counter.
    ml_done_result = await session.execute(
        select(func.count()).where(
            MediaFile.root_folder_id == root_folder_id,
            MediaFile.is_deleted == False,  # noqa: E712
            MediaFile.ai_analyzed_at.isnot(None),
        )
    )
    ml_done = ml_done_result.scalar_one()
    ml_failed = 0  # set below from ml_failed_files

    # Pending: use the scan job counter clamped to ≥0 for in-progress display.
    ml_job_result = await session.execute(
        select(ScanJob)
        .where(ScanJob.root_folder_id == root_folder_id)
        .order_by(ScanJob.started_at.desc())
        .limit(1)
    )
    latest_job = ml_job_result.scalar_one_or_none()
    ml_pending = max(0, latest_job.ml_files_pending if latest_job else 0)

    # Per-file ML failure details.
    ml_failed_result = await session.execute(
        select(MediaFile.id, MediaFile.path, MediaFile.ml_error).where(
            MediaFile.root_folder_id == root_folder_id,
            MediaFile.is_deleted == False,  # noqa: E712
            MediaFile.ml_error.isnot(None),
        )
    )
    ml_failed_files = [
        FailedFileInfo(id=row.id, path=row.path, error=row.ml_error)
        for row in ml_failed_result.all()
    ]
    ml_failed = len(ml_failed_files)
    ml_total = ml_done + ml_pending + ml_failed

    # Caption done — count of files with a caption written.
    caption_done_result = await session.execute(
        select(func.count()).where(
            MediaFile.root_folder_id == root_folder_id,
            MediaFile.is_deleted == False,  # noqa: E712
            MediaFile.caption.isnot(None),
        )
    )
    caption_done = caption_done_result.scalar_one()

    # Caption queue depth — global Redis list, not per root folder.
    # Show only when ML is configured (key won't exist otherwise).
    caption_pending = 0
    if settings.monet_ml_service_url:
        caption_pending = await redis.llen("ml:caption_staging") or 0

    return ProcessingStatusResponse(
        total=total,
        processed=processed,
        pending=total - processed,
        failed=len(failed_files),
        failed_files=failed_files,
        ml_total=ml_total,
        ml_done=ml_done,
        ml_pending=ml_pending,
        ml_failed=ml_failed,
        ml_failed_files=ml_failed_files,
        caption_pending=caption_pending,
        caption_done=caption_done,
    )


@router.post("/retry-ml-failed/{root_folder_id}", dependencies=[Depends(require_admin)])
async def retry_ml_failed(
    root_folder_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    redis=Depends(get_redis),
) -> dict:
    """Clear ml_error on failed files and re-enqueue them for ML analysis."""
    result = await session.execute(
        select(MediaFile.id).where(
            MediaFile.root_folder_id == root_folder_id,
            MediaFile.is_deleted == False,  # noqa: E712
            MediaFile.ml_error.isnot(None),
        )
    )
    file_ids = [row.id for row in result.all()]
    if not file_ids:
        return {"queued": 0}

    await session.execute(
        update(MediaFile)
        .where(MediaFile.id.in_(file_ids))
        .values(ml_error=None)
    )
    await session.commit()

    latest_job_result = await session.execute(
        select(ScanJob)
        .where(ScanJob.root_folder_id == root_folder_id)
        .order_by(ScanJob.started_at.desc())
        .limit(1)
    )
    latest_job = latest_job_result.scalar_one_or_none()
    scan_job_id_str = str(latest_job.id) if latest_job else ""

    for file_id in file_ids:
        await redis.rpush("ml:batch_staging", f"{file_id}:{scan_job_id_str}")

    if latest_job:
        await session.execute(
            update(ScanJob)
            .where(ScanJob.id == latest_job.id)
            .values(
                ml_files_pending=ScanJob.ml_files_pending + len(file_ids),
                ml_files_failed=ScanJob.ml_files_failed - len(file_ids),
            )
        )
        await session.commit()

    return {"queued": len(file_ids)}
