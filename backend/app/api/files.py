from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.database import get_session
from app.models.db import FileMetadata, Folder, MediaFile, RootFolder, User, UserRootPref
from app.models.schemas import FileDetailResponse, FileResponse, PaginatedFiles

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
        trashed_at=f.deleted_at,
        missing_since=f.missing_since,
    )


async def _get_user_visible_root_ids(user: User, session: AsyncSession) -> list[uuid.UUID]:
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


class BulkDeleteRequest(BaseModel):
    file_ids: list[uuid.UUID]


class BulkRestoreRequest(BaseModel):
    file_ids: list[uuid.UUID]


# NOTE: literal routes (/trash, /bulk-delete, /bulk-restore) must come before
# the /{file_id} path-param route so FastAPI matches them correctly.

@router.get("/trash", response_model=PaginatedFiles)
async def list_trash(
    page: int = 1,
    page_size: int = 200,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PaginatedFiles:
    """Return all trashed files visible to this user."""
    visible_root_ids = await _get_user_visible_root_ids(current_user, session)
    if not visible_root_ids:
        return PaginatedFiles(items=[], total=0, page=page, page_size=page_size, pages=1)

    stmt = select(MediaFile).where(
        MediaFile.is_deleted == True,  # noqa: E712
        MediaFile.root_folder_id.in_(visible_root_ids),
    ).order_by(MediaFile.deleted_at.desc())

    from sqlalchemy import func
    count_result = await session.execute(
        select(func.count()).select_from(stmt.subquery())
    )
    total = count_result.scalar_one()

    offset = (page - 1) * page_size
    result = await session.execute(stmt.offset(offset).limit(page_size))
    files = result.scalars().all()

    pages = max(1, (total + page_size - 1) // page_size)
    return PaginatedFiles(
        items=[_file_to_response(f) for f in files],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.post("/bulk-delete")
async def bulk_delete_files(
    body: BulkDeleteRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not body.file_ids:
        return {"trashed": 0}
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(MediaFile).where(
            MediaFile.id.in_(body.file_ids),
            MediaFile.is_deleted == False,  # noqa: E712
        )
    )
    files = result.scalars().all()
    for f in files:
        f.is_deleted = True
        f.deleted_at = now
    await session.commit()
    return {"trashed": len(files)}


@router.post("/bulk-trash-missing")
async def bulk_trash_missing_files(
    body: BulkDeleteRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Move externally-missing files into the user trash."""
    if not body.file_ids:
        return {"trashed": 0}
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(MediaFile).where(
            MediaFile.id.in_(body.file_ids),
            MediaFile.missing_since.isnot(None),
        )
    )
    files = result.scalars().all()
    for f in files:
        f.is_deleted = True
        f.deleted_at = now
        f.missing_since = None
    await session.commit()
    return {"trashed": len(files)}


@router.post("/bulk-restore")
async def bulk_restore_files(
    body: BulkRestoreRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not body.file_ids:
        return {"restored": 0}
    result = await session.execute(
        select(MediaFile).where(
            MediaFile.id.in_(body.file_ids),
            MediaFile.is_deleted == True,  # noqa: E712
        )
    )
    files = result.scalars().all()
    for f in files:
        f.is_deleted = False
        f.deleted_at = None
    await session.commit()
    return {"restored": len(files)}


@router.post("/bulk-dismiss-missing")
async def bulk_dismiss_missing_files(
    body: BulkDeleteRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Permanently remove externally-missing file records from the library."""
    if not body.file_ids:
        return {"dismissed": 0}
    result = await session.execute(
        select(MediaFile).where(
            MediaFile.id.in_(body.file_ids),
            MediaFile.missing_since.isnot(None),
        )
    )
    files = result.scalars().all()
    for f in files:
        await session.delete(f)
    await session.commit()
    return {"dismissed": len(files)}


@router.get("/{file_id}", response_model=FileDetailResponse)
async def get_file_detail(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FileDetailResponse:
    """Return full file detail including all metadata from the JSONB blob."""
    media_file = await session.get(MediaFile, file_id)
    if not media_file or media_file.is_deleted:
        raise HTTPException(status_code=404, detail="File not found")

    meta_result = await session.execute(
        select(FileMetadata).where(FileMetadata.file_id == file_id)
    )
    fm = meta_result.scalar_one_or_none()
    metadata_dict: dict | None = fm.data if fm else None

    return FileDetailResponse(
        id=media_file.id,
        folder_id=media_file.folder_id,
        root_folder_id=media_file.root_folder_id,
        filename=media_file.filename,
        extension=media_file.extension,
        media_type=media_file.media_type,
        mime_type=media_file.mime_type,
        is_raw=media_file.is_raw,
        width=media_file.width,
        height=media_file.height,
        duration_sec=media_file.duration_sec,
        taken_at=media_file.taken_at,
        camera_make=media_file.camera_make,
        camera_model=media_file.camera_model,
        has_gps=media_file.gps_lat is not None,
        has_thumbnail=media_file.thumbnail_path is not None,
        has_preview=media_file.preview_path is not None,
        size_bytes=media_file.size_bytes,
        thumbnail_url=f"/api/thumbnails/{media_file.id}",
        preview_url=f"/api/previews/{media_file.id}",
        lens_model=media_file.lens_model,
        location=media_file.location,
        trashed_at=media_file.deleted_at,
        missing_since=media_file.missing_since,
        path=media_file.path,
        focal_length_mm=media_file.focal_length_mm,
        aperture=media_file.aperture,
        shutter_speed=media_file.shutter_speed,
        iso=media_file.iso,
        gps_lat=media_file.gps_lat,
        gps_lon=media_file.gps_lon,
        gps_alt_m=media_file.gps_alt_m,
        orientation=media_file.orientation,
        indexed_at=media_file.indexed_at,
        processed_at=media_file.processed_at,
        metadata=metadata_dict,
    )
