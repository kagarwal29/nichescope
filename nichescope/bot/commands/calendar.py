"""/calendar — Seasonal content calendar."""
from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from nichescope.bot.formatters import format_calendar
from nichescope.bot.pipeline import ensure_fresh_analysis
from nichescope.models import Niche, User, async_session
from nichescope.services.seasonal_calendar import generate_content_calendar

async def calendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        entries = await generate_content_calendar(session, niche_id, lookahead_weeks=8)
    message = format_calendar(niche_name, entries)
    await update.message.reply_text(message, parse_mode="Markdown", disable_web_page_preview=True)
