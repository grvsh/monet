from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.database import get_session
from app.models.db import Folder, MediaFile, RootFolder, User, UserRootPref
from app.models.schemas import FileResponse, FolderResponse, PaginatedFiles

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


# NOTE: /by-path must be registered before /{folder_id} so FastAPI's literal match
# takes priority over the UUID path parameter.

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
