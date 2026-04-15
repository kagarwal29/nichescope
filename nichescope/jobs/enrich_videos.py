"""Video enrichment job — fetches view counts for recently discovered videos."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from nichescope.models import Video, async_session
from nichescope.services.youtube_api import youtube_api, QuotaExhaustedError

logger = logging.getLogger(__name__)


async def enrich_new_videos():
    """Fetch full metadata for videos that only have RSS stub data (view_count == 0)."""
    async with async_session() as session:
        stmt = (
            select(Video)
            .where(Video.view_count == 0)
            .where(Video.last_stats_update.is_(None))
            .limit(200)  # batch size
        )
        result = await session.execute(stmt)
        videos = list(result.scalars().all())

    if not videos:
        logger.debug("No videos to enrich")
        return

    video_ids = [v.youtube_video_id for v in videos]
    logger.info("Enriching %d videos", len(video_ids))

    try:
        enriched = youtube_api.get_videos_batch(video_ids)
    except QuotaExhaustedError:
        logger.warning("Quota exhausted — skipping enrichment this cycle")
        return

    # Build lookup
    enriched_map = {v["youtube_video_id"]: v for v in enriched}

    async with async_session() as session:
        for video in videos:
            data = enriched_map.get(video.youtube_video_id)
            if data:
                video.view_count = data["view_count"]
                video.like_count = data["like_count"]
                video.comment_count = data["comment_count"]
                video.duration_seconds = data["duration_seconds"]
                video.tags = data["tags"]
                video.description = data["description"]
                video.last_stats_update = datetime.now(timezone.utc)
                video.views_per_day = video.compute_views_per_day()
                session.add(video)

        await session.commit()

    logger.info("Enriched %d / %d videos", len(enriched), len(videos))
