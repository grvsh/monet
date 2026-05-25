"""Tests for folder browsing and file listing endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import Folder, MediaFile, RootFolder, User


class TestListRootLevelFolders:
    async def test_returns_root_level_folders(
        self,
        client: AsyncClient,
        admin_headers: dict,
        root_folder: RootFolder,
        folder_2024: Folder,
    ):
        resp = await client.get("/api/folders", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        ids = [f["id"] for f in data]
        assert str(folder_2024.id) in ids

    async def test_only_shows_visible_roots(
        self,
        client: AsyncClient,
        viewer_headers: dict,
        viewer_user: User,
        root_folder: RootFolder,
        folder_2024: Folder,
        db_session: AsyncSession,
    ):
        # Hide the root folder for this viewer
        from app.models.db import UserRootPref
        pref = UserRootPref(
            user_id=viewer_user.id,
            root_folder_id=root_folder.id,
            is_visible=False,
        )
        db_session.add(pref)
        await db_session.flush()

        resp = await client.get("/api/folders", headers=viewer_headers)
        assert resp.status_code == 200
        # Folder should not appear since its root is hidden
        ids = [f["id"] for f in resp.json()]
        assert str(folder_2024.id) not in ids

    async def test_folder_response_shape(
        self,
        client: AsyncClient,
        admin_headers: dict,
        folder_2024: Folder,
    ):
        resp = await client.get("/api/folders", headers=admin_headers)
        assert resp.status_code == 200
        folder_data = next(
            (f for f in resp.json() if f["id"] == str(folder_2024.id)), None
        )
        if folder_data:
            assert "id" in folder_data
            assert "root_folder_id" in folder_data
            assert "name" in folder_data
            assert "path" in folder_data
            assert "file_count" in folder_data
            assert "child_folder_count" in folder_data

    async def test_requires_auth(self, client: AsyncClient, folder_2024: Folder):
        resp = await client.get("/api/folders")
        assert resp.status_code in (401, 403)


class TestListChildFolders:
    async def test_returns_children(
        self,
        client: AsyncClient,
        admin_headers: dict,
        folder_2024: Folder,
        folder_vacation: Folder,
    ):
        resp = await client.get(f"/api/folders/{folder_2024.id}/children", headers=admin_headers)
        assert resp.status_code == 200
        ids = [f["id"] for f in resp.json()]
        assert str(folder_vacation.id) in ids

    async def test_empty_folder_returns_empty_list(
        self,
        client: AsyncClient,
        admin_headers: dict,
        folder_vacation: Folder,
    ):
        resp = await client.get(f"/api/folders/{folder_vacation.id}/children", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_nonexistent_folder_404(self, client: AsyncClient, admin_headers: dict):
        import uuid
        resp = await client.get(f"/api/folders/{uuid.uuid4()}/children", headers=admin_headers)
        assert resp.status_code == 404


class TestListFolderFiles:
    async def test_returns_files(
        self,
        client: AsyncClient,
        admin_headers: dict,
        folder_vacation: Folder,
        media_file_jpg: MediaFile,
        media_file_video: MediaFile,
    ):
        resp = await client.get(
            f"/api/folders/{folder_vacation.id}/files",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert data["total"] >= 2
        ids = [f["id"] for f in data["items"]]
        assert str(media_file_jpg.id) in ids
        assert str(media_file_video.id) in ids

    async def test_file_response_shape(
        self,
        client: AsyncClient,
        admin_headers: dict,
        folder_vacation: Folder,
        media_file_jpg: MediaFile,
    ):
        resp = await client.get(
            f"/api/folders/{folder_vacation.id}/files",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        if items:
            f = next((i for i in items if i["id"] == str(media_file_jpg.id)), None)
            if f:
                assert f["filename"] == "IMG_001.jpg"
                assert f["media_type"] == "image"
                assert f["is_raw"] is False
                assert "thumbnail_url" in f
                assert "preview_url" in f
                assert f["has_gps"] is True  # we set gps_lat

    async def test_filter_by_media_type(
        self,
        client: AsyncClient,
        admin_headers: dict,
        folder_vacation: Folder,
        media_file_jpg: MediaFile,
        media_file_video: MediaFile,
    ):
        resp = await client.get(
            f"/api/folders/{folder_vacation.id}/files?media_type=image",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        types = [f["media_type"] for f in resp.json()["items"]]
        assert all(t == "image" for t in types)

        resp = await client.get(
            f"/api/folders/{folder_vacation.id}/files?media_type=video",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        types = [f["media_type"] for f in resp.json()["items"]]
        assert all(t == "video" for t in types)

    async def test_pagination(
        self,
        client: AsyncClient,
        admin_headers: dict,
        folder_vacation: Folder,
        media_file_jpg: MediaFile,
        media_file_video: MediaFile,
    ):
        resp = await client.get(
            f"/api/folders/{folder_vacation.id}/files?page=1&page_size=1",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["page_size"] == 1
        assert data["pages"] >= 2

    async def test_sort_by_filename(
        self,
        client: AsyncClient,
        admin_headers: dict,
        folder_vacation: Folder,
        media_file_jpg: MediaFile,
        media_file_video: MediaFile,
    ):
        resp = await client.get(
            f"/api/folders/{folder_vacation.id}/files?sort=filename&order=asc",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        names = [f["filename"] for f in resp.json()["items"]]
        assert names == sorted(names)

    async def test_deleted_files_excluded(
        self,
        client: AsyncClient,
        admin_headers: dict,
        folder_vacation: Folder,
        media_file_jpg: MediaFile,
        db_session: AsyncSession,
    ):
        media_file_jpg.is_deleted = True
        await db_session.flush()

        resp = await client.get(
            f"/api/folders/{folder_vacation.id}/files",
            headers=admin_headers,
        )
        ids = [f["id"] for f in resp.json()["items"]]
        assert str(media_file_jpg.id) not in ids


class TestGetFile:
    async def test_get_file_detail(
        self,
        client: AsyncClient,
        admin_headers: dict,
        media_file_jpg: MediaFile,
    ):
        resp = await client.get(f"/api/files/{media_file_jpg.id}", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(media_file_jpg.id)
        assert data["filename"] == "IMG_001.jpg"
        assert data["camera_make"] == "Canon"
        assert data["camera_model"] == "Canon EOS R5"
        assert data["gps_lat"] == pytest.approx(48.8566, abs=0.0001)
        assert data["gps_lon"] == pytest.approx(2.3522, abs=0.0001)
        assert data["has_gps"] is True

    async def test_file_detail_includes_metadata(
        self,
        client: AsyncClient,
        admin_headers: dict,
        media_file_jpg: MediaFile,
        db_session: AsyncSession,
    ):
        from app.models.db import FileMetadata
        fm = FileMetadata(
            file_id=media_file_jpg.id,
            data={"EXIF:Make": "Canon", "EXIF:Model": "Canon EOS R5"},
        )
        db_session.add(fm)
        await db_session.flush()

        resp = await client.get(f"/api/files/{media_file_jpg.id}", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("metadata") is not None
        assert data["metadata"]["EXIF:Make"] == "Canon"

    async def test_file_not_found(self, client: AsyncClient, admin_headers: dict):
        import uuid
        resp = await client.get(f"/api/files/{uuid.uuid4()}", headers=admin_headers)
        assert resp.status_code == 404

    async def test_requires_auth(self, client: AsyncClient, media_file_jpg: MediaFile):
        resp = await client.get(f"/api/files/{media_file_jpg.id}")
        assert resp.status_code in (401, 403)
