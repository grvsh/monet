"""
Tests for the indexing pipeline.

These test the scan logic and ARQ task functions with:
- Real DB (via the session fixture)
- Mocked ARQ redis (mock_redis fixture)
- Real filesystem (tmp_path)
- Mocked exiftool and ffmpeg
"""
from __future__ import annotations

import io
import struct
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import Folder, MediaFile, RootFolder, ScanJob


# ── Helpers ───────────────────────────────────────────────────────────────────

def tiny_jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), (200, 100, 80)).save(buf, "JPEG")
    return buf.getvalue()


def tiny_mp4() -> bytes:
    def box(fc, payload=b""):
        return struct.pack(">I4s", 8 + len(payload), fc.encode()) + payload
    return box("ftyp", b"isom" + struct.pack(">I", 0) + b"isommp41") + box("mdat", b"\x00" * 8)


# ── Tests for indexer service functions ───────────────────────────────────────

class TestGetOrCreateFolder:
    async def test_creates_new_folder(
        self, db_session: AsyncSession, root_folder: RootFolder
    ):
        from app.services.indexer import get_or_create_folder
        folder = await get_or_create_folder(
            db_session, root_folder.id, "test/path", "path", None
        )
        assert folder.id is not None
        assert folder.path == "test/path"
        assert folder.name == "path"
        assert folder.root_folder_id == root_folder.id

    async def test_returns_existing_folder(
        self, db_session: AsyncSession, root_folder: RootFolder, folder_2024: Folder
    ):
        from app.services.indexer import get_or_create_folder
        # Call twice with same path
        f1 = await get_or_create_folder(
            db_session, root_folder.id, "2024", "2024", None
        )
        f2 = await get_or_create_folder(
            db_session, root_folder.id, "2024", "2024", None
        )
        assert f1.id == f2.id

    async def test_root_folder_has_none_parent(
        self, db_session: AsyncSession, root_folder: RootFolder
    ):
        from app.services.indexer import get_or_create_folder
        folder = await get_or_create_folder(
            db_session, root_folder.id, "", "root", None
        )
        assert folder.parent_id is None


