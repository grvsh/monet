from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import create_access_token, get_current_user
from app.core.limiter import limiter
from app.core.security import DUMMY_HASH, verify_password
from app.database import get_session
from app.models.db import User
from app.models.schemas import LoginRequest, TokenResponse, UserResponse
from app.redis_client import get_redis

router = APIRouter()

_REFRESH_COOKIE = "refresh_token"
_REFRESH_TTL = settings.refresh_token_expire_days * 86400
_ACCESS_COOKIE = "access_token"
_ACCESS_TTL = settings.access_token_expire_minutes * 60


def _refresh_key(token_uuid: str) -> str:
    return f"monet:refresh:{token_uuid}"


def _user_tokens_key(user_id: str) -> str:
    return f"monet:user_tokens:{user_id}"


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.login_rate_limit)
async def login(
    request: Request,       # required by slowapi for IP-based rate limiting
    body: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Authenticate user, issue access token in body + refresh token as HttpOnly cookie.

    Rate-limited to settings.login_rate_limit per IP.  Uses a constant-time
    password comparison even when the email does not exist to prevent user
    enumeration via response-timing differences.
    """
    stmt = select(User).where(User.email == body.email)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        # Run a dummy bcrypt verify so the response time is indistinguishable
        # from a real wrong-password attempt (~100 ms).
        verify_password(body.password, DUMMY_HASH)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Update last_login_at
    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()

    access_token = create_access_token(user.id, user.role)

    # Generate an opaque refresh token UUID and store in Redis with TTL
    token_uuid = str(uuid.uuid4())
    redis = await get_redis()
    await redis.setex(_refresh_key(token_uuid), _REFRESH_TTL, str(user.id))
    # Track token UUID in a per-user set for bulk revocation on deactivation
    await redis.sadd(_user_tokens_key(str(user.id)), token_uuid)
    await redis.expire(_user_tokens_key(str(user.id)), _REFRESH_TTL)

    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=token_uuid,
        httponly=True,
        max_age=_REFRESH_TTL,
        samesite="lax",
        secure=settings.monet_secure_cookies,
    )
    response.set_cookie(
        key=_ACCESS_COOKIE,
        value=access_token,
        httponly=False,
        max_age=_ACCESS_TTL,
        samesite="lax",
        secure=settings.monet_secure_cookies,
    )

    return TokenResponse(
        access_token=access_token,
        user=UserResponse.model_validate(user),
    )


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Validate refresh token cookie, issue a fresh access token."""
    token_uuid = request.cookies.get(_REFRESH_COOKIE)
    if not token_uuid:
        raise HTTPException(status_code=401, detail="No refresh token cookie")

    redis = await get_redis()
    user_id_str = await redis.get(_refresh_key(token_uuid))
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Refresh token expired or invalid")

    user = await session.get(User, uuid.UUID(user_id_str))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    access_token = create_access_token(user.id, user.role)
    response.set_cookie(
        key=_ACCESS_COOKIE,
        value=access_token,
        httponly=False,
        max_age=_ACCESS_TTL,
        samesite="lax",
        secure=settings.monet_secure_cookies,
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
) -> dict:
    """Invalidate the refresh token in Redis and clear the cookie."""
    token_uuid = request.cookies.get(_REFRESH_COOKIE)
    if token_uuid:
        redis = await get_redis()
        user_id_str = await redis.get(_refresh_key(token_uuid))
        await redis.delete(_refresh_key(token_uuid))
        if user_id_str:
            await redis.srem(_user_tokens_key(user_id_str), token_uuid)

    response.delete_cookie(key=_REFRESH_COOKIE, httponly=True, samesite="lax")
    response.delete_cookie(key=_ACCESS_COOKIE, samesite="lax")
    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the current authenticated user's profile."""
    return UserResponse.model_validate(current_user)
