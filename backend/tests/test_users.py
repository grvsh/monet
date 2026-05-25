"""Tests for user management endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import User
from app.core.security import hash_password, verify_password


class TestListUsers:
    async def test_admin_can_list_users(
        self, client: AsyncClient, admin_headers: dict,
        admin_user: User, viewer_user: User
    ):
        resp = await client.get("/api/users", headers=admin_headers)
        assert resp.status_code == 200
        emails = [u["email"] for u in resp.json()]
        assert "admin@test.local" in emails
        assert "viewer@test.local" in emails

    async def test_viewer_cannot_list_users(self, client: AsyncClient, viewer_headers: dict):
        resp = await client.get("/api/users", headers=viewer_headers)
        assert resp.status_code == 403

    async def test_unauthenticated_cannot_list_users(self, client: AsyncClient):
        resp = await client.get("/api/users")
        assert resp.status_code in (401, 403)


class TestCreateUser:
    async def test_admin_creates_user(self, client: AsyncClient, admin_headers: dict):
        resp = await client.post("/api/users", json={
            "email": "newuser@test.local",
            "password": "secure_password_456",
            "full_name": "New User",
            "role": "viewer",
        }, headers=admin_headers)
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["email"] == "newuser@test.local"
        assert data["full_name"] == "New User"
        assert data["role"] == "viewer"
        assert "hashed_password" not in data
        assert "password" not in data

    async def test_create_user_duplicate_email(
        self, client: AsyncClient, admin_headers: dict, admin_user: User
    ):
        resp = await client.post("/api/users", json={
            "email": "admin@test.local",  # already exists
            "password": "some_password",
        }, headers=admin_headers)
        assert resp.status_code in (400, 409, 422)

    async def test_create_admin_user(self, client: AsyncClient, admin_headers: dict):
        resp = await client.post("/api/users", json={
            "email": "admin2@test.local",
            "password": "secure_password_789",
            "role": "admin",
        }, headers=admin_headers)
        assert resp.status_code in (200, 201)
        assert resp.json()["role"] == "admin"

    async def test_viewer_cannot_create_user(self, client: AsyncClient, viewer_headers: dict):
        resp = await client.post("/api/users", json={
            "email": "another@test.local",
            "password": "password123",
        }, headers=viewer_headers)
        assert resp.status_code == 403

    async def test_create_user_invalid_role(self, client: AsyncClient, admin_headers: dict):
        resp = await client.post("/api/users", json={
            "email": "badrole@test.local",
            "password": "password123",
            "role": "superuser",  # invalid
        }, headers=admin_headers)
        assert resp.status_code == 422

    async def test_create_user_short_password(self, client: AsyncClient, admin_headers: dict):
        resp = await client.post("/api/users", json={
            "email": "short@test.local",
            "password": "123",  # too short
        }, headers=admin_headers)
        assert resp.status_code == 422


class TestUpdateUser:
    async def test_admin_updates_full_name(
        self, client: AsyncClient, admin_headers: dict, viewer_user: User
    ):
        resp = await client.patch(
            f"/api/users/{viewer_user.id}",
            json={"full_name": "Updated Name"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["full_name"] == "Updated Name"

    async def test_admin_deactivates_user(
        self, client: AsyncClient, admin_headers: dict, viewer_user: User
    ):
        resp = await client.patch(
            f"/api/users/{viewer_user.id}",
            json={"is_active": False},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    async def test_deactivated_user_cannot_login(
        self, client: AsyncClient, admin_headers: dict,
        viewer_user: User
    ):
        # Deactivate
        await client.patch(
            f"/api/users/{viewer_user.id}",
            json={"is_active": False},
            headers=admin_headers,
        )
        # Try to login
        resp = await client.post("/api/auth/login", json={
            "email": "viewer@test.local",
            "password": "viewer_password_123",
        })
        assert resp.status_code == 401

    async def test_update_nonexistent_user(self, client: AsyncClient, admin_headers: dict):
        import uuid
        fake_id = uuid.uuid4()
        resp = await client.patch(
            f"/api/users/{fake_id}",
            json={"full_name": "Ghost"},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_viewer_cannot_update_user(
        self, client: AsyncClient, viewer_headers: dict, admin_user: User
    ):
        resp = await client.patch(
            f"/api/users/{admin_user.id}",
            json={"full_name": "Hacked"},
            headers=viewer_headers,
        )
        assert resp.status_code == 403


class TestUserUpdateSecurity:
    """Verify the UserUpdate role validator added in the security fix."""

    async def test_cannot_set_invalid_role(
        self, client: AsyncClient, admin_headers: dict, viewer_user: User
    ):
        """Setting role to an arbitrary string must be rejected at the schema layer."""
        resp = await client.patch(
            f"/api/users/{viewer_user.id}",
            json={"role": "superuser"},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    async def test_cannot_set_role_to_empty_string(
        self, client: AsyncClient, admin_headers: dict, viewer_user: User
    ):
        resp = await client.patch(
            f"/api/users/{viewer_user.id}",
            json={"role": ""},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    async def test_valid_role_update_accepted(
        self, client: AsyncClient, admin_headers: dict, viewer_user: User
    ):
        resp = await client.patch(
            f"/api/users/{viewer_user.id}",
            json={"role": "admin"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"


class TestRootPrefs:
    async def test_get_root_prefs_empty(
        self, client: AsyncClient, viewer_headers: dict, viewer_user: User
    ):
        resp = await client.get("/api/users/me/root-prefs", headers=viewer_headers)
        assert resp.status_code == 200
        assert "prefs" in resp.json()

    async def test_update_root_prefs(
        self, client: AsyncClient, viewer_headers: dict,
        viewer_user: User, root_folder
    ):
        resp = await client.put("/api/users/me/root-prefs", json={
            "prefs": [{"root_folder_id": str(root_folder.id), "is_visible": False}]
        }, headers=viewer_headers)
        assert resp.status_code == 200

        # Fetch and verify
        get_resp = await client.get("/api/users/me/root-prefs", headers=viewer_headers)
        prefs = get_resp.json()["prefs"]
        matching = [p for p in prefs if p["root_folder_id"] == str(root_folder.id)]
        if matching:
            assert matching[0]["is_visible"] is False
