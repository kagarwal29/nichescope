"""Anomaly detection job — detects viral videos and flops."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from telegram import Bot

from nichescope.config import settings
from nichescope.models import Channel, Niche, User, Video, async_session

logger = logging.getLogger(__name__)


async def detect_anomalies():
    """Hourly: check user's own videos for performance anomalies (viral/flop)."""
    if not settings.telegram_bot_token:
        return

    bot = Bot(token=settings.telegram_bot_token)
    now = datetime.now(timezone.utc)

    async with async_session() as session:
        # Get all users with a YouTube channel
        stmt = select(User).where(
            User.youtube_channel_id.isnot(None),
            User.telegram_chat_id.isnot(None),
        )
        result = await session.execute(stmt)
        users = list(result.scalars().all())

    for user in users:
        try:
            async with async_session() as session:
                # Find user's channel
                ch_stmt = select(Channel).where(
                    Channel.youtube_channel_id == user.youtube_channel_id
                )
                ch_result = await session.execute(ch_stmt)
                channel = ch_result.scalar_one_or_none()

                if not channel:
                    continue

                # Baseline views_per_day (last 90 days)
                baseline_stmt = (
                    select(func.avg(Video.views_per_day))
                    .where(Video.channel_id == channel.id)
                    .where(Video.published_at >= now - timedelta(days=90))
                )
                baseline_result = await session.execute(baseline_stmt)
                baseline_vpd = baseline_result.scalar() or 0

                if baseline_vpd == 0:
                    continue

                # Check recent videos (last 7 days)
                recent_stmt = (
                    select(Video)
                    .where(Video.channel_id == channel.id)
                    .where(Video.published_at >= now - timedelta(days=7))
                    .where(Video.views_per_day > 0)
                )
                recent_result = await session.execute(recent_stmt)
                recent_videos = list(recent_result.scalars().all())

                for video in recent_videos:
                    ratio = video.views_per_day / baseline_vpd

                    if ratio > 3.0:
                        await bot.send_message(
                            chat_id=user.telegram_chat_id,
                            text=(
                                f"🚀 *VIRAL ALERT!*\n\n"
                                f"Your video \"{video.title}\" is performing "
                                f"*{ratio:.1f}x* above your baseline!\n\n"
                                f"Views: {video.view_count:,} "
                                f"({video.views_per_day:.0f}/day vs {baseline_vpd:.0f} baseline)\n\n"
                                f"[Watch](https://youtube.com/watch?v={video.youtube_video_id})"
                            ),
                            parse_mode="Markdown",
                            disable_web_page_preview=True,
                        )
                        logger.info(
                            "Viral alert for user %d: %s (%.1fx)",
                            user.id, video.title, ratio,
                        )

                    elif ratio < 0.3:
                        await bot.send_message(
                            chat_id=user.telegram_chat_id,
                            text=(
                                f"📉 *Underperformance Alert*\n\n"
                                f"Your video \"{video.title}\" is at "
                                f"*{ratio:.1f}x* your baseline.\n\n"
                                f"Views: {video.view_count:,} "
                                f"({video.views_per_day:.0f}/day vs {baseline_vpd:.0f} baseline)\n\n"
                                f"Consider: different thumbnail? Title tweak?"
                            ),
                            parse_mode="Markdown",
                        )

        except Exception:
            logger.exception("Anomaly detection failed for user %d", user.id)
