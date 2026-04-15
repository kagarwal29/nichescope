"""/formats — Video format intelligence."""
from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from nichescope.bot.formatters import format_format_insights
from nichescope.bot.pipeline import ensure_fresh_analysis
from nichescope.models import Niche, User, async_session
from nichescope.services.format_intel import analyze_format_performance

async def formats(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        insights = await analyze_format_performance(session, niche_id)
    message = format_format_insights(niche_name, insights[:8])
    await update.message.reply_text(message, parse_mode="Markdown", disable_web_page_preview=True)
