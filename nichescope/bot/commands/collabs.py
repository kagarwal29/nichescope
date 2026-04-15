"""/collabs — Find optimal collaboration partners."""
from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from nichescope.bot.formatters import format_collabs
from nichescope.bot.pipeline import ensure_fresh_analysis
from nichescope.models import Channel, Niche, User, async_session
from nichescope.services.collab_graph import find_collab_opportunities

async def collabs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with async_session() as session:
        user = (await session.execute(select(User).where(User.telegram_chat_id == chat_id))).scalar_one_or_none()
        if not user:
            await update.message.reply_text("You're not registered yet. Run /start first!"); return
        niche = (await session.execute(select(Niche).where(Niche.user_id == user.id).limit(1))).scalar_one_or_none()
        if not niche:
            await update.message.reply_text("No niche configured. Run /start to set up."); return
        user_id, niche_id, niche_name = user.id, niche.id, niche.name
        user_channel_id = None
        if user.youtube_channel_id:
            ch = (await session.execute(select(Channel).where(Channel.youtube_channel_id == user.youtube_channel_id))).scalar_one_or_none()
            user_channel_id = ch.id if ch else None
    if not await ensure_fresh_analysis(update, user_id, niche_id, niche_name):
        return
    async with async_session() as session:
        opps = await find_collab_opportunities(session, niche_id, user_channel_id=user_channel_id)
    message = format_collabs(niche_name, opps[:5])
    await update.message.reply_text(message, parse_mode="Markdown", disable_web_page_preview=True)
