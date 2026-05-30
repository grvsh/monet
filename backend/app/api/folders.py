from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.database import get_session
from app.models.db import Folder, MediaFile, RootFolder, User, UserRootPref

logger = logging.getLogger(__name__)
from app.models.schemas import FileResponse, FolderResponse, FolderTypeCounts, PaginatedFiles

router = APIRouter()


async def _get_user_visible_root_ids(
    user: User, session: AsyncSession
) -> list[uuid.UUID]:
    rf_result = await session.execute(
        select(RootFolder.id).where(RootFolder.is_active == True)  # noqa: E712
    )
    all_root_ids = [row[0] for row in rf_result.all()]

    prefs_result = await session.execute(
        select(UserRootPref).where(
            UserRootPref.user_id == user.id,
            UserRootPref.is_visible == False,  # noqa: E712
        )
    )
    hidden_ids = {p.root_folder_id for p in prefs_result.scalars().all()}
    return [rid for rid in all_root_ids if rid not in hidden_ids]


def _file_to_response(f: MediaFile) -> FileResponse:
    return FileResponse(
        id=f.id,
        folder_id=f.folder_id,
        root_folder_id=f.root_folder_id,
        filename=f.filename,
        extension=f.extension,
        media_type=f.media_type,
        mime_type=f.mime_type,
        is_raw=f.is_raw,
        width=f.width,
        height=f.height,
        duration_sec=f.duration_sec,
        taken_at=f.taken_at,
        camera_make=f.camera_make,
        camera_model=f.camera_model,
        has_gps=f.gps_lat is not None,
        has_thumbnail=f.thumbnail_path is not None,
        has_preview=f.preview_path is not None,
        size_bytes=f.size_bytes,
        thumbnail_url=f"/api/thumbnails/{f.id}",
        preview_url=f"/api/previews/{f.id}",
        lens_model=f.lens_model,
        location=f.location,
        trashed_at=f.deleted_at,
        missing_since=f.missing_since,
    )


# NOTE: /by-path and /search must be registered before /{folder_id} so FastAPI's
# literal match takes priority over the UUID path parameter.

