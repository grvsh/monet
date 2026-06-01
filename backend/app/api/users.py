from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, require_admin
from app.core.security import hash_password
from app.database import get_session
from app.models.db import RootFolder, User, UserRootPref
from app.models.schemas import (
    RootPrefItem,
    RootPrefsResponse,
    RootPrefsUpdateRequest,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.redis_client import get_redis

router = APIRouter()


def _user_tokens_key(user_id: str) -> str:
    return f"monet:user_tokens:{user_id}"


def _refresh_key(token_uuid: str) -> str:
    return f"monet:refresh:{token_uuid}"


async def _revoke_all_user_tokens(user_id: str) -> None:
    """Delete all refresh tokens for a given user from Redis."""
    redis = await get_redis()
    token_uuids = await redis.smembers(_user_tokens_key(user_id))
    if token_uuids:
        keys = [_refresh_key(t) for t in token_uuids]
        await redis.delete(*keys)
    await redis.delete(_user_tokens_key(user_id))


@router.get("", response_model=list[UserResponse])
async def list_users(
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[UserResponse]:
    """List all users (admin only)."""
    result = await session.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    return [UserResponse.model_validate(u) for u in users]


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    body: UserCreate,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    """Create a new user (admin only)."""
    # Check for duplicate email
    existing = await session.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    """Update a user's profile/role/status (admin only)."""
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.full_name is not None:
        user.full_name = body.full_name
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        if not body.is_active and user.is_active:
            # Deactivating — revoke all refresh tokens
            await _revoke_all_user_tokens(str(user.id))
        user.is_active = body.is_active

    await session.commit()
    await session.refresh(user)
    return UserResponse.model_validate(user)


@router.delete("/{user_id}", status_code=204)
async def deactivate_user(
    user_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Soft-delete (deactivate) a user and revoke all their refresh tokens (admin only)."""
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_active:
        await _revoke_all_user_tokens(str(user.id))
    user.is_active = False
    await session.commit()


# ---------------------------------------------------------------------------
# Preferences for the current user
# ---------------------------------------------------------------------------


class UpdatePreferencesRequest(BaseModel):
    allow_disk_deletion: bool | None = None
    face_cluster_min_size: int | None = None


@router.patch("/me/preferences", response_model=UserResponse)
async def update_my_preferences(
    body: UpdatePreferencesRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    if body.allow_disk_deletion is not None:
        current_user.allow_disk_deletion = body.allow_disk_deletion
    if body.face_cluster_min_size is not None:
        current_user.face_cluster_min_size = max(1, body.face_cluster_min_size)
    await session.commit()
    await session.refresh(current_user)
    return UserResponse.model_validate(current_user)


# ---------------------------------------------------------------------------
# Root-prefs for the current user
# ---------------------------------------------------------------------------


@router.get("/me/root-prefs", response_model=RootPrefsResponse)
async def get_my_root_prefs(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RootPrefsResponse:
    """Return the current user's root folder visibility prefs.

    Performs a LEFT JOIN so that root folders with no explicit pref row
    are returned with is_visible=True (the default).
    """
    # Get all active root folders
    rf_result = await session.execute(
        select(RootFolder).where(RootFolder.is_active == True)  # noqa: E712
    )
    all_roots = rf_result.scalars().all()

    # Get existing prefs for this user
    prefs_result = await session.execute(
        select(UserRootPref).where(UserRootPref.user_id == current_user.id)
    )
    pref_map: dict[uuid.UUID, bool] = {
        p.root_folder_id: p.is_visible for p in prefs_result.scalars().all()
    }

    prefs = [
        RootPrefItem(
            root_folder_id=rf.id,
            is_visible=pref_map.get(rf.id, True),  # Default: visible
        )
        for rf in all_roots
    ]
    return RootPrefsResponse(prefs=prefs)


@router.put("/me/root-prefs", response_model=RootPrefsResponse)
async def set_my_root_prefs(
    body: RootPrefsUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RootPrefsResponse:
    """Upsert the current user's root folder visibility prefs."""
    for item in body.prefs:
        existing = await session.get(
            UserRootPref, {"user_id": current_user.id, "root_folder_id": item.root_folder_id}
        )
        if existing:
            existing.is_visible = item.is_visible
        else:
            pref = UserRootPref(
                user_id=current_user.id,
                root_folder_id=item.root_folder_id,
                is_visible=item.is_visible,
            )
            session.add(pref)
    await session.flush()

    # Reload all prefs and return
    rf_result = await session.execute(
        select(RootFolder).where(RootFolder.is_active == True)  # noqa: E712
    )
    all_roots = rf_result.scalars().all()
    prefs_result = await session.execute(
        select(UserRootPref).where(UserRootPref.user_id == current_user.id)
    )
    pref_map: dict[uuid.UUID, bool] = {
        p.root_folder_id: p.is_visible for p in prefs_result.scalars().all()
    }
    prefs = [
        RootPrefItem(
            root_folder_id=rf.id,
            is_visible=pref_map.get(rf.id, True),
        )
        for rf in all_roots
    ]
    return RootPrefsResponse(prefs=prefs)
