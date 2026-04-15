"""Telegram bot setup and lifecycle.

The general_message handler catches ALL non-command text — including from
first-time users — so no /start is required.  Commands remain as power-user
shortcuts but are never shown as required steps.
"""

from __future__ import annotations

import logging

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from nichescope.bot.commands.analyze import analyze
from nichescope.bot.commands.brief import brief
from nichescope.bot.commands.calendar import calendar
from nichescope.bot.commands.collabs import collabs
from nichescope.bot.commands.demands import demands
from nichescope.bot.commands.formats import formats
from nichescope.bot.commands.gaps import gaps
from nichescope.bot.commands.general_message import general_message
from nichescope.bot.commands.rival import rival
from nichescope.bot.commands.titlescore import titlescore
from nichescope.bot.commands.trending import trending
from nichescope.config import settings

logger = logging.getLogger(__name__)


async def _start_shortcut(update, context):
    """Minimal /start — just a welcome, no multi-step onboarding."""
    await update.message.reply_text(
        "👋 *Welcome to NicheScope!*\n\n"
        "Just tell me what kind of YouTube channel you're interested in, "
        "and I'll analyze the landscape for you.\n\n"
        "For example:\n"
        "• _\"I want to start a mock interview channel\"_\n"
        "• _\"What's not getting covered in home cooking?\"_\n"
        "• _\"Analyze the personal finance niche\"_\n\n"
        "_No setup needed — just type your question!_",
        parse_mode="Markdown",
    )


def create_bot_app():
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set — bot will not start")
        return None

    app = ApplicationBuilder().token(settings.telegram_bot_token).build()

    # /start — simple welcome message (no multi-step onboarding)
    app.add_handler(CommandHandler("start", _start_shortcut))

    # Power-user command shortcuts
    app.add_handler(CommandHandler("brief", brief))
    app.add_handler(CommandHandler("gaps", gaps))
    app.add_handler(CommandHandler("rival", rival))
    app.add_handler(CommandHandler("trending", trending))
    app.add_handler(CommandHandler("demands", demands))
    app.add_handler(CommandHandler("calendar", calendar))
    app.add_handler(CommandHandler("collabs", collabs))
    app.add_handler(CommandHandler("formats", formats))
    app.add_handler(CommandHandler("titlescore", titlescore))
    app.add_handler(CommandHandler("analyze", analyze))

    # Conversational handler — catches ALL non-command text (including new users)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, general_message))

    logger.info("Telegram bot handlers registered (10 commands + conversational handler)")
    return app


async def start_bot_polling():
    app = create_bot_app()
    if app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        logger.info("Telegram bot started (polling mode)")
        return app
    return None


async def stop_bot(app):
    if app:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
