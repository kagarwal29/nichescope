"""Forward-looking feature API routes — features no competitor offers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from nichescope.api.auth import get_current_user
from nichescope.models import Channel, Niche, User, get_db

router = APIRouter(prefix="/api/insights", tags=["insights"])


class TitleScoreRequest(BaseModel):
    niche_id: int
    titles: list[str]


# ---------- Comment Demand Mining ----------

@router.get("/demands")
async def get_audience_demands(
    niche_id: int,
    max_videos: int = 15,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mine viewer comment requests — what your audience is ASKING for.

    Extracts "can you make a video about..." patterns from competitor comments.
    Returns ranked demand signals with strength scores.
    """
    niche = await db.get(Niche, niche_id)
    if not niche or niche.user_id != user.id:
        raise HTTPException(status_code=404, detail="Niche not found")

    from nichescope.services.comment_demand import mine_comment_demands

    clusters = await mine_comment_demands(db, niche_id, max_videos=max_videos)

    return {
        "niche": niche.name,
        "demand_signals": [
            {
                "topic": c.topic,
                "request_count": c.request_count,
                "total_likes": c.total_likes,
                "strength_score": c.strength_score,
                "example_requests": c.example_requests,
                "source_channels": c.source_channels,
            }
            for c in clusters[:10]
        ],
    }


# ---------- Seasonal Content Calendar ----------

@router.get("/calendar")
async def get_content_calendar(
    niche_id: int,
    weeks_ahead: int = 8,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a seasonal content calendar — know WHEN to publish each topic.

    Predicts topic spikes from 12+ months of historical data.
    Recommends publishing 2 weeks before each seasonal peak.
    """
    niche = await db.get(Niche, niche_id)
    if not niche or niche.user_id != user.id:
        raise HTTPException(status_code=404, detail="Niche not found")

    from nichescope.services.seasonal_calendar import generate_content_calendar

    entries = await generate_content_calendar(db, niche_id, lookahead_weeks=weeks_ahead)

    return {
        "niche": niche.name,
        "calendar": [
            {
                "topic": e.topic_label,
                "publish_window": e.recommended_publish_window,
                "peak_month": e.peak_month,
                "peak_multiplier": e.peak_multiplier,
                "reason": e.reason,
                "urgency": e.urgency,
            }
            for e in entries
        ],
    }


# ---------- Collaboration Opportunities ----------

@router.get("/collabs")
async def get_collab_opportunities(
    niche_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Find optimal collaboration partners — high relevance, low audience overlap.

    Maps the collaboration graph across your niche and identifies
    untapped partners where a collab would expose you to maximum new viewers.
    """
    niche = await db.get(Niche, niche_id)
    if not niche or niche.user_id != user.id:
        raise HTTPException(status_code=404, detail="Niche not found")

    from nichescope.services.collab_graph import find_collab_opportunities

    # Find user's channel
    user_channel = None
    if user.youtube_channel_id:
        from nichescope.models import Channel
        from sqlalchemy import select

        ch_stmt = select(Channel).where(Channel.youtube_channel_id == user.youtube_channel_id)
        ch_result = await db.execute(ch_stmt)
        ch = ch_result.scalar_one_or_none()
        user_channel = ch.id if ch else None

    opps = await find_collab_opportunities(db, niche_id, user_channel_id=user_channel)

    return {
        "niche": niche.name,
        "opportunities": [
            {
                "channel": o.channel_title,
                "handle": o.handle,
                "subscribers": o.subscriber_count,
                "topic_overlap": o.topic_overlap_score,
                "audience_overlap": o.audience_overlap_estimate,
                "potential_new_viewers": o.potential_reach,
                "shared_topics": o.shared_topics,
                "existing_collabs": o.existing_collabs,
                "reason": o.reason,
            }
            for o in opps[:10]
        ],
    }


# ---------- Format Intelligence ----------

@router.get("/formats")
async def get_format_insights(
    niche_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Discover which video formats perform best per topic.

    Answers: "For meal prep, 12-min tutorials get 2.4x more views than vlogs."
    """
    niche = await db.get(Niche, niche_id)
    if not niche or niche.user_id != user.id:
        raise HTTPException(status_code=404, detail="Niche not found")

    from nichescope.services.format_intel import analyze_format_performance

    insights = await analyze_format_performance(db, niche_id)

    return {
        "niche": niche.name,
        "format_insights": [
            {
                "topic": i.topic_label,
                "best_format": i.best_format,
                "best_duration": i.best_duration,
                "best_avg_views": i.best_avg_views,
                "worst_format": i.worst_format,
                "worst_avg_views": i.worst_avg_views,
                "multiplier": i.multiplier,
                "recommendation": i.recommendation,
            }
            for i in insights[:10]
        ],
    }


# ---------- Title Predictor ----------

@router.post("/title-score")
async def score_titles(
    req: TitleScoreRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Score title candidates BEFORE publishing — pre-publish A/B testing.

    Analyzes title patterns in your niche and predicts which variant
    will perform best based on historical data.
    """
    niche = await db.get(Niche, req.niche_id)
    if not niche or niche.user_id != user.id:
        raise HTTPException(status_code=404, detail="Niche not found")

    if len(req.titles) > 10:
        raise HTTPException(status_code=400, detail="Max 10 titles per request")

    from nichescope.services.title_predictor import compare_titles

    scores = await compare_titles(db, req.niche_id, req.titles)

    return {
        "niche": niche.name,
        "rankings": [
            {
                "rank": i + 1,
                "title": s.title,
                "score": s.score,
                "strengths": s.strengths,
                "weaknesses": s.weaknesses,
                "suggestions": s.suggestions,
            }
            for i, s in enumerate(scores)
        ],
    }
