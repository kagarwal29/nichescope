"""Channel ingestion — pull videos for a channel into the database."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nichescope.models import Channel, Video
from nichescope.services.youtube_api import youtube_api

logger = logging.getLogger(__name__)


async def ingest_channel(session: AsyncSession, youtube_channel_id: str) -> Channel:
    """Fetch channel metadata + recent uploads, upsert into DB. Returns Channel."""

    stmt = select(Channel).where(Channel.youtube_channel_id == youtube_channel_id)
    channel = (await session.execute(stmt)).scalar_one_or_none()

    meta = youtube_api.get_channel_by_id(youtube_channel_id)
    if not meta:
        raise ValueError(f"Channel not found: {youtube_channel_id}")

    if channel is None:
        channel = Channel(**meta)
        session.add(channel)
        await session.flush()
        logger.info("Created channel: %s (%s)", channel.title, channel.youtube_channel_id)
    else:
        for key in ("title", "handle", "subscriber_count", "video_count", "thumbnail_url", "uploads_playlist_id"):
            setattr(channel, key, meta[key])

    if not channel.uploads_playlist_id:
        logger.warning("No uploads playlist for channel %s", channel.youtube_channel_id)
        return channel

    # Limit to 50 videos for fast initial ingestion
    video_data_list = youtube_api.get_uploads(channel.uploads_playlist_id, max_results=50)
    logger.info("Fetched %d videos from YouTube for channel %s", len(video_data_list), channel.title)

    existing_ids_stmt = select(Video.youtube_video_id).where(Video.channel_id == channel.id)
    existing_ids = {row[0] for row in (await session.execute(existing_ids_stmt)).all()}

    new_count = 0
    for vdata in video_data_list:
        if vdata["youtube_video_id"] in existing_ids:
            video_stmt = select(Video).where(Video.youtube_video_id == vdata["youtube_video_id"])
            video = (await session.execute(video_stmt)).scalar_one_or_none()
            if video:
                video.view_count = vdata["view_count"]
                video.like_count = vdata["like_count"]
                video.comment_count = vdata["comment_count"]
                video.last_stats_update = datetime.now(timezone.utc)
                video.views_per_day = video.compute_views_per_day()
        else:
            video = Video(channel_id=channel.id, **vdata)
            video.views_per_day = video.compute_views_per_day()
            session.add(video)
            new_count += 1

    channel.last_full_sync = datetime.now(timezone.utc)
    await session.flush()   # Let caller control the commit

    logger.info("Channel %s: %d new videos stored", channel.title, new_count)
    return channel


async def ingest_channel_by_handle(session: AsyncSession, handle: str) -> Channel:
    """Look up channel by @handle, then ingest."""
    meta = youtube_api.get_channel_by_handle(handle)
    if not meta:
        raise ValueError(f"Channel not found for handle: @{handle}")
    return await ingest_channel(session, meta["youtube_channel_id"])
