"""Content gap analyzer — scores topic opportunities for a user."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nichescope.models import GapScore, Niche, TopicCluster, User, Video
from nichescope.models.channel import niche_channels

logger = logging.getLogger(__name__)


@dataclass
class GapInsight:
    """Human-readable gap insight for a single topic."""

    topic_label: str
    score: float
    avg_views: int
    competitor_video_count: int
    your_video_count: int
    trend: str
    keywords: list[str]
    top_competitor_video_titles: list[str]


async def compute_gap_scores(
    session: AsyncSession,
    user_id: int,
    niche_id: int,
) -> list[GapScore]:
    """Compute content gap scores for all topic clusters in a niche.

    gap_score = (demand × recency_boost) / (supply × (user_coverage + 1))

    Higher score = bigger opportunity.
    """
    user = await session.get(User, user_id)
    if not user:
        raise ValueError(f"User {user_id} not found")

    # Load topic clusters for this niche
    clusters_stmt = select(TopicCluster).where(TopicCluster.niche_id == niche_id)
    clusters_result = await session.execute(clusters_stmt)
    clusters = list(clusters_result.scalars().all())

    if not clusters:
        logger.warning("No topic clusters for niche %d — run clustering first", niche_id)
        return []

    # Count total videos in the niche (for supply normalization)
    total_videos_stmt = (
        select(func.count(Video.id))
        .join(Video.channel)
        .join(niche_channels, niche_channels.c.channel_id == Video.channel_id)
        .where(niche_channels.c.niche_id == niche_id)
    )
    total_result = await session.execute(total_videos_stmt)
    total_videos = total_result.scalar() or 1

    # Count user's videos per topic cluster (if they have a channel)
    user_coverage_map: dict[int, int] = {}
    if user.youtube_channel_id:
        from nichescope.models import Channel

        user_channel_stmt = select(Channel).where(
            Channel.youtube_channel_id == user.youtube_channel_id
        )
        uc_result = await session.execute(user_channel_stmt)
        user_channel = uc_result.scalar_one_or_none()

        if user_channel:
            user_vids_stmt = (
                select(Video.topic_cluster_id, func.count(Video.id))
                .where(Video.channel_id == user_channel.id)
                .where(Video.topic_cluster_id.isnot(None))
                .group_by(Video.topic_cluster_id)
            )
            uv_result = await session.execute(user_vids_stmt)
            user_coverage_map = {row[0]: row[1] for row in uv_result.all()}

    now = datetime.now(timezone.utc)
    scores: list[GapScore] = []

    for cluster in clusters:
        demand = cluster.avg_views
        supply = cluster.video_count / total_videos if total_videos else 1.0
        user_coverage = user_coverage_map.get(cluster.id, 0)
        recency_boost = 1.0 + (0.5 if cluster.trend_direction == "up" else 0.0)

        # Core formula
        score = (demand * recency_boost) / (supply * (user_coverage + 1)) if supply > 0 else 0

        gap = GapScore(
            user_id=user_id,
            topic_cluster_id=cluster.id,
            niche_id=niche_id,
            score=score,
            demand_score=demand,
            supply_score=supply,
            user_coverage=user_coverage,
            recency_boost=recency_boost,
            computed_at=now,
        )
        session.add(gap)
        scores.append(gap)

    await session.commit()
    logger.info("Computed %d gap scores for user %d, niche %d", len(scores), user_id, niche_id)

    return sorted(scores, key=lambda g: g.score, reverse=True)


async def get_top_gaps(
    session: AsyncSession,
    user_id: int,
    niche_id: int,
    limit: int = 5,
) -> list[GapInsight]:
    """Get the top N content gap insights for a user's niche."""
    import json

    stmt = (
        select(GapScore, TopicCluster)
        .join(TopicCluster, GapScore.topic_cluster_id == TopicCluster.id)
        .where(GapScore.user_id == user_id)
        .where(GapScore.niche_id == niche_id)
        .order_by(GapScore.score.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()

    insights: list[GapInsight] = []
    for gap, cluster in rows:
        # Get top competitor videos in this cluster
        top_vids_stmt = (
            select(Video.title)
            .where(Video.topic_cluster_id == cluster.id)
            .order_by(Video.view_count.desc())
            .limit(3)
        )
        vids_result = await session.execute(top_vids_stmt)
        top_titles = [row[0] for row in vids_result.all()]

        insights.append(
            GapInsight(
                topic_label=cluster.label,
                score=round(gap.score, 1),
                avg_views=int(cluster.avg_views),
                competitor_video_count=cluster.video_count,
                your_video_count=gap.user_coverage,
                trend=cluster.trend_direction,
                keywords=json.loads(cluster.keywords) if cluster.keywords else [],
                top_competitor_video_titles=top_titles,
            )
        )

    return insights
