"""/brief — Daily briefing command."""
from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from nichescope.bot.formatters import format_brief
from nichescope.bot.pipeline import ensure_fresh_analysis
from nichescope.models import Niche, User, async_session
from nichescope.services.gap_analyzer import get_top_gaps
from nichescope.services.competitor_radar import detect_competitor_alerts

async def brief(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with async_session() as session:
        user = (await session.execute(select(User).where(User.telegram_chat_id == chat_id))).scalar_one_or_none()
        if not user:
            await update.message.reply_text("You're not registered yet. Run /start first!"); return
        niche = (await session.execute(select(Niche).where(Niche.user_id == user.id).limit(1))).scalar_one_or_none()
        if not niche:
            await update.message.reply_text("No niche configured. Run /start to set up."); return
        user_id, niche_id, niche_name = user.id, niche.id, niche.name
    if not await ensure_fresh_analysis(update, user_id, niche_id, niche_name):
        return
    async with async_session() as session:
        gaps = await get_top_gaps(session, user_id, niche_id, limit=3)
        gap_dicts = [{"topic": g.topic_label, "score": g.score, "avg_views": g.avg_views, "competitor_videos": g.competitor_video_count, "your_videos": g.your_video_count, "trend": g.trend, "example_videos": g.top_competitor_video_titles} for g in gaps]
        alerts = await detect_competitor_alerts(session, niche_id)
        alert_dicts = [{"message": a.message, "type": a.alert_type} for a in alerts]
    message = format_brief(niche_name, gap_dicts, alert_dicts)
    await update.message.reply_text(message, parse_mode="Markdown", disable_web_page_preview=True)
