from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clip_encoder
from app.core.auth import get_current_user
from app.database import get_session
from app.models.db import AlbumFile, MediaFile, RootFolder, User, UserRootPref
from app.models.schemas import FileResponse, PaginatedFiles
from app.api.utils import file_to_response

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


@router.get("", response_model=PaginatedFiles)
async def search(
    q: str | None = Query(default=None, description="Search term (filename, camera, caption)"),
    folder_id: uuid.UUID | None = Query(default=None),
    root_folder_id: uuid.UUID | None = Query(default=None),
    album_id: uuid.UUID | None = Query(default=None),
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

    # Collect all WHERE conditions so they can be shared across query paths.
    where: list = [
        MediaFile.is_deleted == False,  # noqa: E712
        MediaFile.root_folder_id.in_(visible_root_ids),
    ]

    if album_id:
        where.append(
            MediaFile.id.in_(
                select(AlbumFile.file_id).where(AlbumFile.album_id == album_id)
            )
        )
    if folder_id:
        where.append(MediaFile.folder_id == folder_id)
    if root_folder_id:
        if root_folder_id not in visible_root_ids:
            return PaginatedFiles(items=[], total=0, page=page, page_size=page_size, pages=1)
        where.append(MediaFile.root_folder_id == root_folder_id)
    if media_type != "all":
        where.append(MediaFile.media_type == media_type)
    if date_from:
        where.append(MediaFile.taken_at >= date_from)
    if date_to:
        where.append(MediaFile.taken_at <= date_to)

    if q:
        # Encode query on CPU in a thread pool so the event loop stays unblocked.
        embedding = await asyncio.get_running_loop().run_in_executor(
            None, clip_encoder.encode, q
        )

        if embedding is not None:
            return await _clip_search(
                q, embedding, where, page, page_size, session
            )

        # CLIP not ready yet — fall back to full-text search (Tier 1).
        return await _fts_search(q, where, page, page_size, session)

    # No query: return all files ordered by date.
    stmt = select(MediaFile).where(*where)
    return await _paginate(stmt, page, page_size, session)


# ---------------------------------------------------------------------------
# Search paths
# ---------------------------------------------------------------------------

async def _clip_search(
    q: str,
    embedding: list[float],
    where: list,
    page: int,
    page_size: int,
    session: AsyncSession,
) -> PaginatedFiles:
    """Semantic search via CLIP cosine similarity, with metadata keyword fallback."""

    # 1. Vector search: top 500 files ranked by cosine distance.
    vec_stmt = (
        select(MediaFile.id)
        .where(*where, MediaFile.clip_embedding.isnot(None))
        .order_by(MediaFile.clip_embedding.cosine_distance(embedding))
        .limit(500)
    )
    vec_result = await session.execute(vec_stmt)
    clip_ids: list[uuid.UUID] = [row[0] for row in vec_result.all()]

    # 2. Metadata keyword search (filenames, camera strings).
    #    Covers files without embeddings and explicit metadata queries.
    pattern = f"%{q}%"
    kw_stmt = select(MediaFile.id).where(
        *where,
        or_(
            MediaFile.filename.ilike(pattern),
            MediaFile.camera_make.ilike(pattern),
            MediaFile.camera_model.ilike(pattern),
        ),
    )
    kw_result = await session.execute(kw_stmt)
    keyword_ids: list[uuid.UUID] = [row[0] for row in kw_result.all()]

    # 3. Merge: CLIP ranking first, keyword results appended if not already present.
    seen: set[uuid.UUID] = set(clip_ids)
    merged = list(clip_ids)
    for fid in keyword_ids:
        if fid not in seen:
            merged.append(fid)

    total = len(merged)
    offset = (page - 1) * page_size
    page_ids = merged[offset : offset + page_size]

    files: list[MediaFile] = []
    if page_ids:
        records_stmt = select(MediaFile).where(MediaFile.id.in_(page_ids))
        records_result = await session.execute(records_stmt)
        by_id = {f.id: f for f in records_result.scalars().all()}
        files = [by_id[fid] for fid in page_ids if fid in by_id]

    pages = max(1, (total + page_size - 1) // page_size)
    return PaginatedFiles(
        items=[file_to_response(f) for f in files],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


async def _fts_search(
    q: str,
    where: list,
    page: int,
    page_size: int,
    session: AsyncSession,
) -> PaginatedFiles:
    """Full-text search on caption + ilike on metadata fields (Tier 1 fallback)."""
    pattern = f"%{q}%"
    fts_query = func.websearch_to_tsquery("english", q)
    caption_fts = func.to_tsvector(
        "english", func.coalesce(MediaFile.caption, "")
    ).op("@@")(fts_query)

    stmt = select(MediaFile).where(
        *where,
        or_(
            MediaFile.filename.ilike(pattern),
            MediaFile.camera_make.ilike(pattern),
            MediaFile.camera_model.ilike(pattern),
            caption_fts,
        ),
    )
    return await _paginate(stmt, page, page_size, session)


async def _paginate(
    stmt,
    page: int,
    page_size: int,
    session: AsyncSession,
) -> PaginatedFiles:
    """SQL-level count + offset pagination, ordered by date then filename."""
    count_result = await session.execute(
        select(func.count()).select_from(stmt.subquery())
    )
    total = count_result.scalar_one()

    stmt = stmt.order_by(MediaFile.taken_at.desc().nullslast(), MediaFile.filename.asc())
    offset = (page - 1) * page_size
    stmt = stmt.offset(offset).limit(page_size)
    result = await session.execute(stmt)
    files = result.scalars().all()

    pages = max(1, (total + page_size - 1) // page_size)
    return PaginatedFiles(
        items=[file_to_response(f) for f in files],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )
