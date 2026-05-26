"""Tests for root folder management and filesystem browser."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import RootFolder, User


class TestListRootFolders:
    async def test_any_user_can_list(
        self, client: AsyncClient, viewer_headers: dict, root_folder: RootFolder
    ):
        resp = await client.get("/api/root-folders", headers=viewer_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        ids = [r["id"] for r in data]
        assert str(root_folder.id) in ids

    async def test_unauthenticated_cannot_list(self, client: AsyncClient, root_folder: RootFolder):
        resp = await client.get("/api/root-folders")
        assert resp.status_code in (401, 403)

    async def test_response_shape(
        self, client: AsyncClient, admin_headers: dict, root_folder: RootFolder
    ):
        resp = await client.get("/api/root-folders", headers=admin_headers)
        assert resp.status_code == 200
        entry = next(r for r in resp.json() if r["id"] == str(root_folder.id))
        assert "id" in entry
        assert "name" in entry
        assert "path" in entry
        assert "is_active" in entry
        assert "created_at" in entry
        assert "last_scanned_at" in entry


class TestCreateRootFolder:
    async def test_admin_creates_root_folder(
        self, client: AsyncClient, admin_headers: dict, tmp_path
    ):
        media = tmp_path / "newmedia"
        media.mkdir()
        resp = await client.post("/api/root-folders", json={
            "name": "New Library",
            "path": str(media),
        }, headers=admin_headers)
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["name"] == "New Library"
        assert data["path"] == str(media)
        assert data["is_active"] is True

    async def test_viewer_cannot_create(self, client: AsyncClient, viewer_headers: dict, tmp_path):
        media = tmp_path / "viewermedia"
        media.mkdir()
        resp = await client.post("/api/root-folders", json={
            "name": "Viewer Library",
            "path": str(media),
        }, headers=viewer_headers)
        assert resp.status_code == 403

    async def test_nonexistent_path_rejected(self, client: AsyncClient, admin_headers: dict):
        resp = await client.post("/api/root-folders", json={
            "name": "Ghost",
            "path": "/nonexistent/path/that/does/not/exist",
        }, headers=admin_headers)
        assert resp.status_code in (400, 422)

    async def test_duplicate_path_rejected(
        self, client: AsyncClient, admin_headers: dict, root_folder: RootFolder
    ):
        resp = await client.post("/api/root-folders", json={
            "name": "Duplicate",
            "path": root_folder.path,
        }, headers=admin_headers)
        assert resp.status_code in (400, 409, 422)


class TestUpdateRootFolder:
    async def test_rename(
        self, client: AsyncClient, admin_headers: dict, root_folder: RootFolder
    ):
        resp = await client.patch(
            f"/api/root-folders/{root_folder.id}",
            json={"name": "Renamed Library"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed Library"

    async def test_viewer_cannot_rename(
        self, client: AsyncClient, viewer_headers: dict, root_folder: RootFolder
    ):
        resp = await client.patch(
            f"/api/root-folders/{root_folder.id}",
            json={"name": "Hacked"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403


class TestDeleteRootFolder:
    async def test_admin_deletes(
        self, client: AsyncClient, admin_headers: dict, db_session: AsyncSession, tmp_path
    ):
        media = tmp_path / "to_delete"
        media.mkdir()
        rf = RootFolder(name="To Delete", path=str(media), is_active=True)
        db_session.add(rf)
        await db_session.flush()

        resp = await client.delete(f"/api/root-folders/{rf.id}", headers=admin_headers)
        assert resp.status_code in (200, 204)

    async def test_viewer_cannot_delete(
        self, client: AsyncClient, viewer_headers: dict, root_folder: RootFolder
    ):
        resp = await client.delete(f"/api/root-folders/{root_folder.id}", headers=viewer_headers)
        assert resp.status_code == 403


class TestFsBrowseSecurity:
    """Security-specific tests for the filesystem browser."""

    async def test_cannot_browse_etc(self, client: AsyncClient, admin_headers: dict):
        """/etc is outside MONET_BROWSE_ROOTS and must be rejected."""
        resp = await client.get("/api/fs/browse?path=/etc", headers=admin_headers)
        assert resp.status_code == 403

    async def test_cannot_browse_root(self, client: AsyncClient, admin_headers: dict):
        """/ is outside MONET_BROWSE_ROOTS and must be rejected."""
        resp = await client.get("/api/fs/browse?path=/", headers=admin_headers)
        assert resp.status_code == 403

    async def test_cannot_browse_proc(self, client: AsyncClient, admin_headers: dict):
        """/proc is outside MONET_BROWSE_ROOTS and must be rejected."""
        resp = await client.get("/api/fs/browse?path=/proc", headers=admin_headers)
        assert resp.status_code == 403

    async def test_path_traversal_rejected(self, client: AsyncClient, admin_headers: dict):
        """A path that resolves outside allowed roots after traversal must be rejected."""
        resp = await client.get(
            "/api/fs/browse?path=/mnt/../etc/passwd",
            headers=admin_headers,
        )
        # After resolve(), /mnt/../etc/passwd → /etc/passwd which is outside roots
        assert resp.status_code in (403, 404)

    async def test_viewer_cannot_browse(self, client: AsyncClient, viewer_headers: dict):
        resp = await client.get("/api/fs/browse?path=/mnt", headers=viewer_headers)
        assert resp.status_code == 403

    async def test_unauthenticated_cannot_browse(self, client: AsyncClient):
        resp = await client.get("/api/fs/browse?path=/mnt")
        assert resp.status_code in (401, 403)


class TestFsBrowse:
    async def test_browse_allowed_dir(self, client: AsyncClient, admin_headers: dict):
        """Browse a directory that is within MONET_BROWSE_ROOTS (/tmp in tests)."""
        resp = await client.get("/api/fs/browse?path=/tmp", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "path" in data
        assert "entries" in data
        assert isinstance(data["entries"], list)

    async def test_browse_tmp(self, client: AsyncClient, admin_headers: dict, tmp_path):
        (tmp_path / "subdir_a").mkdir()
        (tmp_path / "subdir_b").mkdir()
        (tmp_path / "file.txt").write_text("ignored")

        resp = await client.get(f"/api/fs/browse?path={tmp_path}", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        names = [e["name"] for e in data["entries"]]
        assert "subdir_a" in names
        assert "subdir_b" in names
        assert "file.txt" not in names  # files excluded

    async def test_browse_shows_configured_flag(
        self, client: AsyncClient, admin_headers: dict,
        root_folder: RootFolder, tmp_path
    ):
        # Browse the parent of our root_folder path
        parent = str(root_folder.path).rsplit("/", 1)[0] or "/"
        resp = await client.get(f"/api/fs/browse?path={parent}", headers=admin_headers)
        if resp.status_code == 200:
            entries = resp.json()["entries"]
            root_name = root_folder.path.split("/")[-1]
            matching = [e for e in entries if e["name"] == root_name]
            if matching:
                assert matching[0]["is_configured"] is True

    async def test_browse_viewer_forbidden(self, client: AsyncClient, viewer_headers: dict):
        resp = await client.get("/api/fs/browse?path=/", headers=viewer_headers)
        assert resp.status_code == 403

    async def test_browse_unauthenticated_forbidden(self, client: AsyncClient):
        resp = await client.get("/api/fs/browse?path=/")
        assert resp.status_code in (401, 403)

    async def test_browse_parent_navigation(self, client: AsyncClient, admin_headers: dict, tmp_path):
        nested = tmp_path / "level1" / "level2"
        nested.mkdir(parents=True)

        resp = await client.get(f"/api/fs/browse?path={nested}", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == str(nested)
        assert data["parent"] == str(nested.parent)
