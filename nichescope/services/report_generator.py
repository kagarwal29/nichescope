"""Public channel report generator."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nichescope.models import Channel, Video

logger = logging.getLogger(__name__)


@dataclass
class ChannelReport:
    """Public-facing analysis of a YouTube channel."""

    channel_title: str
    handle: str
    subscriber_count: int
    total_videos_analyzed: int
    avg_views_per_video: int
    avg_views_last_30d: int
    posting_frequency: str  # "3.2 videos/week"
    top_videos: list[dict]
    topic_breakdown: list[dict]  # [{topic, video_count, avg_views}]
    consistency_score: float  # 0-100
    growth_signal: str  # "accelerating" | "steady" | "declining"
    generated_at: str

    def to_dict(self) -> dict:
        return asdict(self)


async def generate_channel_report(
    session: AsyncSession,
    youtube_channel_id: str,
) -> ChannelReport | None:
    """Generate a public report for any YouTube channel."""

    stmt = select(Channel).where(Channel.youtube_channel_id == youtube_channel_id)
    result = await session.execute(stmt)
    channel = result.scalar_one_or_none()

    if not channel:
        return None

    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)
    ninety_days_ago = now - timedelta(days=90)

    # All videos
    all_vids_stmt = (
        select(Video)
        .where(Video.channel_id == channel.id)
        .order_by(Video.view_count.desc())
    )
    all_result = await session.execute(all_vids_stmt)
    all_videos = list(all_result.scalars().all())

    if not all_videos:
        return None

    # Overall avg views
    avg_views = sum(v.view_count for v in all_videos) // len(all_videos)

    # 30-day avg views
    recent = [v for v in all_videos if v.published_at and v.published_at >= thirty_days_ago]
    avg_views_30d = sum(v.view_count for v in recent) // len(recent) if recent else 0

    # Posting frequency (videos per week over last 90 days)
    ninety_vids = [v for v in all_videos if v.published_at and v.published_at >= ninety_days_ago]
    weeks = 13  # 90 / 7
    freq = len(ninety_vids) / weeks if weeks > 0 else 0
    posting_frequency = f"{freq:.1f} videos/week"

    # Top 5 videos
    top_videos = [
        {
            "title": v.title,
            "views": v.view_count,
            "published_at": v.published_at.isoformat() if v.published_at else "",
            "url": f"https://youtube.com/watch?v={v.youtube_video_id}",
        }
        for v in all_videos[:5]
    ]

    # Topic breakdown (if clusters assigned)
    topic_map: dict[str, dict] = {}
    for v in all_videos:
        if v.topic_cluster:
            label = v.topic_cluster.label
            if label not in topic_map:
                topic_map[label] = {"topic": label, "video_count": 0, "total_views": 0}
            topic_map[label]["video_count"] += 1
            topic_map[label]["total_views"] += v.view_count

    topic_breakdown = []
    for t in sorted(topic_map.values(), key=lambda x: x["total_views"], reverse=True)[:10]:
        t["avg_views"] = t["total_views"] // t["video_count"] if t["video_count"] else 0
        del t["total_views"]
        topic_breakdown.append(t)

    # Consistency score: how regularly do they post? (0-100)
    if len(ninety_vids) >= 2:
        dates = sorted([v.published_at for v in ninety_vids if v.published_at])
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        avg_gap = sum(gaps) / len(gaps) if gaps else 30
        std_gap = (sum((g - avg_gap) ** 2 for g in gaps) / len(gaps)) ** 0.5 if gaps else 30
        consistency = max(0, min(100, 100 - std_gap * 5))
    else:
        consistency = 0

    # Growth signal
    if avg_views_30d > avg_views * 1.3:
        growth = "accelerating"
    elif avg_views_30d < avg_views * 0.7:
        growth = "declining"
    else:
        growth = "steady"

    return ChannelReport(
        channel_title=channel.title,
        handle=channel.handle or "",
        subscriber_count=channel.subscriber_count,
        total_videos_analyzed=len(all_videos),
        avg_views_per_video=avg_views,
        avg_views_last_30d=avg_views_30d,
        posting_frequency=posting_frequency,
        top_videos=top_videos,
        topic_breakdown=topic_breakdown,
        consistency_score=round(consistency, 1),
        growth_signal=growth,
        generated_at=now.isoformat(),
    )
