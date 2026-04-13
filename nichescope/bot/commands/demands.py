"""/demands — Show audience demand signals mined from competitor comments."""
from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from nichescope.bot.formatters import format_demands
from nichescope.models import Niche, User, async_session
from nichescope.services.comment_demand import mine_comment_demands
from sqlalchemy import select

async def demands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with async_session() as session:
        stmt = select(User).where(User.telegram_chat_id == chat_id)
        user = (await session.execute(stmt)).scalar_one_or_none()
        if not user:
            await update.message.reply_text("You're not registered yet. Run /start first!")
            return
        niche = (await session.execute(
            select(Niche).where(Niche.user_id == user.id).limit(1)
        )).scalar_one_or_none()
        if not niche:
            await update.message.reply_text("No niche configured. Run /start to set up.")
            return
        await update.message.reply_text("⏳ Mining audience demands from competitor comments...")
        clusters = await mine_comment_demands(session, niche.id, max_videos=15)
    await update.message.reply_text(
        format_demands(niche.name, clusters[:8]),
        parse_mode="Markdown", disable_web_page_preview=True
    )
