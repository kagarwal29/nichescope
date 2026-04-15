"""/rival — Competitor deep-dive."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from nichescope.bot.formatters import format_competitor_report
from nichescope.models import Channel, async_session
from nichescope.services.competitor_radar import analyze_competitor
from nichescope.services.youtube_api import youtube_api
from sqlalchemy import select


async def rival(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/rival @handle — deep-dive on a specific competitor."""
    if not context.args:
        await update.message.reply_text("Usage: /rival @channelhandle")
        return

    handle = context.args[0].lstrip("@")
    await update.message.reply_text(f"🔍 Analyzing @{handle}...")

    async with async_session() as session:
        # Find channel in DB
        stmt = select(Channel).where(Channel.handle == f"@{handle}")
        result = await session.execute(stmt)
        channel = result.scalar_one_or_none()

        if not channel:
            # Try without @
            stmt = select(Channel).where(Channel.handle == handle)
            result = await session.execute(stmt)
            channel = result.scalar_one_or_none()

        if not channel:
            await update.message.reply_text(
                f"Channel @{handle} not found in our database.\n"
                "Add them as a competitor first via /start or the API."
            )
            return

        insight = await analyze_competitor(session, channel.id)

    report = format_competitor_report({
        "channel_title": insight.channel_title,
        "handle": insight.handle,
        "subscriber_count": insight.subscriber_count,
        "recent_videos": insight.recent_videos,
        "total_views_7d": insight.total_views_7d,
        "videos_posted_7d": insight.videos_posted_7d,
        "avg_views_per_video": insight.avg_views_per_video,
        "top_topic": insight.top_topic,
    })

    await update.message.reply_text(report, parse_mode="Markdown", disable_web_page_preview=True)
