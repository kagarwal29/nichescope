"""Comment Demand Mining — extract explicit audience requests from competitor video comments.

NO COMPETITOR DOES THIS.

The insight: YouTube comments contain literal demand signals. Viewers write
"can you make a video about X?", "do a tutorial on Y!", "please cover Z".
These are higher-signal than any keyword tool because they're UNPROMPTED requests
from real viewers in your exact niche.

This service:
1. Pulls comments from top-performing competitor videos
2. Extracts "request" patterns using regex + lightweight NLP
3. Clusters requests into demand topics
4. Cross-references with your gap scores to surface validated opportunities
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nichescope.models import Channel, Video
from nichescope.models.channel import niche_channels
from nichescope.services.youtube_api import youtube_api

logger = logging.getLogger(__name__)

# Patterns that signal a viewer request
REQUEST_PATTERNS = [
    re.compile(r"(?:can|could) you (?:make|do|create|film|shoot|try|cover|review)\b(.{5,80})", re.I),
    re.compile(r"(?:please|pls) (?:make|do|create|cover|try|review)\b(.{5,80})", re.I),
    re.compile(r"(?:you should|you need to) (?:make|do|try|cover|review)\b(.{5,80})", re.I),
    re.compile(r"(?:do|make) a (?:video|tutorial|guide|review) (?:on|about|for)\b(.{5,80})", re.I),
    re.compile(r"(?:would love|i(?:'d| would) love) (?:to see|a video|a tutorial)\b(.{5,80})", re.I),
    re.compile(r"(?:next video|next time).{0,10}(?:try|make|do|cover|about)\b(.{5,80})", re.I),
    re.compile(r"(?:video idea|content idea|suggestion)[:\s]+(.{5,80})", re.I),
    re.compile(r"(?:react to|reaction to|thoughts on)\b(.{5,80})", re.I),
]

# Noise filter — ignore requests that match these
NOISE_PATTERNS = [
    re.compile(r"(?:subscribe|like|share|comment|notification)", re.I),
    re.compile(r"(?:first|pin me|shout ?out)", re.I),
]


@dataclass
class DemandSignal:
    """A single viewer request extracted from a comment."""

    raw_text: str
    extracted_topic: str
    video_title: str
    video_id: str
    channel_title: str
    like_count: int  # comment likes = strength signal


@dataclass
class DemandCluster:
    """Aggregated demand for a topic from multiple comments."""

    topic: str
    request_count: int
    total_likes: int  # sum of comment likes across all requests
    example_requests: list[str]
    source_channels: list[str]
    strength_score: float  # request_count × avg_likes


async def mine_comment_demands(
    session: AsyncSession,
    niche_id: int,
    max_videos: int = 20,
    max_comments_per_video: int = 100,
) -> list[DemandCluster]:
    """Mine viewer requests from comments on top competitor videos.

    Strategy:
    1. Pick the top N performing videos from each competitor
    2. Pull their comments via YouTube API
    3. Regex-extract request patterns
    4. Cluster by topic similarity
    5. Rank by (request_count × avg_likes)

    API quota: ~1 unit per 20 comments (commentThreads.list)
    For 20 videos × 100 comments = ~100 units. Budget accordingly.
    """

    # Get top-performing competitor videos in this niche
    stmt = (
        select(Video, Channel.title)
        .join(Channel, Video.channel_id == Channel.id)
        .join(niche_channels, niche_channels.c.channel_id == Channel.id)
        .where(niche_channels.c.niche_id == niche_id)
        .order_by(Video.view_count.desc())
        .limit(max_videos)
    )
    result = await session.execute(stmt)
    top_videos = result.all()

    if not top_videos:
        logger.warning("No videos found for niche %d", niche_id)
        return []

    # Extract demand signals from comments
    all_signals: list[DemandSignal] = []

    for video, channel_title in top_videos:
        try:
            comments = _fetch_comments(video.youtube_video_id, max_comments_per_video)
            for comment_text, like_count in comments:
                signals = _extract_requests(comment_text, video, channel_title, like_count)
                all_signals.extend(signals)
        except Exception:
            logger.warning("Failed to fetch comments for %s", video.youtube_video_id)
            continue

    logger.info("Extracted %d demand signals from %d videos", len(all_signals), len(top_videos))

    # Cluster by topic
    return _cluster_demands(all_signals)


def _fetch_comments(video_id: str, max_results: int = 100) -> list[tuple[str, int]]:
    """Fetch top comments for a video. Returns [(text, like_count)]."""
    comments: list[tuple[str, int]] = []
    page_token = None

    while len(comments) < max_results:
        youtube_api._charge("commentThreads.list")
        resp = (
            youtube_api._service.commentThreads()
            .list(
                part="snippet",
                videoId=video_id,
                maxResults=min(100, max_results - len(comments)),
                order="relevance",
                pageToken=page_token,
            )
            .execute()
        )

        for item in resp.get("items", []):
            snippet = item["snippet"]["topLevelComment"]["snippet"]
            text = snippet.get("textDisplay", "")
            likes = snippet.get("likeCount", 0)
            comments.append((text, likes))

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return comments


def _extract_requests(
    comment_text: str,
    video: Video,
    channel_title: str,
    like_count: int,
) -> list[DemandSignal]:
    """Extract demand signals from a single comment."""
    # Skip noise
    for noise in NOISE_PATTERNS:
        if noise.search(comment_text):
            return []

    signals: list[DemandSignal] = []
    for pattern in REQUEST_PATTERNS:
        match = pattern.search(comment_text)
        if match:
            topic = match.group(1).strip().rstrip("?.!,")
            # Clean up
            topic = re.sub(r"<[^>]+>", "", topic)  # strip HTML tags
            topic = topic.strip()

            if len(topic) < 5 or len(topic) > 80:
                continue

            signals.append(
                DemandSignal(
                    raw_text=comment_text[:200],
                    extracted_topic=topic.lower(),
                    video_title=video.title,
                    video_id=video.youtube_video_id,
                    channel_title=channel_title,
                    like_count=like_count,
                )
            )
            break  # one match per comment

    return signals


def _cluster_demands(signals: list[DemandSignal]) -> list[DemandCluster]:
    """Cluster demand signals by topic similarity using keyword overlap."""
    if not signals:
        return []

    # Simple keyword-based grouping (v1 — upgrade to embeddings in v2)
    # Normalize topics to keyword bags
    topic_bags: dict[str, list[DemandSignal]] = {}

    for signal in signals:
        # Use first 3 significant words as cluster key
        words = [w for w in signal.extracted_topic.split() if len(w) > 3][:3]
        key = " ".join(sorted(words)) if words else signal.extracted_topic[:20]

        if key not in topic_bags:
            topic_bags[key] = []
        topic_bags[key].append(signal)

    # Build clusters
    clusters: list[DemandCluster] = []
    for key, group in topic_bags.items():
        if len(group) < 1:
            continue

        total_likes = sum(s.like_count for s in group)
        avg_likes = total_likes / len(group) if group else 0

        clusters.append(
            DemandCluster(
                topic=group[0].extracted_topic,  # use first signal's topic as label
                request_count=len(group),
                total_likes=total_likes,
                example_requests=list({s.raw_text[:100] for s in group})[:3],
                source_channels=list({s.channel_title for s in group}),
                strength_score=round(len(group) * (1 + avg_likes), 1),
            )
        )

    # Sort by strength
    clusters.sort(key=lambda c: c.strength_score, reverse=True)
    return clusters
