"""/collabs — Find optimal collaboration partners."""
from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from nichescope.bot.formatters import format_collabs
from nichescope.models import Channel, Niche, User, async_session
from nichescope.services.collab_graph import find_collab_opportunities
from sqlalchemy import select

async def collabs(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        user_channel_id = None
        if user.youtube_channel_id:
            ch = (await session.execute(
                select(Channel).where(Channel.youtube_channel_id == user.youtube_channel_id)
            )).scalar_one_or_none()
            user_channel_id = ch.id if ch else None
        opps = await find_collab_opportunities(session, niche.id, user_channel_id=user_channel_id)
    await update.message.reply_text(
        format_collabs(niche.name, opps[:5]),
        parse_mode="Markdown", disable_web_page_preview=True
    )
