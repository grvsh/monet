from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.database import get_session
from app.models.db import Album, AlbumFile, MediaFile, User
from app.models.schemas import (
    AlbumFilesRequest,
    AlbumResponse,
    CreateAlbumRequest,
    FileResponse,
    PaginatedFiles,
    RenameAlbumRequest,
)

router = APIRouter()


def _file_to_response(f: MediaFile) -> FileResponse:
    return FileResponse(
        id=str(f.id),
        folder_id=str(f.folder_id),
        root_folder_id=str(f.root_folder_id),
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


async def _get_own_album(
    album_id: uuid.UUID, user: User, session: AsyncSession
) -> Album:
    album = await session.get(Album, album_id)
    if not album:
        raise HTTPException(status_code=404, detail="Album not found")
    if album.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return album


async def _album_to_response(album: Album, session: AsyncSession) -> AlbumResponse:
    # file count
    count_result = await session.execute(
        select(func.count()).where(AlbumFile.album_id == album.id)
    )
    file_count = count_result.scalar_one()

    # cover: thumbnail of most recently added file
    cover_result = await session.execute(
        select(MediaFile)
        .join(AlbumFile, AlbumFile.file_id == MediaFile.id)
        .where(AlbumFile.album_id == album.id, MediaFile.thumbnail_path.isnot(None))
        .order_by(AlbumFile.added_at.desc())
        .limit(1)
    )
    cover_file = cover_result.scalar_one_or_none()
    cover_url = f"/api/thumbnails/{cover_file.id}" if cover_file else None

    return AlbumResponse(
        id=album.id,
        name=album.name,
        owner_id=album.owner_id,
        file_count=file_count,
        cover_url=cover_url,
        created_at=album.created_at,
        updated_at=album.updated_at,
    )


# ── List ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[AlbumResponse])
async def list_albums(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AlbumResponse]:
    result = await session.execute(
        select(Album)
        .where(Album.owner_id == current_user.id)
        .order_by(Album.name)
    )
    albums = result.scalars().all()
    return [await _album_to_response(a, session) for a in albums]


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("", response_model=AlbumResponse, status_code=201)
async def create_album(
    body: CreateAlbumRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AlbumResponse:
    album = Album(owner_id=current_user.id, name=body.name.strip())
    session.add(album)
    await session.flush()
    return await _album_to_response(album, session)


# ── Get single ───────────────────────────────────────────────────────────────

@router.get("/{album_id}", response_model=AlbumResponse)
async def get_album(
    album_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AlbumResponse:
    album = await _get_own_album(album_id, current_user, session)
    return await _album_to_response(album, session)


# ── Rename ────────────────────────────────────────────────────────────────────

@router.patch("/{album_id}", response_model=AlbumResponse)
async def rename_album(
    album_id: uuid.UUID,
    body: RenameAlbumRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AlbumResponse:
    album = await _get_own_album(album_id, current_user, session)
    album.name = body.name.strip()
    album.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return await _album_to_response(album, session)


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/{album_id}", status_code=204)
async def delete_album(
    album_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    album = await _get_own_album(album_id, current_user, session)
    await session.delete(album)


# ── Files: list ───────────────────────────────────────────────────────────────

@router.get("/{album_id}/files", response_model=PaginatedFiles)
async def list_album_files(
    album_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=500, ge=1, le=500),
    sort: Literal["taken_at", "filename", "size_bytes", "position"] = Query(default="position"),
    order: Literal["asc", "desc"] = Query(default="asc"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PaginatedFiles:
    album = await _get_own_album(album_id, current_user, session)

    sort_col = {
        "taken_at": MediaFile.taken_at,
        "filename": MediaFile.filename,
        "size_bytes": MediaFile.size_bytes,
        "position": AlbumFile.position,
    }[sort]

    stmt = (
        select(MediaFile)
        .join(AlbumFile, AlbumFile.file_id == MediaFile.id)
        .where(AlbumFile.album_id == album.id, MediaFile.is_deleted == False)  # noqa: E712
    )
    if order == "desc":
        stmt = stmt.order_by(sort_col.desc().nullslast(), AlbumFile.added_at.desc())
    else:
        stmt = stmt.order_by(sort_col.asc().nullsfirst(), AlbumFile.added_at.asc())

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


# ── Files: add ────────────────────────────────────────────────────────────────

@router.post("/{album_id}/files", status_code=204)
async def add_files_to_album(
    album_id: uuid.UUID,
    body: AlbumFilesRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    album = await _get_own_album(album_id, current_user, session)

    # Find the current max position
    max_pos_result = await session.execute(
        select(func.coalesce(func.max(AlbumFile.position), -1))
        .where(AlbumFile.album_id == album.id)
    )
    max_pos: int = max_pos_result.scalar_one()

    # Get existing file_ids to avoid duplicates
    existing_result = await session.execute(
        select(AlbumFile.file_id).where(AlbumFile.album_id == album.id)
    )
    existing_ids = {row[0] for row in existing_result.all()}

    for i, file_id in enumerate(body.file_ids):
        if file_id in existing_ids:
            continue
        session.add(AlbumFile(
            album_id=album.id,
            file_id=file_id,
            position=max_pos + 1 + i,
        ))

    album.updated_at = datetime.now(timezone.utc)
    await session.flush()


# ── Files: remove ─────────────────────────────────────────────────────────────

@router.delete("/{album_id}/files", status_code=204)
async def remove_files_from_album(
    album_id: uuid.UUID,
    body: AlbumFilesRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    album = await _get_own_album(album_id, current_user, session)
    file_ids = [fid for fid in body.file_ids]

    result = await session.execute(
        select(AlbumFile).where(
            AlbumFile.album_id == album.id,
            AlbumFile.file_id.in_(file_ids),
        )
    )
    for af in result.scalars().all():
        await session.delete(af)

    album.updated_at = datetime.now(timezone.utc)
    await session.flush()
