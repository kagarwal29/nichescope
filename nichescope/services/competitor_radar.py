"""Competitor radar — tracks competitor movements and generates alerts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nichescope.models import Channel, Niche, Video
from nichescope.models.channel import niche_channels

logger = logging.getLogger(__name__)


@dataclass
class CompetitorInsight:
    """Summary of a competitor's recent activity."""

    channel_title: str
    handle: str
    subscriber_count: int
    recent_videos: list[dict]  # [{title, views, published_at, views_per_day}]
    total_views_7d: int
    videos_posted_7d: int
    avg_views_per_video: int
    top_topic: str | None


@dataclass
class CompetitorAlert:
    """Alert about a competitor's notable activity."""

    channel_title: str
    alert_type: str  # "new_video" | "viral" | "growth_spike" | "gap_covered"
    message: str
    video_title: str | None = None
    video_url: str | None = None


async def analyze_competitor(
    session: AsyncSession,
    channel_id: int,
) -> CompetitorInsight:
    """Generate a deep-dive report on a single competitor."""
    channel = await session.get(Channel, channel_id)
    if not channel:
        raise ValueError(f"Channel {channel_id} not found")

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # Recent videos
    recent_stmt = (
        select(Video)
        .where(Video.channel_id == channel_id)
        .order_by(Video.published_at.desc())
        .limit(10)
    )
    result = await session.execute(recent_stmt)
    recent_videos = result.scalars().all()

    video_dicts = [
        {
            "title": v.title,
            "views": v.view_count,
            "published_at": v.published_at.isoformat() if v.published_at else "",
            "views_per_day": round(v.views_per_day, 1),
            "url": f"https://youtube.com/watch?v={v.youtube_video_id}",
        }
        for v in recent_videos
    ]

    # 7-day stats
    week_vids = [v for v in recent_videos if v.published_at and v.published_at >= week_ago]
    total_views_7d = sum(v.view_count for v in week_vids)
    avg_views = total_views_7d // len(week_vids) if week_vids else 0

    # Top topic — explicit query to avoid lazy-loading greenlet crash
    top_topic = None
    if recent_videos:
        first_video = list(recent_videos)[0]
        if first_video.topic_cluster_id:
            from nichescope.models import TopicCluster
            tc_stmt = select(TopicCluster).where(TopicCluster.id == first_video.topic_cluster_id)
            tc_result = await session.execute(tc_stmt)
            tc = tc_result.scalar_one_or_none()
            if tc:
                top_topic = tc.label

    return CompetitorInsight(
        channel_title=channel.title,
        handle=channel.handle or "",
        subscriber_count=channel.subscriber_count,
        recent_videos=video_dicts,
        total_views_7d=total_views_7d,
        videos_posted_7d=len(week_vids),
        avg_views_per_video=avg_views,
        top_topic=top_topic,
    )


async def detect_competitor_alerts(
    session: AsyncSession,
    niche_id: int,
) -> list[CompetitorAlert]:
    """Scan all competitors in a niche for notable activity. Returns alerts."""

    # Get competitor channels
    stmt = (
        select(Channel)
        .join(niche_channels, niche_channels.c.channel_id == Channel.id)
        .where(niche_channels.c.niche_id == niche_id)
    )
    result = await session.execute(stmt)
    channels = list(result.scalars().all())

    now = datetime.now(timezone.utc)
    alerts: list[CompetitorAlert] = []

    for channel in channels:
        # Check for new videos in last hour (for push alerts)
        recent_stmt = (
            select(Video)
            .where(Video.channel_id == channel.id)
            .where(Video.published_at >= now - timedelta(hours=1))
        )
        recent_result = await session.execute(recent_stmt)
        new_videos = list(recent_result.scalars().all())

        for video in new_videos:
            alerts.append(
                CompetitorAlert(
                    channel_title=channel.title,
                    alert_type="new_video",
                    message=f"📹 {channel.title} just posted: \"{video.title}\"",
                    video_title=video.title,
                    video_url=f"https://youtube.com/watch?v={video.youtube_video_id}",
                )
            )

        # Check for viral videos (3x baseline views_per_day)
        baseline_stmt = (
            select(func.avg(Video.views_per_day))
            .where(Video.channel_id == channel.id)
            .where(Video.published_at >= now - timedelta(days=90))
        )
        baseline_result = await session.execute(baseline_stmt)
        baseline_vpd = baseline_result.scalar() or 0

        if baseline_vpd > 0:
            viral_stmt = (
                select(Video)
                .where(Video.channel_id == channel.id)
                .where(Video.published_at >= now - timedelta(days=3))
                .where(Video.views_per_day > baseline_vpd * 3)
            )
            viral_result = await session.execute(viral_stmt)
            for video in viral_result.scalars().all():
                alerts.append(
                    CompetitorAlert(
                        channel_title=channel.title,
                        alert_type="viral",
                        message=(
                            f"🔥 {channel.title}'s video \"{video.title}\" is going viral! "
                            f"{video.view_count:,} views ({video.views_per_day:.0f}/day vs {baseline_vpd:.0f} baseline)"
                        ),
                        video_title=video.title,
                        video_url=f"https://youtube.com/watch?v={video.youtube_video_id}",
                    )
                )

    return alerts
