"""Collaboration Graph — map creator collaborations and find untapped opportunities.

NO COMPETITOR DOES THIS.

The insight: Collabs are the #1 organic growth lever on YouTube.
But creators pick collab partners randomly. This service:
1. Detects existing collaborations (title mentions, description @tags, comments)
2. Maps a collaboration graph across the niche
3. Identifies OPTIMAL collab partners — creators with high audience
   relevance but LOW audience overlap with you
4. Ranks opportunities by potential reach × relevance

The goal: "You should collab with @CreatorX because they cover similar topics
but their audience barely overlaps with yours — maximum new viewer exposure."
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nichescope.models import Channel, Video
from nichescope.models.channel import niche_channels

logger = logging.getLogger(__name__)

# Patterns that indicate a collab
COLLAB_PATTERNS = [
    re.compile(r"(?:feat\.?|featuring|ft\.?|with|collab(?:oration)? with|×|x )\s*@?(\w[\w\s]{2,30})", re.I),
    re.compile(r"@(\w{3,30})\s", re.I),  # @mention in title/description
]


@dataclass
class CollabEdge:
    """A detected collaboration between two creators."""

    channel_a: str
    channel_b: str
    video_title: str
    video_id: str
    detection_method: str  # "title_mention" | "description_tag" | "video_collab"


@dataclass
class CollabOpportunity:
    """A recommended collaboration partner."""

    channel_title: str
    handle: str
    subscriber_count: int
    topic_overlap_score: float  # 0-1: how similar their topics are
    audience_overlap_estimate: str  # "low" | "medium" | "high"
    existing_collabs: int  # how many times they've collabed with others
    potential_reach: int  # their subscriber count × (1 - estimated overlap)
    shared_topics: list[str]
    reason: str


async def build_collab_graph(
    session: AsyncSession,
    niche_id: int,
) -> dict[str, list[CollabEdge]]:
    """Build a collaboration graph from video titles and descriptions.

    Returns: dict mapping channel_title → list of collab edges.
    """

    # Get all channels in niche
    channels_stmt = (
        select(Channel)
        .join(niche_channels, niche_channels.c.channel_id == Channel.id)
        .where(niche_channels.c.niche_id == niche_id)
    )
    channels_result = await session.execute(channels_stmt)
    channels = list(channels_result.scalars().all())

    channel_names = {c.title.lower(): c for c in channels}
    channel_handles = {c.handle.lower().lstrip("@"): c for c in channels if c.handle}

    graph: dict[str, list[CollabEdge]] = defaultdict(list)

    for channel in channels:
        # Get all videos
        videos_stmt = select(Video).where(Video.channel_id == channel.id)
        videos_result = await session.execute(videos_stmt)
        videos = list(videos_result.scalars().all())

        for video in videos:
            # Check title for collab mentions
            collab_partner = _detect_collab(
                video.title, video.description, channel_names, channel_handles
            )
            if collab_partner and collab_partner != channel.title:
                edge = CollabEdge(
                    channel_a=channel.title,
                    channel_b=collab_partner,
                    video_title=video.title,
                    video_id=video.youtube_video_id,
                    detection_method="title_mention",
                )
                graph[channel.title].append(edge)
                graph[collab_partner].append(edge)

    logger.info("Built collab graph: %d channels, %d edges", len(graph), sum(len(v) for v in graph.values()))
    return dict(graph)


def _detect_collab(
    title: str,
    description: str,
    channel_names: dict[str, Channel],
    channel_handles: dict[str, Channel],
) -> str | None:
    """Detect if a video is a collaboration by checking title/description."""
    text = f"{title} {description[:500]}"

    for pattern in COLLAB_PATTERNS:
        match = pattern.search(text)
        if match:
            mention = match.group(1).strip().lower()
            # Check if mention matches a known channel
            if mention in channel_names:
                return channel_names[mention].title
            if mention in channel_handles:
                return channel_handles[mention].title

    return None


async def find_collab_opportunities(
    session: AsyncSession,
    niche_id: int,
    user_channel_id: int | None = None,
) -> list[CollabOpportunity]:
    """Find optimal collaboration partners for a creator.

    Optimal = high topic relevance × low audience overlap × high reach.

    Since we can't directly measure audience overlap (YouTube doesn't expose this),
    we estimate it from:
    - Subscriber count ratio (very different sizes = lower overlap)
    - Topic similarity (same topics = higher overlap)
    - Existing collab frequency (frequent collaborators = already high overlap)
    """

    collab_graph = await build_collab_graph(session, niche_id)

    # Get all channels
    channels_stmt = (
        select(Channel)
        .join(niche_channels, niche_channels.c.channel_id == Channel.id)
        .where(niche_channels.c.niche_id == niche_id)
    )
    channels_result = await session.execute(channels_stmt)
    channels = list(channels_result.scalars().all())

    # Get user's channel for comparison
    user_channel = None
    if user_channel_id:
        user_channel = await session.get(Channel, user_channel_id)

    opportunities: list[CollabOpportunity] = []

    for channel in channels:
        if user_channel and channel.id == user_channel.id:
            continue

        # Topic overlap: count shared topic clusters
        channel_topics = set()
        videos_stmt = select(Video.topic_cluster_id).where(
            Video.channel_id == channel.id,
            Video.topic_cluster_id.isnot(None),
        ).distinct()
        topics_result = await session.execute(videos_stmt)
        channel_topics = {row[0] for row in topics_result.all()}

        user_topics = set()
        if user_channel:
            user_topics_stmt = select(Video.topic_cluster_id).where(
                Video.channel_id == user_channel.id,
                Video.topic_cluster_id.isnot(None),
            ).distinct()
            ut_result = await session.execute(user_topics_stmt)
            user_topics = {row[0] for row in ut_result.all()}

        shared = channel_topics & user_topics
        total = channel_topics | user_topics
        topic_overlap = len(shared) / len(total) if total else 0

        # Audience overlap estimate
        if user_channel:
            size_ratio = min(channel.subscriber_count, user_channel.subscriber_count) / max(
                channel.subscriber_count, user_channel.subscriber_count, 1
            )
        else:
            size_ratio = 0.5

        if topic_overlap > 0.7 and size_ratio > 0.5:
            overlap_estimate = "high"
        elif topic_overlap > 0.3:
            overlap_estimate = "medium"
        else:
            overlap_estimate = "low"

        # Existing collabs
        existing = len(collab_graph.get(channel.title, []))

        # Potential reach
        overlap_factor = {"low": 0.9, "medium": 0.6, "high": 0.3}[overlap_estimate]
        potential_reach = int(channel.subscriber_count * overlap_factor)

        # Get shared topic labels
        from nichescope.models import TopicCluster
        shared_labels = []
        if shared:
            labels_stmt = select(TopicCluster.label).where(TopicCluster.id.in_(shared))
            labels_result = await session.execute(labels_stmt)
            shared_labels = [row[0] for row in labels_result.all()]

        reason = (
            f"Audience overlap: {overlap_estimate}. "
            f"Topic relevance: {topic_overlap:.0%}. "
            f"Potential new viewers: ~{potential_reach:,}. "
            f"{'Already active collaborator' if existing > 2 else 'Untapped collab partner'}."
        )

        opportunities.append(
            CollabOpportunity(
                channel_title=channel.title,
                handle=channel.handle or "",
                subscriber_count=channel.subscriber_count,
                topic_overlap_score=round(topic_overlap, 2),
                audience_overlap_estimate=overlap_estimate,
                existing_collabs=existing,
                potential_reach=potential_reach,
                shared_topics=shared_labels[:5],
                reason=reason,
            )
        )

    # Best collabs: high topic overlap + low audience overlap + high reach
    opportunities.sort(key=lambda o: o.potential_reach, reverse=True)
    return opportunities
