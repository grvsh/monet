"""
Pytest configuration and shared fixtures for Monet backend tests.

Test database: controlled by TEST_DATABASE_URL env var (defaults to in-memory
SQLite for unit tests, or PostgreSQL for integration tests via docker-compose.test.yml).

Each test gets its own transaction that is rolled back on teardown — no state leaks.
"""
from __future__ import annotations

import asyncio
import io
import os
import struct
import uuid
from collections.abc import AsyncGenerator, Generator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ── Database URL ──────────────────────────────────────────────────────────────

TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://monet_test:monet_test_password@localhost:5433/monet_test",
)
TEST_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6380/0")
TEST_CACHE_DIR = os.environ.get("MONET_CACHE_DIR", "/tmp/monet_test_cache")

# Override settings BEFORE importing app modules
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("REDIS_URL", TEST_REDIS_URL)
os.environ.setdefault("MONET_CACHE_DIR", TEST_CACHE_DIR)
os.environ.setdefault("JWT_SECRET_KEY", "test_secret_key_not_for_production_use_only_32b")
os.environ.setdefault("MONET_WATCH_ENABLED", "false")
os.environ.setdefault("MONET_SCAN_ON_STARTUP", "false")

# Now import app modules (settings are already patched via env)
from app.core.security import hash_password
from app.database import get_session
from app.main import app
from app.models.db import (
    Base,
    FileMetadata,
    Folder,
    MediaFile,
    RootFolder,
    ScanJob,
    User,
    UserRootPref,
)
from app.redis_client import get_redis

# ── Async test mode ───────────────────────────────────────────────────────────

pytest_plugins = ("anyio",)


# ── Engine / schema setup (session-scoped) ─────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    """Create the test engine and tables once per session."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pgcrypto"'))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── Per-test transaction rollback ─────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Each test runs inside a savepoint that is rolled back on teardown."""
    async with db_engine.connect() as conn:
        await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        await conn.begin_nested()  # savepoint

        @event.listens_for(session.sync_session, "after_transaction_end")
        def restart_savepoint(session_, transaction):
            if transaction.nested and not transaction._parent.nested:
                session_.begin_nested()

        yield session

        await session.close()
        await conn.rollback()


# ── Redis mock ────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_redis():
    """In-memory dict-backed Redis mock."""
    store: dict[str, Any] = {}
    sets: dict[str, set] = {}

    r = AsyncMock()
    r.set = AsyncMock(side_effect=lambda k, v, ex=None, **kw: store.update({k: v}))
    r.get = AsyncMock(side_effect=lambda k: store.get(k))
    r.delete = AsyncMock(side_effect=lambda *keys: [store.pop(k, None) for k in keys])
    r.exists = AsyncMock(side_effect=lambda k: k in store)
    r.expire = AsyncMock(return_value=True)
    r.sadd = AsyncMock(side_effect=lambda k, *vs: sets.setdefault(k, set()).update(vs))
    r.smembers = AsyncMock(side_effect=lambda k: sets.get(k, set()))
    r.srem = AsyncMock(side_effect=lambda k, *vs: [sets.get(k, set()).discard(v) for v in vs])
    r.enqueue_job = AsyncMock(return_value=None)
    return r