@router.get("", response_model=list[FolderResponse])
async def list_root_level_folders(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[FolderResponse]:
    """Return root-level folders (parent_id IS NULL) for the user's visible roots."""
    visible_root_ids = await _get_user_visible_root_ids(current_user, session)
    if not visible_root_ids:
        return []

    result = await session.execute(
        select(Folder)
        .where(
            Folder.parent_id == None,  # noqa: E711
            Folder.root_folder_id.in_(visible_root_ids),
        )
        .order_by(Folder.root_folder_id, Folder.name)
    )
    folders = result.scalars().all()
    return [FolderResponse.model_validate(f) for f in folders]


@router.get("/search", response_model=list[FolderResponse])
async def search_folders(
    q: str = Query(default="", min_length=1, max_length=200),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[FolderResponse]:
    """Search folders by name (case-insensitive substring). Returns up to 60 results."""
    visible_root_ids = await _get_user_visible_root_ids(current_user, session)
    if not visible_root_ids:
        return []
    result = await session.execute(
        select(Folder)
        .where(
            Folder.root_folder_id.in_(visible_root_ids),
            Folder.name.ilike(f"%{q}%"),
        )
        .order_by(Folder.name)
        .limit(60)
    )
    folders = result.scalars().all()
    return [FolderResponse.model_validate(f) for f in folders]


@router.get("/by-path", response_model=FolderResponse)
async def get_folder_by_path(
    root_folder_id: uuid.UUID,
    path: str = "",
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FolderResponse:
    """Resolve a folder by root_folder_id + relative path. Used by frontend routing."""
    visible_root_ids = await _get_user_visible_root_ids(current_user, session)
    if root_folder_id not in visible_root_ids:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await session.execute(
        select(Folder).where(
            Folder.root_folder_id == root_folder_id,
            Folder.path == path,
        )
    )
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    return FolderResponse.model_validate(folder)


@router.get("/{folder_id}/children", response_model=list[FolderResponse])
async def list_child_folders(
    folder_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[FolderResponse]:
    """Return child folders of a given folder."""
    folder = await session.get(Folder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    visible_root_ids = await _get_user_visible_root_ids(current_user, session)
    if folder.root_folder_id not in visible_root_ids:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await session.execute(
        select(Folder)
        .where(Folder.parent_id == folder_id)
        .order_by(Folder.name)
    )
    children = result.scalars().all()
    return [FolderResponse.model_validate(c) for c in children]


@router.get("/{folder_id}/files", response_model=PaginatedFiles)
async def list_folder_files(
    folder_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    sort: Literal["taken_at", "filename", "size_bytes"] = Query(default="taken_at"),
    order: Literal["asc", "desc"] = Query(default="desc"),
    media_type: Literal["image", "video", "audio", "all"] = Query(default="all"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PaginatedFiles:
    """Return paginated active (non-trashed, non-missing) media files for a folder."""
    folder = await session.get(Folder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    visible_root_ids = await _get_user_visible_root_ids(current_user, session)
    if folder.root_folder_id not in visible_root_ids:
        raise HTTPException(status_code=403, detail="Access denied")

    stmt = select(MediaFile).where(
        MediaFile.folder_id == folder_id,
        MediaFile.is_deleted == False,  # noqa: E712
        MediaFile.missing_since.is_(None),
    )
    if media_type != "all":
        stmt = stmt.where(MediaFile.media_type == media_type)

    sort_col = {
        "taken_at": MediaFile.taken_at,
        "filename": MediaFile.filename,
        "size_bytes": MediaFile.size_bytes,
    }[sort]
    if order == "desc":
        stmt = stmt.order_by(sort_col.desc().nullslast())
    else:
        stmt = stmt.order_by(sort_col.asc().nullsfirst())

    count_result = await session.execute(
        select(func.count()).select_from(stmt.subquery())
    )
    total = count_result.scalar_one()

    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)
    result = await session.execute(stmt)
    files = result.scalars().all()

    pages = max(1, (total + page_size - 1) // page_size)
    return PaginatedFiles(
        items=[_file_to_response(f) for f in files],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/{folder_id}/type-counts", response_model=FolderTypeCounts)
async def get_folder_type_counts(
    folder_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FolderTypeCounts:
    """Return counts of active files per media type for a folder."""
    folder = await session.get(Folder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    visible_root_ids = await _get_user_visible_root_ids(current_user, session)
    if folder.root_folder_id not in visible_root_ids:
        raise HTTPException(status_code=403, detail="Access denied")

    base = (
        select(MediaFile.media_type, func.count().label("cnt"))
        .where(
            MediaFile.folder_id == folder_id,
            MediaFile.is_deleted == False,  # noqa: E712
            MediaFile.missing_since.is_(None),
        )
        .group_by(MediaFile.media_type)
    )
    result = await session.execute(base)
    counts: dict[str, int] = {row.media_type: row.cnt for row in result.all()}
    return FolderTypeCounts(
        image=counts.get("image", 0),
        video=counts.get("video", 0),
        audio=counts.get("audio", 0),
    )


@router.get("/{folder_id}/missing-files", response_model=list[FileResponse])
async def list_folder_missing_files(
    folder_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[FileResponse]:
    """Return files that disappeared from disk (externally moved/deleted) for a folder."""
    folder = await session.get(Folder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    visible_root_ids = await _get_user_visible_root_ids(current_user, session)
    if folder.root_folder_id not in visible_root_ids:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await session.execute(
        select(MediaFile)
        .where(
            MediaFile.folder_id == folder_id,
            MediaFile.is_deleted == False,  # noqa: E712
            MediaFile.missing_since.isnot(None),
        )
        .order_by(MediaFile.missing_since.desc())
    )
    files = result.scalars().all()
    return [_file_to_response(f) for f in files]


@router.get("/{folder_id}/trashed-files", response_model=list[FileResponse])
async def list_folder_trashed_files(
    folder_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[FileResponse]:
    """Return user-trashed files for a folder."""
    folder = await session.get(Folder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    visible_root_ids = await _get_user_visible_root_ids(current_user, session)
    if folder.root_folder_id not in visible_root_ids:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await session.execute(
        select(MediaFile)
        .where(
            MediaFile.folder_id == folder_id,
            MediaFile.is_deleted == True,  # noqa: E712
        )
        .order_by(MediaFile.deleted_at.desc())
    )
    files = result.scalars().all()
    return [_file_to_response(f) for f in files]


@router.get("/{folder_id}/disk-stats")
async def get_folder_disk_stats(
    folder_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return the count of files on disk in this folder (non-recursive)."""
    folder = await session.get(Folder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    root = await session.get(RootFolder, folder.root_folder_id)
    if not root:
        raise HTTPException(status_code=404, detail="Root folder not found")

    abs_path = Path(root.path) / folder.path
    try:
        file_count = sum(1 for e in os.scandir(abs_path) if e.is_file())
    except (FileNotFoundError, PermissionError):
        file_count = 0

    return {"file_count": file_count}


@router.post("/{folder_id}/remove-from-monet", status_code=204)
async def remove_folder_from_monet(
    folder_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Remove a folder from Monet's library without touching disk."""
    folder = await session.get(Folder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    root = await session.get(RootFolder, folder.root_folder_id)
    if root and current_user.role != "admin" and root.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="You don't have permission to remove this folder")

    if folder.parent_id:
        parent = await session.get(Folder, folder.parent_id)
        if parent:
            parent.child_folder_count = max(0, parent.child_folder_count - 1)

    await session.delete(folder)
    await session.commit()


@router.delete("/{folder_id}", status_code=204)
async def delete_empty_folder_from_disk(
    folder_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete an empty folder from disk and remove it from the library."""
    if not current_user.allow_disk_deletion:
        raise HTTPException(status_code=403, detail="Disk deletion is not enabled for your account")

    folder = await session.get(Folder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    root = await session.get(RootFolder, folder.root_folder_id)
    if root and current_user.role != "admin" and root.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="You don't have permission to delete this folder")

    file_count = await session.scalar(
        select(func.count()).where(MediaFile.folder_id == folder_id)
    )
    child_count = await session.scalar(
        select(func.count()).where(Folder.parent_id == folder_id)
    )
    if file_count or child_count:
        raise HTTPException(status_code=409, detail="Folder is not empty")

    abs_path = Path(root.path) / folder.path
    try:
        os.rmdir(abs_path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.error("Failed to delete folder %s from disk: %s", abs_path, e)
        raise HTTPException(status_code=500, detail=f"Could not delete folder from disk: {e}")

    if folder.parent_id:
        parent = await session.get(Folder, folder.parent_id)
        if parent:
            parent.child_folder_count = max(0, parent.child_folder_count - 1)

    await session.delete(folder)
    await session.commit()
