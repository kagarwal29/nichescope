"""Format Intelligence — analyze which video formats perform best per topic.

NO COMPETITOR DOES THIS.

The insight: It's not just WHAT you make, it's HOW you make it.
A "10-minute meal prep guide" gets 3x the views of a "45-minute meal prep vlog"
in the same niche. But nobody quantifies this.

This service:
1. Classifies videos by format (short/medium/long, tutorial/vlog/listicle/review)
2. Cross-references format × topic to find optimal combinations
3. Answers: "For topic X, 12-18 minute tutorials get 2.4x more views than vlogs"
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nichescope.models import TopicCluster, Video

logger = logging.getLogger(__name__)


@dataclass
class FormatProfile:
    """Performance profile for a specific format within a topic."""

    format_type: str  # "tutorial" | "vlog" | "listicle" | "review" | "challenge" | "other"
    duration_bucket: str  # "short (<5m)" | "medium (5-15m)" | "long (15-30m)" | "extra_long (30m+)"
    video_count: int
    avg_views: int
    avg_likes: int
    avg_engagement_rate: float  # likes / views
    performance_vs_baseline: float  # multiplier vs topic average


@dataclass
class FormatInsight:
    """Actionable format recommendation for a topic."""

    topic_label: str
    best_format: str
    best_duration: str
    best_avg_views: int
    worst_format: str
    worst_avg_views: int
    multiplier: float  # best / worst
    recommendation: str
    profiles: list[FormatProfile]


# Format classification patterns
FORMAT_CLASSIFIERS = {
    "tutorial": re.compile(r"(?:how to|tutorial|guide|learn|step by step|beginner|basics)", re.I),
    "listicle": re.compile(r"(?:\d+ (?:best|top|ways|tips|things|mistakes|reasons|hacks))", re.I),
    "review": re.compile(r"(?:review|unboxing|first look|hands on|worth it|honest)", re.I),
    "challenge": re.compile(r"(?:challenge|vs\.?|versus|battle|competition|taste test)", re.I),
    "vlog": re.compile(r"(?:vlog|day in|what i|my morning|routine|week in)", re.I),
    "reaction": re.compile(r"(?:react|reaction|reacting|watching|responding)", re.I),
}

DURATION_BUCKETS = [
    ("short (<5m)", 0, 300),
    ("medium (5-15m)", 300, 900),
    ("long (15-30m)", 900, 1800),
    ("extra_long (30m+)", 1800, 999999),
]


def classify_format(title: str, description: str = "") -> str:
    """Classify a video's format from its title."""
    text = f"{title} {description[:200]}"
    for fmt, pattern in FORMAT_CLASSIFIERS.items():
        if pattern.search(text):
            return fmt
    return "other"


def classify_duration(seconds: int) -> str:
    """Classify video duration into a bucket."""
    for label, low, high in DURATION_BUCKETS:
        if low <= seconds < high:
            return label
    return "extra_long (30m+)"


async def analyze_format_performance(
    session: AsyncSession,
    niche_id: int,
) -> list[FormatInsight]:
    """Analyze which video formats perform best for each topic in a niche."""

    # Get all topic clusters
    clusters_stmt = select(TopicCluster).where(TopicCluster.niche_id == niche_id)
    clusters_result = await session.execute(clusters_stmt)
    clusters = list(clusters_result.scalars().all())

    insights: list[FormatInsight] = []

    for cluster in clusters:
        videos_stmt = (
            select(Video)
            .where(Video.topic_cluster_id == cluster.id)
            .where(Video.view_count > 0)
        )
        videos_result = await session.execute(videos_stmt)
        videos = list(videos_result.scalars().all())

        if len(videos) < 5:
            continue

        insight = _analyze_topic_formats(cluster, videos)
        if insight:
            insights.append(insight)

    # Sort by multiplier (biggest format gap = most actionable)
    insights.sort(key=lambda i: i.multiplier, reverse=True)
    return insights


def _analyze_topic_formats(cluster: TopicCluster, videos: list[Video]) -> FormatInsight | None:
    """Analyze format performance within a single topic cluster."""

    # Classify each video
    format_groups: dict[str, list[Video]] = defaultdict(list)
    duration_groups: dict[str, list[Video]] = defaultdict(list)

    for v in videos:
        fmt = classify_format(v.title, v.description)
        dur = classify_duration(v.duration_seconds)
        format_groups[fmt].append(v)
        duration_groups[dur].append(v)

    # Compute topic baseline
    baseline_views = sum(v.view_count for v in videos) / len(videos)

    # Build format profiles
    profiles: list[FormatProfile] = []

    for fmt, fmt_videos in format_groups.items():
        if len(fmt_videos) < 2:
            continue

        avg_views = sum(v.view_count for v in fmt_videos) // len(fmt_videos)
        avg_likes = sum(v.like_count for v in fmt_videos) // len(fmt_videos)
        total_views = sum(v.view_count for v in fmt_videos)
        total_likes = sum(v.like_count for v in fmt_videos)
        engagement = total_likes / total_views if total_views else 0

        # Find dominant duration bucket for this format
        dur_counts: dict[str, int] = defaultdict(int)
        for v in fmt_videos:
            dur_counts[classify_duration(v.duration_seconds)] += 1
        dominant_duration = max(dur_counts, key=dur_counts.get) if dur_counts else "medium (5-15m)"

        profiles.append(
            FormatProfile(
                format_type=fmt,
                duration_bucket=dominant_duration,
                video_count=len(fmt_videos),
                avg_views=avg_views,
                avg_likes=avg_likes,
                avg_engagement_rate=round(engagement, 4),
                performance_vs_baseline=round(avg_views / baseline_views, 2) if baseline_views else 1.0,
            )
        )

    if len(profiles) < 2:
        return None

    profiles.sort(key=lambda p: p.avg_views, reverse=True)
    best = profiles[0]
    worst = profiles[-1]
    multiplier = round(best.avg_views / worst.avg_views, 1) if worst.avg_views else 1.0

    if multiplier < 1.3:
        return None  # Not enough format difference to be actionable

    recommendation = (
        f"For '{cluster.label}', {best.format_type}s ({best.duration_bucket}) "
        f"get {multiplier}x more views than {worst.format_type}s. "
        f"Best format averages {best.avg_views:,} views vs {worst.avg_views:,}."
    )

    return FormatInsight(
        topic_label=cluster.label,
        best_format=best.format_type,
        best_duration=best.duration_bucket,
        best_avg_views=best.avg_views,
        worst_format=worst.format_type,
        worst_avg_views=worst.avg_views,
        multiplier=multiplier,
        recommendation=recommendation,
        profiles=profiles,
    )
