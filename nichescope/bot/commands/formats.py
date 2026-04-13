"""/formats — Show which video formats perform best per topic."""
from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from nichescope.bot.formatters import format_format_insights
from nichescope.models import Niche, User, async_session
from nichescope.services.format_intel import analyze_format_performance
from sqlalchemy import select

async def formats(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        insights = await analyze_format_performance(session, niche.id)
    await update.message.reply_text(
        format_format_insights(niche.name, insights[:8]),
        parse_mode="Markdown", disable_web_page_preview=True
    )
