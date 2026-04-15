"""Daily briefing push job — sends Telegram briefs at each user's preferred time."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from telegram import Bot

from nichescope.bot.formatters import format_brief
from nichescope.config import settings
from nichescope.models import Niche, User, async_session
from nichescope.services.competitor_radar import detect_competitor_alerts
from nichescope.services.gap_analyzer import get_top_gaps

logger = logging.getLogger(__name__)


async def send_all_briefs():
    """Send daily briefing to all users whose brief_time matches current hour.

    Called hourly. Only sends to users whose brief_time matches UTC hour.
    """
    if not settings.telegram_bot_token:
        logger.warning("No Telegram token — skipping briefs")
        return

    bot = Bot(token=settings.telegram_bot_token)
    now = datetime.now(timezone.utc)
    current_hour = now.strftime("%H:00")

    async with async_session() as session:
        # Find users whose brief time matches this hour
        stmt = (
            select(User)
            .where(User.telegram_chat_id.isnot(None))
            .where(User.brief_time == current_hour)
        )
        result = await session.execute(stmt)
        users = list(result.scalars().all())

    logger.info("Sending briefs to %d users (hour=%s)", len(users), current_hour)

    for user in users:
        try:
            async with async_session() as session:
                # Get user's first niche
                niche_stmt = select(Niche).where(Niche.user_id == user.id).limit(1)
                niche_result = await session.execute(niche_stmt)
                niche = niche_result.scalar_one_or_none()

                if not niche:
                    continue

                # Get gaps
                gaps = await get_top_gaps(session, user.id, niche.id, limit=3)
                gap_dicts = [
                    {
                        "topic": g.topic_label,
                        "score": g.score,
                        "avg_views": g.avg_views,
                        "competitor_videos": g.competitor_video_count,
                        "your_videos": g.your_video_count,
                        "trend": g.trend,
                        "example_videos": g.top_competitor_video_titles,
                    }
                    for g in gaps
                ]

                # Get alerts
                alerts = await detect_competitor_alerts(session, niche.id)
                alert_dicts = [{"message": a.message, "type": a.alert_type} for a in alerts]

            message = format_brief(niche.name, gap_dicts, alert_dicts)
            await bot.send_message(
                chat_id=user.telegram_chat_id,
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            logger.info("Brief sent to user %d", user.id)

        except Exception:
            logger.exception("Failed to send brief to user %d", user.id)
