"""/calendar — Show seasonal content calendar with optimal publish windows."""
from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from nichescope.bot.formatters import format_calendar
from nichescope.models import Niche, User, async_session
from nichescope.services.seasonal_calendar import generate_content_calendar
from sqlalchemy import select

async def calendar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with async_session() as session:
        user = (await session.execute(
            select(User).where(User.telegram_chat_id == chat_id)
        )).scalar_one_or_none()
        if not user:
            await update.message.reply_text("You're not registered yet. Run /start first!")
            return
        niche = (await session.execute(
            select(Niche).where(Niche.user_id == user.id).limit(1)
        )).scalar_one_or_none()
        if not niche:
            await update.message.reply_text("No niche configured. Run /start to set up.")
            return
        entries = await generate_content_calendar(session, niche.id, lookahead_weeks=8)
    await update.message.reply_text(
        format_calendar(niche.name, entries),
        parse_mode="Markdown", disable_web_page_preview=True
    )
