"""Seasonal Content Calendar — predict when topics will spike based on historical patterns.

NO COMPETITOR DOES THIS.

The insight: Certain topics have predictable seasonal patterns.
"Grilling" spikes every May-July. "Meal prep" spikes in January.
"Halloween costumes" spikes in October. If you can predict WHEN a topic
will surge, you can publish 1-2 weeks before the spike and ride the wave.

This service:
1. Analyzes view velocity of each topic cluster by month (last 12+ months)
2. Detects seasonal patterns (monthly view index vs annual average)
3. Generates a forward-looking content calendar with optimal publish windows
4. Alerts when a seasonal opportunity is approaching (2 weeks before historical spike)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nichescope.models import TopicCluster, Video

logger = logging.getLogger(__name__)


@dataclass
class SeasonalPattern:
    """Detected seasonal pattern for a topic."""

    topic_label: str
    topic_id: int
    # Monthly index: month (1-12) → relative performance (1.0 = average)
    # e.g., {1: 1.8, 7: 0.4} means Jan is 80% above avg, July is 60% below
    monthly_index: dict[int, float]
    peak_month: int
    peak_multiplier: float  # how much above baseline the peak is
    trough_month: int
    is_seasonal: bool  # True if max/min spread > 1.5x
    confidence: float  # 0-1, based on data density


@dataclass
class CalendarEntry:
    """A recommended content calendar item."""

    topic_label: str
    recommended_publish_window: str  # "Jan 15 - Jan 30"
    peak_month: str  # "February"
    peak_multiplier: float
    reason: str
    urgency: str  # "now" | "upcoming" | "plan_ahead"


MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


async def analyze_seasonal_patterns(
    session: AsyncSession,
    niche_id: int,
) -> list[SeasonalPattern]:
    """Analyze all topic clusters in a niche for seasonal patterns."""

    # Get all topic clusters
    clusters_stmt = select(TopicCluster).where(TopicCluster.niche_id == niche_id)
    clusters_result = await session.execute(clusters_stmt)
    clusters = list(clusters_result.scalars().all())

    patterns: list[SeasonalPattern] = []

    for cluster in clusters:
        # Get all videos in this cluster
        videos_stmt = (
            select(Video)
            .where(Video.topic_cluster_id == cluster.id)
            .where(Video.published_at.isnot(None))
            .where(Video.view_count > 0)
        )
        videos_result = await session.execute(videos_stmt)
        videos = list(videos_result.scalars().all())

        pattern = _compute_seasonal_pattern(cluster, videos)
        if pattern:
            patterns.append(pattern)

    # Sort: most seasonal first
    patterns.sort(key=lambda p: p.peak_multiplier, reverse=True)
    return patterns


def _compute_seasonal_pattern(
    cluster: TopicCluster,
    videos: list[Video],
) -> SeasonalPattern | None:
    """Compute monthly performance index for a topic cluster."""
    if len(videos) < 6:  # need enough data across months
        return None

    # Group views by publication month
    monthly_views: dict[int, list[int]] = defaultdict(list)
    for v in videos:
        if v.published_at:
            month = v.published_at.month
            monthly_views[month].append(v.view_count)

    if len(monthly_views) < 3:  # need data in at least 3 months
        return None

    # Compute monthly averages
    monthly_avg: dict[int, float] = {}
    for month, views in monthly_views.items():
        monthly_avg[month] = sum(views) / len(views)

    # Compute overall average
    all_views = [v for views in monthly_views.values() for v in views]
    overall_avg = sum(all_views) / len(all_views) if all_views else 1

    # Compute monthly index (1.0 = average)
    monthly_index: dict[int, float] = {}
    for month in range(1, 13):
        if month in monthly_avg:
            monthly_index[month] = round(monthly_avg[month] / overall_avg, 2)
        else:
            monthly_index[month] = 1.0  # assume average if no data

    # Find peak and trough
    peak_month = max(monthly_index, key=monthly_index.get)
    trough_month = min(monthly_index, key=monthly_index.get)

    peak_val = monthly_index[peak_month]
    trough_val = monthly_index[trough_month]

    # Is it seasonal? (peak must be at least 1.5x above trough)
    is_seasonal = (peak_val / trough_val) >= 1.5 if trough_val > 0 else False

    # Confidence based on data density
    months_with_data = sum(1 for m in monthly_views if len(monthly_views[m]) >= 2)
    confidence = round(min(1.0, months_with_data / 8), 2)

    return SeasonalPattern(
        topic_label=cluster.label,
        topic_id=cluster.id,
        monthly_index=monthly_index,
        peak_month=peak_month,
        peak_multiplier=round(peak_val, 2),
        trough_month=trough_month,
        is_seasonal=is_seasonal,
        confidence=confidence,
    )


async def generate_content_calendar(
    session: AsyncSession,
    niche_id: int,
    lookahead_weeks: int = 8,
) -> list[CalendarEntry]:
    """Generate a forward-looking content calendar based on seasonal patterns.

    Recommends publishing 2 weeks before each topic's historical peak.
    """
    patterns = await analyze_seasonal_patterns(session, niche_id)
    seasonal = [p for p in patterns if p.is_seasonal and p.confidence >= 0.3]

    if not seasonal:
        return []

    now = datetime.now(timezone.utc)
    current_month = now.month
    entries: list[CalendarEntry] = []

    for pattern in seasonal:
        # When should they publish? 2 weeks before peak month
        peak = pattern.peak_month
        publish_month = peak - 1 if peak > 1 else 12

        # How many months from now is the publish window?
        months_away = (publish_month - current_month) % 12

        if months_away > (lookahead_weeks / 4):
            urgency = "plan_ahead"
        elif months_away <= 1:
            urgency = "now"
        else:
            urgency = "upcoming"

        # Only include if within lookahead window
        if months_away <= (lookahead_weeks / 4) + 1:
            publish_start = f"{MONTH_NAMES[publish_month]} 15"
            publish_end = f"{MONTH_NAMES[peak]} 1"

            entries.append(
                CalendarEntry(
                    topic_label=pattern.topic_label,
                    recommended_publish_window=f"{publish_start} — {publish_end}",
                    peak_month=MONTH_NAMES[peak],
                    peak_multiplier=pattern.peak_multiplier,
                    reason=(
                        f"'{pattern.topic_label}' historically peaks in {MONTH_NAMES[peak]} "
                        f"at {pattern.peak_multiplier:.1f}x baseline views. "
                        f"Publish 2 weeks early to ride the wave."
                    ),
                    urgency=urgency,
                )
            )

    # Sort: urgent first, then by peak multiplier
    urgency_order = {"now": 0, "upcoming": 1, "plan_ahead": 2}
    entries.sort(key=lambda e: (urgency_order.get(e.urgency, 9), -e.peak_multiplier))
    return entries
