"""Authentication routes — API key auth + YouTube OAuth2."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nichescope.models import User, get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


async def get_current_user(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency: resolve API key → User. Raises 401 if invalid."""
    stmt = select(User).where(User.api_key == x_api_key)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return user


@router.post("/register")
async def register(
    telegram_chat_id: int | None = None,
    youtube_channel_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Create a new user account. Returns the API key (show once)."""
    api_key = secrets.token_urlsafe(32)
    user = User(
        telegram_chat_id=telegram_chat_id,
        youtube_channel_id=youtube_channel_id,
        api_key=api_key,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return {
        "user_id": user.id,
        "api_key": api_key,
        "message": "Save your API key — it won't be shown again.",
    }


@router.post("/youtube/callback")
async def youtube_oauth_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
):
    """Handle YouTube OAuth2 callback. Stores access + refresh tokens.

    Full OAuth flow to be implemented with google-auth-oauthlib.
    This is the callback endpoint that YouTube redirects to.
    """
    # TODO: Exchange code for tokens using google-auth-oauthlib
    # For MVP, users provide their channel ID directly
    return {"status": "ok", "message": "YouTube OAuth callback — implement with google-auth-oauthlib"}
