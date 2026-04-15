"""RSS polling job — runs every 15 minutes, zero API quota."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from nichescope.models import Channel, Video, async_session
from nichescope.services.rss_poller import poll_channel_rss

logger = logging.getLogger(__name__)


async def poll_all_rss():
    """Poll RSS feeds for all tracked channels. Inserts new video stubs."""
    async with async_session() as session:
        stmt = select(Channel)
        result = await session.execute(stmt)
        channels = list(result.scalars().all())

    total_new = 0
    executor = ThreadPoolExecutor(max_workers=3)
    
    for channel in channels:
        try:
            # Run sync function in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            new_videos = await loop.run_in_executor(
                executor, poll_channel_rss, channel.youtube_channel_id
            )

            async with async_session() as session:
                # Check which video IDs are already in DB
                existing_stmt = select(Video.youtube_video_id).where(
                    Video.channel_id == channel.id
                )
                existing_result = await session.execute(existing_stmt)
                existing_ids = {row[0] for row in existing_result.all()}

                inserted = 0
                for vdata in new_videos:
                    if vdata["youtube_video_id"] not in existing_ids:
                        video = Video(
                            youtube_video_id=vdata["youtube_video_id"],
                            channel_id=channel.id,
                            title=vdata["title"],
                            description=vdata.get("description", ""),
                            published_at=vdata["published_at"],
                            thumbnail_url=vdata.get("thumbnail_url"),
                            tags="[]",
                        )
                        session.add(video)
                        inserted += 1

                if inserted:
                    channel.last_rss_poll = datetime.now(timezone.utc)
                    await session.commit()
                    total_new += inserted
                    logger.info("RSS: %d new videos from %s", inserted, channel.title)

        except Exception:
            logger.exception("RSS poll failed for channel %s", channel.youtube_channel_id)

    executor.shutdown(wait=False)
    logger.info("RSS poll complete: %d new videos across %d channels", total_new, len(channels))