# ── HTTP test client ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(db_session, mock_redis) -> AsyncGenerator[AsyncClient, None]:
    """Full ASGI test client with DB and Redis overridden."""
    async def override_session():
        yield db_session

    async def override_redis():
        return mock_redis

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_redis] = override_redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ── User fixtures ─────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email="admin@test.local",
        hashed_password=hash_password("admin_password_123"),
        full_name="Test Admin",
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def viewer_user(db_session: AsyncSession) -> User:
    user = User(
        email="viewer@test.local",
        hashed_password=hash_password("viewer_password_123"),
        full_name="Test Viewer",
        role="viewer",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def admin_token(client: AsyncClient, admin_user: User, mock_redis) -> str:
    """Log in as admin and return access token."""
    resp = await client.post("/api/auth/login", json={
        "email": "admin@test.local",
        "password": "admin_password_123",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def viewer_token(client: AsyncClient, viewer_user: User, mock_redis) -> str:
    resp = await client.post("/api/auth/login", json={
        "email": "viewer@test.local",
        "password": "viewer_password_123",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture
def admin_headers(admin_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def viewer_headers(viewer_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {viewer_token}"}


# ── Media fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_media_dir(tmp_path: Path) -> Path:
    """A temporary directory tree with some media files."""
    media = tmp_path / "media"
    (media / "2024" / "vacation").mkdir(parents=True)
    (media / "2024" / "winter").mkdir(parents=True)
    (media / "2023").mkdir(parents=True)

    def tiny_jpeg(color=(200, 100, 80)) -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (10, 10), color).save(buf, "JPEG")
        return buf.getvalue()

    def tiny_mp4() -> bytes:
        def box(fc, payload=b""):
            return struct.pack(">I4s", 8 + len(payload), fc.encode()) + payload
        return box("ftyp", b"isom" + struct.pack(">I", 0) + b"isommp41") + box("mdat", b"\x00" * 8)

    # 2024/vacation
    (media / "2024" / "vacation" / "IMG_001.jpg").write_bytes(tiny_jpeg((200, 100, 80)))
    (media / "2024" / "vacation" / "IMG_002.jpg").write_bytes(tiny_jpeg((80, 200, 100)))
    (media / "2024" / "vacation" / "clip.mp4").write_bytes(tiny_mp4())
    (media / "2024" / "vacation" / "notes.txt").write_text("should be ignored")

    # 2024/winter
    (media / "2024" / "winter" / "IMG_010.jpg").write_bytes(tiny_jpeg((100, 100, 200)))

    # 2023
    (media / "2023" / "old_photo.jpg").write_bytes(tiny_jpeg((150, 150, 50)))

    return media


@pytest_asyncio.fixture
async def root_folder(db_session: AsyncSession, admin_user: User, tmp_media_dir: Path) -> RootFolder:
    rf = RootFolder(
        name="Test Library",
        path=str(tmp_media_dir),
        is_active=True,
        created_by=admin_user.id,
    )
    db_session.add(rf)
    await db_session.flush()
    return rf


@pytest_asyncio.fixture
async def folder_2024(db_session: AsyncSession, root_folder: RootFolder) -> Folder:
    f = Folder(
        root_folder_id=root_folder.id,
        parent_id=None,
        path="2024",
        name="2024",
        file_count=0,
        child_folder_count=2,
    )
    db_session.add(f)
    await db_session.flush()
    return f


@pytest_asyncio.fixture
async def folder_vacation(db_session: AsyncSession, root_folder: RootFolder, folder_2024: Folder) -> Folder:
    f = Folder(
        root_folder_id=root_folder.id,
        parent_id=folder_2024.id,
        path="2024/vacation",
        name="vacation",
        file_count=3,
        child_folder_count=0,
    )
    db_session.add(f)
    await db_session.flush()
    return f


@pytest_asyncio.fixture
async def media_file_jpg(
    db_session: AsyncSession, root_folder: RootFolder, folder_vacation: Folder
) -> MediaFile:
    mf = MediaFile(
        folder_id=folder_vacation.id,
        root_folder_id=root_folder.id,
        path="2024/vacation/IMG_001.jpg",
        filename="IMG_001.jpg",
        extension="jpg",
        media_type="image",
        mime_type="image/jpeg",
        is_raw=False,
        size_bytes=12345,
        mtime=datetime(2024, 7, 14, 9, 22, 41, tzinfo=timezone.utc),
        width=4000,
        height=3000,
        taken_at=datetime(2024, 7, 14, 9, 22, 41, tzinfo=timezone.utc),
        camera_make="Canon",
        camera_model="Canon EOS R5",
        lens_model="RF 85mm F1.2 L USM",
        focal_length_mm=85.0,
        aperture=1.2,
        shutter_speed="1/500",
        iso=100,
        gps_lat=48.8566,
        gps_lon=2.3522,
    )
    db_session.add(mf)
    await db_session.flush()
    return mf


@pytest_asyncio.fixture
async def media_file_video(
    db_session: AsyncSession, root_folder: RootFolder, folder_vacation: Folder
) -> MediaFile:
    mf = MediaFile(
        folder_id=folder_vacation.id,
        root_folder_id=root_folder.id,
        path="2024/vacation/clip.mp4",
        filename="clip.mp4",
        extension="mp4",
        media_type="video",
        mime_type="video/mp4",
        is_raw=False,
        size_bytes=524288,
        mtime=datetime(2024, 7, 14, 10, 0, 0, tzinfo=timezone.utc),
        width=1920,
        height=1080,
        duration_sec=30.5,
        taken_at=datetime(2024, 7, 14, 10, 0, 0, tzinfo=timezone.utc),
        camera_make="Apple",
        camera_model="iPhone 15 Pro",
    )
    db_session.add(mf)
    await db_session.flush()
    return mf


# ── Fixture paths ─────────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def fixture_path(name: str) -> Path:
    """Return path to a named test fixture file, skipping if it doesn't exist."""
    p = FIXTURES_DIR / name
    if not p.exists():
        pytest.skip(f"Fixture file not found: {p}. Run: python scripts/create_test_fixtures.py")
    return p
