from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import require_admin
from app.database import get_session
from app.models.db import RootFolder, User
from app.models.schemas import FsBrowseResponse, FsEntry

router = APIRouter()

# Pre-resolve configured browse roots once at import time for fast checking.
# Paths that are not descendants of any allowed root are rejected with 403.
_ALLOWED_ROOTS: list[Path] = [Path(p).resolve() for p in settings.monet_browse_roots]


def _is_within_allowed_root(resolved: Path) -> bool:
    """Return True if *resolved* is equal to, or a descendant of, any allowed root."""
    for allowed in _ALLOWED_ROOTS:
        if resolved == allowed or allowed in resolved.parents:
            return True
    return False


@router.get("/browse", response_model=FsBrowseResponse)
async def browse(
    path: str = Query(default=None, description="Absolute directory path to list"),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> FsBrowseResponse:
    """Browse directories on the NAS filesystem (admin only).

    Only paths within MONET_BROWSE_ROOTS are accessible.  Returns only
    directories; files are omitted.  Unreadable sub-directories are silently
    skipped.  Symlinks are followed but flagged with is_symlink=True.
    """
    # Default to showing the configured browse roots themselves
    if path is None:
        entries: list[FsEntry] = []
        result = await session.execute(
            select(RootFolder.path).where(RootFolder.is_active == True)  # noqa: E712
        )
        configured_paths: set[str] = {row[0] for row in result.all()}
        for root in _ALLOWED_ROOTS:
            if root.is_dir():
                entries.append(FsEntry(
                    name=root.name or str(root),
                    path=str(root),
                    is_symlink=root.is_symlink(),
                    is_configured=str(root) in configured_paths,
                ))
        return FsBrowseResponse(path="", parent=None, entries=entries)

    resolved = Path(path).resolve()

    # ── Security gate ─────────────────────────────────────────────────────────
    if not _is_within_allowed_root(resolved):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Path is outside the allowed browse roots. "
                f"Configure MONET_BROWSE_ROOTS to include additional paths."
            ),
        )

    if not resolved.is_dir():
        raise HTTPException(status_code=404, detail="Path not found or not a directory")

    # Determine parent — None when we are already at an allowed root boundary
    parent: str | None = None
    parent_path = resolved.parent
    if resolved != parent_path and _is_within_allowed_root(parent_path):
        parent = str(parent_path)

    # Load configured root folder paths for the is_configured flag (active only)
    result = await session.execute(
        select(RootFolder.path).where(RootFolder.is_active == True)  # noqa: E712
    )
    configured_paths = {row[0] for row in result.all()}

    def _entry_is_configured(abs_path: str) -> bool:
        """True if abs_path is a configured root or a descendant of one."""
        for cp in configured_paths:
            if abs_path == cp or abs_path.startswith(cp + "/"):
                return True
        return False

    # True when the current directory itself is inside (or is) a configured root
    resolved_str = str(resolved)
    current_is_configured = _entry_is_configured(resolved_str)

    dir_entries: list[FsEntry] = []
    try:
        with os.scandir(str(resolved)) as it:
            for entry in sorted(it, key=lambda e: e.name.lower()):
                if not entry.is_dir(follow_symlinks=True):
                    continue
                if entry.name.startswith('.'):
                    continue
                try:
                    abs_entry_path = str(Path(entry.path).resolve())
                    dir_entries.append(FsEntry(
                        name=entry.name,
                        path=abs_entry_path,
                        is_symlink=entry.is_symlink(),
                        is_configured=_entry_is_configured(abs_entry_path),
                    ))
                except PermissionError:
                    continue
    except PermissionError:
        pass  # Return empty list if the directory itself is unreadable

    return FsBrowseResponse(
        path=resolved_str,
        parent=parent,
        entries=dir_entries,
        path_is_configured=current_is_configured,
    )
