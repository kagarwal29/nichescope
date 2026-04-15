"""RSS feed poller — zero YouTube API quota consumption."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import feedparser

logger = logging.getLogger(__name__)


def poll_channel_rss(youtube_channel_id: str) -> list[dict]:
    """Poll a YouTube channel's RSS feed. Returns list of new video stubs.

    Each stub has: youtube_video_id, title, published_at, description (partial).
    These are lightweight — view counts require a separate API enrichment call.

    Costs ZERO YouTube API quota.
    """
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={youtube_channel_id}"
    feed = feedparser.parse(url)

    if feed.bozo and not feed.entries:
        logger.warning("RSS parse error for %s: %s", youtube_channel_id, feed.bozo_exception)
        return []

    videos: list[dict] = []
    for entry in feed.entries:
        video_id = entry.get("yt_videoid", "")
        if not video_id:
            # Fallback: extract from link
            link = entry.get("link", "")
            if "v=" in link:
                video_id = link.split("v=")[-1].split("&")[0]
            if not video_id:
                continue

        published = entry.get("published_parsed")
        if published:
            pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
        else:
            pub_dt = datetime.now(timezone.utc)

        videos.append(
            {
                "youtube_video_id": video_id,
                "title": entry.get("title", ""),
                "published_at": pub_dt,
                "description": entry.get("summary", "")[:500],
                "thumbnail_url": _extract_thumbnail(entry),
            }
        )

    logger.info("RSS poll for %s: found %d entries", youtube_channel_id, len(videos))
    return videos


def _extract_thumbnail(entry: dict) -> str | None:
    """Extract thumbnail URL from RSS entry media groups."""
    media_group = entry.get("media_group", [])
    if media_group:
        for item in media_group:
            thumbnails = item.get("media_thumbnail", [])
            if thumbnails:
                return thumbnails[0].get("url")
    # Fallback: construct from video ID
    video_id = entry.get("yt_videoid", "")
    if video_id:
        return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"
    return None