class TestUpsertMediaFile:
    async def test_creates_new_file(
        self, db_session: AsyncSession, root_folder: RootFolder, folder_vacation: Folder, tmp_media_dir: Path
    ):
        from app.services.indexer import upsert_media_file
        abs_path = str(tmp_media_dir / "2024" / "vacation" / "IMG_001.jpg")
        mtime = datetime(2024, 7, 14, 9, 0, 0, tzinfo=timezone.utc)

        file, is_new = await upsert_media_file(
            db_session, root_folder.id, folder_vacation.id,
            abs_path, "2024/vacation/IMG_001.jpg", mtime,
            "image", "image/jpeg", "jpg",
        )
        assert is_new is True
        assert file.filename == "IMG_001.jpg"
        assert file.extension == "jpg"
        assert file.media_type == "image"
        assert file.is_raw is False

    async def test_skips_unchanged_file(
        self, db_session: AsyncSession, root_folder: RootFolder,
        folder_vacation: Folder, media_file_jpg: MediaFile
    ):
        from app.services.indexer import upsert_media_file
        # Same mtime and already processed
        media_file_jpg.processed_at = datetime.now(timezone.utc)
        await db_session.flush()

        file, is_new = await upsert_media_file(
            db_session, root_folder.id, folder_vacation.id,
            "/fake/path", "2024/vacation/IMG_001.jpg",
            media_file_jpg.mtime,  # same mtime
            "image", "image/jpeg", "jpg",
        )
        assert is_new is False

    async def test_resets_processed_at_on_mtime_change(
        self, db_session: AsyncSession, root_folder: RootFolder,
        folder_vacation: Folder, media_file_jpg: MediaFile, tmp_media_dir: Path
    ):
        from app.services.indexer import upsert_media_file
        media_file_jpg.processed_at = datetime.now(timezone.utc)
        await db_session.flush()

        abs_path = str(tmp_media_dir / "2024" / "vacation" / "IMG_001.jpg")
        new_mtime = datetime(2024, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        file, is_new = await upsert_media_file(
            db_session, root_folder.id, folder_vacation.id,
            abs_path, "2024/vacation/IMG_001.jpg",
            new_mtime,  # different mtime — triggers size re-read
            "image", "image/jpeg", "jpg",
        )
        assert file.processed_at is None  # reset


class TestMediaTypeDetection:
    def test_jpeg_detected_as_image(self, tmp_path):
        from app.services.media import get_media_type
        p = tmp_path / "photo.jpg"
        p.write_bytes(tiny_jpeg())
        result = get_media_type(str(p))
        assert result is not None
        media_type, mime = result
        assert media_type == "image"
        assert "jpeg" in mime or "image" in mime

    def test_png_detected_as_image(self, tmp_path):
        from app.services.media import get_media_type
        buf = io.BytesIO()
        Image.new("RGB", (10, 10)).save(buf, "PNG")
        p = tmp_path / "img.png"
        p.write_bytes(buf.getvalue())
        result = get_media_type(str(p))
        assert result is not None
        assert result[0] == "image"

    def test_text_file_returns_none(self, tmp_path):
        from app.services.media import get_media_type
        p = tmp_path / "notes.txt"
        p.write_text("hello world")
        assert get_media_type(str(p)) is None

    def test_pdf_returns_none(self, tmp_path):
        from app.services.media import get_media_type
        p = tmp_path / "doc.pdf"
        p.write_bytes(b"%PDF-1.4\n%%EOF\n")
        assert get_media_type(str(p)) is None

    def test_raw_extensions_detected(self):
        from app.services.media import is_raw
        assert is_raw("cr2") is True
        assert is_raw("cr3") is True
        assert is_raw("nef") is True
        assert is_raw("arw") is True
        assert is_raw("dng") is True
        assert is_raw("jpg") is False
        assert is_raw("mp4") is False


class TestCachePathGeneration:
    def test_thumbnail_path_sharded(self):
        from app.services.media import thumbnail_cache_path
        file_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        path = thumbnail_cache_path(file_id, "/var/monet/cache")
        assert str(path).startswith("/var/monet/cache/thumbnails/")
        # Should be sharded by first 4 chars of UUID without dashes
        assert "12" in str(path)
        assert str(file_id) + ".jpg" in str(path)

    def test_preview_path_sharded(self):
        from app.services.media import preview_cache_path
        file_id = uuid.UUID("abcdef12-abcd-abcd-abcd-abcdef123456")
        path = preview_cache_path(file_id, "/var/monet/cache")
        assert str(path).startswith("/var/monet/cache/previews/")
        assert str(file_id) + ".jpg" in str(path)

    def test_different_ids_different_paths(self):
        from app.services.media import thumbnail_cache_path
        id1 = uuid.uuid4()
        id2 = uuid.uuid4()
        p1 = thumbnail_cache_path(id1, "/cache")
        p2 = thumbnail_cache_path(id2, "/cache")
        assert p1 != p2


class TestScanJobTracking:
    async def test_scan_job_created_on_scan_request(
        self,
        client,
        admin_headers: dict,
        root_folder: RootFolder,
        mock_redis,
    ):
        resp = await client.post("/api/index/scan", headers=admin_headers)
        assert resp.status_code in (200, 202)
        data = resp.json()
        assert "scan_job_id" in data or "message" in data

    async def test_scan_status_returns_jobs(
        self,
        client,
        admin_headers: dict,
        db_session: AsyncSession,
        root_folder: RootFolder,
    ):
        # Create a scan job directly
        job = ScanJob(
            root_folder_id=root_folder.id,
            trigger_type="manual",
            status="completed",
            folders_found=5,
            folders_scanned=5,
            files_found=20,
            files_new=20,
        )
        db_session.add(job)
        await db_session.flush()

        resp = await client.get("/api/index/status", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "jobs" in data
        assert len(data["jobs"]) >= 1
