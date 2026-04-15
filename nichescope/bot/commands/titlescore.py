"""/titlescore — Pre-publish title scoring and comparison."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from nichescope.bot.formatters import format_title_scores
from nichescope.models import Niche, User, async_session
from nichescope.services.title_predictor import compare_titles
from sqlalchemy import select


async def titlescore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Score title candidates before publishing.

    Usage: /titlescore
    Title Option 1
    Title Option 2
    Title Option 3

    Or: /titlescore My Single Title To Score
    """
    chat_id = update.effective_chat.id
    raw_text = update.message.text.strip()

    # Parse titles: everything after /titlescore, one per line
    parts = raw_text.split("\n")
    # First line may be "/titlescore Some Title" or just "/titlescore"
    first_line = parts[0].replace("/titlescore", "").strip()
    titles = []
    if first_line:
        titles.append(first_line)
    for line in parts[1:]:
        line = line.strip()
        if line:
            titles.append(line)

    if not titles:
        await update.message.reply_text(
            "📝 *Title Scorer — Pre-Publish A/B Testing*\n\n"
            "Send your title options, one per line:\n\n"
            "```\n"
            "/titlescore\n"
            "5 Mistakes Every Beginner Makes\n"
            "How to Avoid Common Beginner Mistakes\n"
            "Beginner? Don't Make These Mistakes!\n"
            "```\n\n"
            "I'll score each one against your niche's historical patterns.",
            parse_mode="Markdown",
        )
        return

    if len(titles) > 10:
        await update.message.reply_text("⚠️ Max 10 titles per request. Send fewer options.")
        return

    async with async_session() as session:
        stmt = select(User).where(User.telegram_chat_id == chat_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            await update.message.reply_text("You're not registered yet. Run /start first!")
            return

        niche_stmt = select(Niche).where(Niche.user_id == user.id).limit(1)
        niche_result = await session.execute(niche_stmt)
        niche = niche_result.scalar_one_or_none()

        if not niche:
            await update.message.reply_text("No niche configured. Run /start to set up.")
            return

        scores = await compare_titles(session, niche.id, titles)

    message = format_title_scores(niche.name, scores)
    await update.message.reply_text(message, parse_mode="Markdown", disable_web_page_preview=True)
