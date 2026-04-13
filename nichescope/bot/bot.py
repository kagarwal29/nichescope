"""Telegram bot setup and lifecycle."""
from __future__ import annotations
import logging
from telegram.ext import ApplicationBuilder, CommandHandler
from nichescope.bot.commands.brief import brief
from nichescope.bot.commands.calendar import calendar
from nichescope.bot.commands.collabs import collabs
from nichescope.bot.commands.demands import demands
from nichescope.bot.commands.formats import formats
from nichescope.bot.commands.gaps import gaps
from nichescope.bot.commands.rival import rival
from nichescope.bot.commands.start import get_onboarding_handler
from nichescope.bot.commands.titlescore import titlescore
from nichescope.bot.commands.trending import trending
from nichescope.config import settings

logger = logging.getLogger(__name__)

def create_bot_app():
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set — bot will not start")
        return None
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.add_handler(get_onboarding_handler())
    app.add_handler(CommandHandler("brief", brief))
    app.add_handler(CommandHandler("gaps", gaps))
    app.add_handler(CommandHandler("rival", rival))
    app.add_handler(CommandHandler("trending", trending))
    app.add_handler(CommandHandler("demands", demands))
    app.add_handler(CommandHandler("calendar", calendar))
    app.add_handler(CommandHandler("collabs", collabs))
    app.add_handler(CommandHandler("formats", formats))
    app.add_handler(CommandHandler("titlescore", titlescore))
    logger.info("Telegram bot handlers registered (9 commands)")
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
