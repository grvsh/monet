from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import get_current_user
from app.database import get_session
from app.models.db import MediaFile, RootFolder, User


def _content_disposition(filename: str) -> str:
    """Build a RFC 5987-compliant Content-Disposition header value.

    Handles filenames with quotes, non-ASCII characters, and other special
    characters that would break a naive f-string interpolation.
    """
    encoded = quote(filename, safe="")
    return f"attachment; filename*=UTF-8''{encoded}"

router = APIRouter()

_CACHE_HEADERS = {"Cache-Control": "max-age=31536000, immutable"}


@router.get("/thumbnails/{file_id}")
async def get_thumbnail(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    """Serve the thumbnail JPEG for a media file."""
    media_file = await session.get(MediaFile, file_id)
    if not media_file or media_file.is_deleted:
        raise HTTPException(status_code=404, detail="File not found")

    if media_file.processed_at is None or media_file.thumbnail_path is None:
        raise HTTPException(status_code=404, detail="thumbnail_pending")

    thumb_path = Path(settings.monet_cache_dir) / "thumbnails" / media_file.thumbnail_path
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="thumbnail_pending")

    return FileResponse(
        path=str(thumb_path),
        media_type="image/jpeg",
        headers=_CACHE_HEADERS,
    )


@router.get("/previews/{file_id}")
async def get_preview(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    """Serve the preview JPEG for a media file."""
    media_file = await session.get(MediaFile, file_id)
    if not media_file or media_file.is_deleted:
        raise HTTPException(status_code=404, detail="File not found")

    if media_file.processed_at is None or media_file.preview_path is None:
        raise HTTPException(status_code=404, detail="preview_pending")

    preview_path = Path(settings.monet_cache_dir) / "previews" / media_file.preview_path
    if not preview_path.exists():
        raise HTTPException(status_code=404, detail="preview_pending")

    return FileResponse(
        path=str(preview_path),
        media_type="image/jpeg",
        headers=_CACHE_HEADERS,
    )


@router.get("/previews/{file_id}/download")
async def download_preview(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    """Download the preview JPEG with Content-Disposition: attachment."""
    media_file = await session.get(MediaFile, file_id)
    if not media_file or media_file.is_deleted:
        raise HTTPException(status_code=404, detail="File not found")

    if media_file.processed_at is None or media_file.preview_path is None:
        raise HTTPException(status_code=404, detail="preview_pending")

    preview_path = Path(settings.monet_cache_dir) / "previews" / media_file.preview_path
    if not preview_path.exists():
        raise HTTPException(status_code=404, detail="preview_pending")

    stem = Path(media_file.filename).stem
    download_name = f"{stem}_preview.jpg"

    return FileResponse(
        path=str(preview_path),
        media_type="image/jpeg",
        headers={"Content-Disposition": _content_disposition(download_name)},
    )


@router.get("/stream/{file_id}")
async def stream_original(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    """Serve the original file with range request support (streaming)."""
    media_file = await session.get(MediaFile, file_id)
    if not media_file or media_file.is_deleted:
        raise HTTPException(status_code=404, detail="File not found")

    root = await session.get(RootFolder, media_file.root_folder_id)
    if not root:
        raise HTTPException(status_code=404, detail="Root folder not found")

    abs_path = Path(root.path) / media_file.path
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=str(abs_path),
        media_type=media_file.mime_type,
        filename=media_file.filename,
    )


@router.get("/original/{file_id}")
async def download_original(
    file_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    """Download the original file with Content-Disposition: attachment."""
    media_file = await session.get(MediaFile, file_id)
    if not media_file or media_file.is_deleted:
        raise HTTPException(status_code=404, detail="File not found")

    root = await session.get(RootFolder, media_file.root_folder_id)
    if not root:
        raise HTTPException(status_code=404, detail="Root folder not found")

    abs_path = Path(root.path) / media_file.path
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=str(abs_path),
        media_type=media_file.mime_type,
        filename=media_file.filename,
        headers={
            "Content-Disposition": _content_disposition(media_file.filename),
        },
    )
