from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_admin
from app.database import get_session
from app.models.db import RootFolder, User
from app.models.schemas import RootFolderCreate, RootFolderResponse, RootFolderUpdate
from app.services.watcher import watcher_manager
from app.config import settings

router = APIRouter()


async def _on_file_change(path: str, event_type: str, root_folder_id: str) -> None:
    """Callback invoked by watchdog when a file changes under a root folder."""
    # Import here to avoid circular imports; this runs in the background
    from app.redis_client import get_redis
    from app.database import async_session_factory
    from app.models.db import RootFolder as RF
    from datetime import datetime, timezone
    from arq.connections import create_pool, RedisSettings

    if event_type == "deleted":
        # Mark file as deleted in DB
        from pathlib import Path as PPath
        from sqlalchemy import select, update
        from app.models.db import MediaFile
        rf_id = uuid.UUID(root_folder_id)
        async with async_session_factory() as session:
            async with session.begin():
                root = await session.get(RF, rf_id)
                if not root:
                    return
                abs_root = root.path
                rel = str(PPath(path).relative_to(abs_root)) if path.startswith(abs_root) else None
                if rel:
                    await session.execute(
                        update(MediaFile)
                        .where(MediaFile.root_folder_id == rf_id, MediaFile.path == rel)
                        .values(is_deleted=True, deleted_at=datetime.now(timezone.utc))
                    )
        return

    # For created/modified/moved, enqueue a single-file re-scan via ARQ
    try:
        arq_redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await arq_redis.enqueue_job(
            "scan_folder",
            root_folder_id,
            "",  # relative_path — will re-scan from the root (simple approach for v1)
            None,
            str(uuid.uuid4()),  # ephemeral scan job id
                    )
        await arq_redis.aclose()
    except Exception:
        pass  # Don't crash the watcher thread


@router.get("", response_model=list[RootFolderResponse])
async def list_root_folders(
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[RootFolderResponse]:
    """List all active root folders (all authenticated users)."""
    result = await session.execute(
        select(RootFolder)
        .where(RootFolder.is_active == True)  # noqa: E712
        .order_by(RootFolder.created_at)
    )
    roots = result.scalars().all()
    return [RootFolderResponse.model_validate(r) for r in roots]


@router.post("", response_model=RootFolderResponse, status_code=201)
async def create_root_folder(
    body: RootFolderCreate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RootFolderResponse:
    """Add a new root folder (admin only). Path must exist on disk."""
    from pathlib import Path as PPath

    # Validate path exists
    if not os.path.isdir(body.path):
        raise HTTPException(status_code=400, detail=f"Path does not exist or is not a directory: {body.path}")

    new_path = PPath(body.path).resolve()

    # Check for duplicate path
    existing_check = await session.execute(
        select(RootFolder).where(RootFolder.is_active == True)  # noqa: E712
    )
    active_roots = existing_check.scalars().all()

    for r in active_roots:
        if PPath(r.path).resolve() == new_path:
            raise HTTPException(status_code=409, detail="Root folder with this path already exists")

    # Detect ancestor / descendant relationships
    parent_root: RootFolder | None = None
    child_roots: list[RootFolder] = []

    for r in active_roots:
        r_path = PPath(r.path).resolve()
        if str(new_path).startswith(str(r_path) + "/"):
            # New folder is inside an existing root — it's a descendant
            parent_root = r
        elif str(r_path).startswith(str(new_path) + "/"):
            # Existing root is inside new folder — new is an ancestor
            child_roots.append(r)

    root = RootFolder(
        name=body.name,
        path=str(new_path),
        created_by=admin.id,
        parent_root_id=parent_root.id if parent_root else None,
    )
    session.add(root)
    await session.flush()

    # Re-parent existing child roots to the new ancestor
    for child in child_roots:
        child.parent_root_id = root.id

    await session.commit()
    await session.refresh(root)

    # Start watchdog observer (even for descendants — they may be watched independently)
    if settings.monet_watch_enabled:
        watcher_manager.start(
            str(root.id),
            root.path,
            _on_file_change,
            settings.monet_file_settle_seconds,
        )

    # Only scan if this is NOT a descendant (data already exists in parent's scan)
    if parent_root is None:
        try:
            from arq.connections import create_pool, RedisSettings
            from app.models.db import ScanJob

            job = ScanJob(
                root_folder_id=root.id,
                triggered_by=admin.id,
                trigger_type="auto",
                status="running",
                pending_folders=1,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)

            arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            await arq.enqueue_job("scan_folder", str(root.id), "", None, str(job.id))
            await arq.aclose()
        except Exception:
            pass  # Don't fail the add if scan enqueue fails

    return RootFolderResponse.model_validate(root)


@router.patch("/{root_folder_id}", response_model=RootFolderResponse)
async def update_root_folder(
    root_folder_id: uuid.UUID,
    body: RootFolderUpdate,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> RootFolderResponse:
    """Update name or path of a root folder (admin only)."""
    root = await session.get(RootFolder, root_folder_id)
    if not root:
        raise HTTPException(status_code=404, detail="Root folder not found")

    if body.name is not None:
        root.name = body.name
    if body.path is not None:
        if not os.path.isdir(body.path):
            raise HTTPException(
                status_code=400,
                detail=f"Path does not exist or is not a directory: {body.path}",
            )
        # Restart watcher on new path
        if settings.monet_watch_enabled:
            watcher_manager.stop(str(root.id))
        root.path = body.path
        if settings.monet_watch_enabled:
            watcher_manager.start(
                str(root.id),
                root.path,
                _on_file_change,
                settings.monet_file_settle_seconds,
            )

    await session.commit()
    await session.refresh(root)
    return RootFolderResponse.model_validate(root)


@router.delete("/{root_folder_id}", status_code=204)
async def delete_root_folder(
    root_folder_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a root folder (admin only). Cancels running scan jobs and stops the watchdog observer."""
    from sqlalchemy import update
    from datetime import datetime, timezone
    from app.models.db import ScanJob

    root = await session.get(RootFolder, root_folder_id)
    if not root:
        raise HTTPException(status_code=404, detail="Root folder not found")

    # Cancel any running or pending scan jobs for this root folder
    now = datetime.now(timezone.utc)
    await session.execute(
        update(ScanJob)
        .where(
            ScanJob.root_folder_id == root_folder_id,
            ScanJob.status.in_(["running", "pending"]),
        )
        .values(status="cancelled", completed_at=now)
    )

    # Hard-delete the root folder record
    await session.delete(root)
    await session.commit()

    # Stop the watchdog observer
    watcher_manager.stop(str(root_folder_id))
