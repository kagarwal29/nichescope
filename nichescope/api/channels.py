"""Channel management API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nichescope.api.auth import get_current_user
from nichescope.models import Channel, Niche, User, get_db
from nichescope.services.channel_ingester import ingest_channel, ingest_channel_by_handle

router = APIRouter(prefix="/api/channels", tags=["channels"])


class AddChannelRequest(BaseModel):
    niche_id: int
    channel_id: str | None = None  # UC... YouTube channel ID
    handle: str | None = None  # @handle


class NicheCreateRequest(BaseModel):
    name: str
    seed_keywords: list[str] = []


@router.post("/niches")
async def create_niche(
    req: NicheCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new niche for the user."""
    import json

    niche = Niche(
        user_id=user.id,
        name=req.name,
        seed_keywords=json.dumps(req.seed_keywords),
    )
    db.add(niche)
    await db.commit()
    await db.refresh(niche)
    return {"niche_id": niche.id, "name": niche.name}


@router.get("/niches")
async def list_niches(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List user's niches."""
    stmt = select(Niche).where(Niche.user_id == user.id)
    result = await db.execute(stmt)
    niches = result.scalars().all()
    return [{"id": n.id, "name": n.name} for n in niches]


@router.post("")
async def add_competitor(
    req: AddChannelRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a competitor channel to a niche. Triggers full video ingestion."""
    niche = await db.get(Niche, req.niche_id)
    if not niche or niche.user_id != user.id:
        raise HTTPException(status_code=404, detail="Niche not found")

    # Check competitor limit
    current_count = len(niche.competitor_channels) if niche.competitor_channels else 0
    if current_count >= user.max_competitors():
        raise HTTPException(
            status_code=403,
            detail=f"Competitor limit reached ({user.max_competitors()} for {user.tier} tier)",
        )

    # Ingest channel
    try:
        if req.handle:
            channel = await ingest_channel_by_handle(db, req.handle)
        elif req.channel_id:
            channel = await ingest_channel(db, req.channel_id)
        else:
            raise HTTPException(status_code=400, detail="Provide channel_id or handle")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Link to niche
    if channel not in niche.competitor_channels:
        niche.competitor_channels.append(channel)
        await db.commit()

    return {
        "channel_id": channel.id,
        "youtube_channel_id": channel.youtube_channel_id,
        "title": channel.title,
        "subscriber_count": channel.subscriber_count,
        "video_count": channel.video_count,
    }


@router.get("")
async def list_channels(
    niche_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List competitor channels in a niche."""
    niche = await db.get(Niche, niche_id)
    if not niche or niche.user_id != user.id:
        raise HTTPException(status_code=404, detail="Niche not found")

    return [
        {
            "id": c.id,
            "youtube_channel_id": c.youtube_channel_id,
            "title": c.title,
            "handle": c.handle,
            "subscriber_count": c.subscriber_count,
        }
        for c in niche.competitor_channels
    ]


@router.delete("/{channel_id}")
async def remove_competitor(
    channel_id: int,
    niche_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a competitor from a niche."""
    niche = await db.get(Niche, niche_id)
    if not niche or niche.user_id != user.id:
        raise HTTPException(status_code=404, detail="Niche not found")

    channel = await db.get(Channel, channel_id)
    if channel and channel in niche.competitor_channels:
        niche.competitor_channels.remove(channel)
        await db.commit()

    return {"status": "removed"}
