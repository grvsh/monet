from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import Folder, MediaFile
from app.services.media import is_raw


async def get_or_create_folder(
    session: AsyncSession,
    root_folder_id: uuid.UUID,
    relative_path: str,
    name: str,
    parent_id: uuid.UUID | None,
) -> Folder:
    """Upsert a folder row. Returns the existing or newly created Folder.

    Uses INSERT ON CONFLICT DO NOTHING so concurrent scan tasks for the same
    root folder do not race and crash on the unique (root_folder_id, path) constraint.
    """
    await session.execute(
        pg_insert(Folder)
        .values(
            root_folder_id=root_folder_id,
            path=relative_path,
            name=name,
            parent_id=parent_id,
        )
        .on_conflict_do_nothing(constraint="uq_folders_root_path")
    )
    result = await session.execute(
        select(Folder).where(
            Folder.root_folder_id == root_folder_id,
            Folder.path == relative_path,
        )
    )
    return result.scalar_one()


async def upsert_media_file(
    session: AsyncSession,
    root_folder_id: uuid.UUID,
    folder_id: uuid.UUID,
    abs_path: str,
    relative_path: str,
    mtime: datetime,
    media_type: str,
    mime_type: str,
    extension: str,
) -> tuple[MediaFile, bool]:
    """Upsert a media file row.

    Returns (MediaFile, is_new) where is_new=True means the row was just inserted.
    """
    stmt = select(MediaFile).where(
        MediaFile.root_folder_id == root_folder_id,
        MediaFile.path == relative_path,
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is not None:
        # File found on disk — clear any missing flag regardless of change state
        if existing.missing_since is not None:
            existing.missing_since = None

        if existing.mtime == mtime and existing.processed_at is not None:
            return existing, False

        # File changed — reset processed_at to trigger reprocessing
        existing.mtime = mtime
        existing.processed_at = None
        existing.is_deleted = False
        existing.deleted_at = None
        existing.size_bytes = os.path.getsize(abs_path)
        await session.flush()
        return existing, False

    new_file = MediaFile(
        folder_id=folder_id,
        root_folder_id=root_folder_id,
        path=relative_path,
        filename=Path(abs_path).name,
        extension=extension,
        size_bytes=os.path.getsize(abs_path),
        mtime=mtime,
        media_type=media_type,
        mime_type=mime_type,
        is_raw=is_raw(extension),
    )
    session.add(new_file)
    await session.flush()
    return new_file, True


async def mark_missing_files(
    session: AsyncSession,
    _root_folder_id: uuid.UUID,
    folder_id: uuid.UUID,
    found_relative_paths: set[str],
) -> int:
    """Mark files not found on disk as missing (external move/delete).

    Only affects files that are NOT already user-trashed (is_deleted=False).
    Returns the number of files newly marked missing.
    """
    stmt = select(MediaFile).where(
        MediaFile.folder_id == folder_id,
        MediaFile.is_deleted == False,  # noqa: E712
        MediaFile.missing_since.is_(None),
    )
    result = await session.execute(stmt)
    db_files = result.scalars().all()

    marked = 0
    now = datetime.now(timezone.utc)
    for f in db_files:
        if f.path not in found_relative_paths:
            f.missing_since = now
            marked += 1

    if marked:
        await session.flush()

    return marked
