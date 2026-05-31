from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
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

    # ML counters come from the latest scan job for this root folder.
    ml_job_result = await session.execute(
        select(ScanJob)
        .where(ScanJob.root_folder_id == root_folder_id)
        .order_by(ScanJob.started_at.desc())
        .limit(1)
    )
    latest_job = ml_job_result.scalar_one_or_none()
    ml_pending = latest_job.ml_files_pending if latest_job else 0
    ml_done = latest_job.ml_files_done if latest_job else 0
    ml_failed = latest_job.ml_files_failed if latest_job else 0
    ml_total = ml_pending + ml_done + ml_failed

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
        caption_pending=caption_pending,
    )
