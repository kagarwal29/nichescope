"""Content gap API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from nichescope.api.auth import get_current_user
from nichescope.models import Niche, User, get_db
from nichescope.services.gap_analyzer import get_top_gaps

router = APIRouter(prefix="/api/gaps", tags=["gaps"])


@router.get("")
async def get_gaps(
    niche_id: int,
    limit: int = 5,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get top content gap opportunities for a niche."""
    niche = await db.get(Niche, niche_id)
    if not niche or niche.user_id != user.id:
        raise HTTPException(status_code=404, detail="Niche not found")

    insights = await get_top_gaps(db, user.id, niche_id, limit=limit)

    return {
        "niche": niche.name,
        "gaps": [
            {
                "topic": g.topic_label,
                "score": g.score,
                "avg_views": g.avg_views,
                "competitor_videos": g.competitor_video_count,
                "your_videos": g.your_video_count,
                "trend": g.trend,
                "keywords": g.keywords,
                "example_videos": g.top_competitor_video_titles,
            }
            for g in insights
        ],
    }
