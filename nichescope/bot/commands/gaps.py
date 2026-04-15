"""/gaps — On-demand content gap analysis."""
from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from nichescope.bot.formatters import format_gap_insight
from nichescope.bot.pipeline import ensure_fresh_analysis
from nichescope.models import Niche, User, async_session
from nichescope.services.gap_analyzer import get_top_gaps

async def gaps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with async_session() as session:
        user = (await session.execute(select(User).where(User.telegram_chat_id == chat_id))).scalar_one_or_none()
        if not user:
            await update.message.reply_text("Not registered. Run /start first!"); return
        niche = (await session.execute(select(Niche).where(Niche.user_id == user.id).limit(1))).scalar_one_or_none()
        if not niche:
            await update.message.reply_text("No niche configured. Run /start to set up."); return
        user_id, niche_id, niche_name = user.id, niche.id, niche.name
    if not await ensure_fresh_analysis(update, user_id, niche_id, niche_name):
        return
    async with async_session() as session:
        insights = await get_top_gaps(session, user_id, niche_id, limit=5)
    if not insights:
        await update.message.reply_text("⚠️ No gaps found yet. Try adding more competitors, then /analyze."); return
    lines = [f"📊 *Content Gaps — {niche_name}*\n"]
    for i, gap in enumerate(insights, 1):
        lines.append(format_gap_insight({"topic": gap.topic_label, "score": gap.score, "avg_views": gap.avg_views, "competitor_videos": gap.competitor_video_count, "your_videos": gap.your_video_count, "trend": gap.trend, "example_videos": gap.top_competitor_video_titles}, i))
        lines.append("")
    lines.append("_Higher score = bigger opportunity. Run /brief for daily summary._")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
