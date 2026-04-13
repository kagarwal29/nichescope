"""/titlescore — Pre-publish title scoring and comparison."""
from __future__ import annotations
from telegram import Update
from telegram.ext import ContextTypes
from nichescope.bot.formatters import format_title_scores
from nichescope.models import Niche, User, async_session
from nichescope.services.title_predictor import compare_titles
from sqlalchemy import select

async def titlescore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    raw_text = update.message.text.strip()
    parts = raw_text.split("\n")
    first_line = parts[0].replace("/titlescore", "").strip()
    titles = [first_line] if first_line else []
    for line in parts[1:]:
        line = line.strip()
        if line:
            titles.append(line)
    if not titles:
        await update.message.reply_text(
            "📝 *Title Scorer*\n\nSend titles one per line:\n```\n/titlescore\n"
            "5 Mistakes Every Beginner Makes\nHow to Avoid Common Mistakes\n```",
            parse_mode="Markdown",
        )
        return
    if len(titles) > 10:
        await update.message.reply_text("⚠️ Max 10 titles per request.")
        return
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
        scores = await compare_titles(session, niche.id, titles)
    await update.message.reply_text(
        format_title_scores(niche.name, scores),
        parse_mode="Markdown", disable_web_page_preview=True
    )
