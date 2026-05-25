from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.database import get_session
from app.models.db import MediaFile, RootFolder, User, UserRootPref
from app.models.schemas import FileResponse, PaginatedFiles

router = APIRouter()


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
    )


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


@router.get("", response_model=PaginatedFiles)
async def search(
    q: str | None = Query(default=None, description="Search term (filename, camera make/model)"),
    folder_id: uuid.UUID | None = Query(default=None),
    root_folder_id: uuid.UUID | None = Query(default=None),
    media_type: Literal["image", "video", "audio", "all"] = Query(default="all"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PaginatedFiles:
    """Search media files with filters. Respects user root visibility prefs."""
    visible_root_ids = await _get_user_visible_root_ids(current_user, session)
    if not visible_root_ids:
        return PaginatedFiles(items=[], total=0, page=page, page_size=page_size, pages=1)

    stmt = select(MediaFile).where(
        MediaFile.is_deleted == False,  # noqa: E712
        MediaFile.root_folder_id.in_(visible_root_ids),
    )

    # Text search across filename, camera_make, camera_model
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                MediaFile.filename.ilike(pattern),
                MediaFile.camera_make.ilike(pattern),
                MediaFile.camera_model.ilike(pattern),
            )
        )

    # Optional filters
    if folder_id:
        stmt = stmt.where(MediaFile.folder_id == folder_id)
    if root_folder_id:
        if root_folder_id not in visible_root_ids:
            return PaginatedFiles(items=[], total=0, page=page, page_size=page_size, pages=1)
        stmt = stmt.where(MediaFile.root_folder_id == root_folder_id)
    if media_type != "all":
        stmt = stmt.where(MediaFile.media_type == media_type)
    if date_from:
        stmt = stmt.where(MediaFile.taken_at >= date_from)
    if date_to:
        stmt = stmt.where(MediaFile.taken_at <= date_to)

    # Count
    count_result = await session.execute(
        select(func.count()).select_from(stmt.subquery())
    )
    total = count_result.scalar_one()

    # Sort by taken_at desc, then filename
    stmt = stmt.order_by(MediaFile.taken_at.desc().nullslast(), MediaFile.filename.asc())

    # Paginate
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
