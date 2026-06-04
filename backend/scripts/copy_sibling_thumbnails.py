"""Copy thumbnails/previews from child-root siblings to parent-root duplicate records.

Run this after adding a parent root folder over already-indexed child roots.
It directly copies thumbnail files and updates the DB — no ARQ queue needed.
"""
import asyncio
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session_factory
from app.models.db import MediaFile, RootFolder
from app.services.media import thumbnail_cache_path, preview_cache_path


def _copy_file(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


async def process_root(session: AsyncSession, parent_root: RootFolder, child_roots: list[RootFolder]) -> int:
    child_root_by_path = {Path(cr.path): cr for cr in child_roots}

    # Fetch all unprocessed files under this parent root
    result = await session.execute(
        select(MediaFile).where(
            MediaFile.root_folder_id == parent_root.id,
            MediaFile.processed_at.is_(None),
            MediaFile.is_deleted == False,  # noqa: E712
        )
    )
    unprocessed = result.scalars().all()
    print(f"  {len(unprocessed)} unprocessed files under '{parent_root.name}'")

    # Build lookup: child_root -> {rel_path -> MediaFile} for files with thumbnails
    sibling_cache: dict[uuid.UUID, dict[str, MediaFile]] = {}

    fixed = 0
    batch_size = 200
    now = datetime.now(timezone.utc)

    for i, mf in enumerate(unprocessed):
        abs_path = Path(parent_root.path) / mf.path

        # Find which child root contains this file
        sibling: MediaFile | None = None
        for cr_path, cr in child_root_by_path.items():
            try:
                rel = abs_path.relative_to(cr_path)
            except ValueError:
                continue

            # Lazy-build sibling cache for this child root
            if cr.id not in sibling_cache:
                cr_result = await session.execute(
                    select(MediaFile).where(
                        MediaFile.root_folder_id == cr.id,
                        MediaFile.processed_at.isnot(None),
                        MediaFile.thumbnail_path.isnot(None),
                    )
                )
                sibling_cache[cr.id] = {s.path: s for s in cr_result.scalars().all()}

            sibling = sibling_cache.get(cr.id, {}).get(str(rel))
            break

        if not sibling:
            continue  # not a child-root file; needs normal processing

        # Copy thumbnail
        src_thumb = Path(settings.monet_cache_dir) / "thumbnails" / sibling.thumbnail_path
        dst_thumb = thumbnail_cache_path(mf.id, settings.monet_cache_dir)
        thumb_ok = _copy_file(src_thumb, dst_thumb)
        if not thumb_ok:
            continue

        thumb_rel = str(dst_thumb.relative_to(Path(settings.monet_cache_dir) / "thumbnails"))
        mf.thumbnail_path = thumb_rel

        # Copy preview (best-effort)
        if sibling.preview_path:
            src_prev = Path(settings.monet_cache_dir) / "previews" / sibling.preview_path
            dst_prev = preview_cache_path(mf.id, settings.monet_cache_dir)
            if _copy_file(src_prev, dst_prev):
                mf.preview_path = str(dst_prev.relative_to(Path(settings.monet_cache_dir) / "previews"))

        mf.width = sibling.width
        mf.height = sibling.height
        mf.processed_at = now
        fixed += 1

        # Commit in batches
        if fixed % batch_size == 0:
            await session.commit()
            print(f"    ... {fixed} copied so far")

    if fixed % batch_size != 0:
        await session.commit()

    return fixed


async def main() -> None:
    async with async_session_factory() as session:
        # Find all parent roots (roots that have child roots)
        all_roots_result = await session.execute(
            select(RootFolder).where(RootFolder.is_active == True)  # noqa: E712
        )
        all_roots = all_roots_result.scalars().all()
        root_by_id = {r.id: r for r in all_roots}

        # Group child roots by their parent
        children_by_parent: dict[uuid.UUID, list[RootFolder]] = {}
        for r in all_roots:
            if r.parent_root_id:
                children_by_parent.setdefault(r.parent_root_id, []).append(r)

        if not children_by_parent:
            print("No parent/child root relationships found. Nothing to do.")
            return

        total_fixed = 0
        for parent_id, child_roots in children_by_parent.items():
            parent_root = root_by_id.get(parent_id)
            if not parent_root:
                continue
            print(f"\nProcessing parent root '{parent_root.name}' with {len(child_roots)} child root(s):")
            for cr in child_roots:
                print(f"  child: '{cr.name}' at {cr.path}")
            fixed = await process_root(session, parent_root, child_roots)
            print(f"  → Fixed {fixed} files")
            total_fixed += fixed

    print(f"\nDone. Total fixed: {total_fixed}")


asyncio.run(main())
