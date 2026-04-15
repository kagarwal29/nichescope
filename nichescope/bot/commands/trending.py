"""/trending — Trending topics in the user's niche."""
from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from nichescope.bot.formatters import format_number, trend_emoji
from nichescope.bot.pipeline import ensure_fresh_analysis
from nichescope.models import Niche, TopicCluster, User, async_session

async def trending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with async_session() as session:
        user = (await session.execute(select(User).where(User.telegram_chat_id == chat_id))).scalar_one_or_none()
        if not user:
            await update.message.reply_text("Not registered. Run /start first!"); return
        niche = (await session.execute(select(Niche).where(Niche.user_id == user.id).limit(1))).scalar_one_or_none()
        if not niche:
            await update.message.reply_text("No niche configured. Run /start."); return
        user_id, niche_id, niche_name = user.id, niche.id, niche.name
    if not await ensure_fresh_analysis(update, user_id, niche_id, niche_name):
        return
    async with async_session() as session:
        topics = list((await session.execute(select(TopicCluster).where(TopicCluster.niche_id == niche_id).order_by(TopicCluster.avg_views_30d.desc()).limit(10))).scalars().all())
    if not topics:
        await update.message.reply_text("No topic data found. Try /analyze to re-run."); return
    lines = [f"🔥 *Trending Topics — {niche_name}*\n"]
    for i, t in enumerate(topics, 1):
        emoji = trend_emoji(t.trend_direction)
        lines.append(f"*{i}. {t.label}* {emoji}\n   Avg views (30d): {format_number(int(t.avg_views_30d))} | Videos: {t.video_count}")
    lines.append("\n📈 = trending up | ➡️ = stable | 📉 = declining")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
