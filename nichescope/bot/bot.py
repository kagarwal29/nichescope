"""Telegram bot — competitor commands + conversational YouTube assistant.

Supports two transport modes (auto-selected by config):
  - Webhook (TELEGRAM_WEBHOOK_URL set): Telegram POSTs updates to /webhook on
    our FastAPI server.  Outbound connection to api.telegram.org only needed at
    startup to register/deregister the webhook URL.
  - Polling (fallback): bot opens a long-poll connection to api.telegram.org
    (requires reliable outbound access — does NOT work on blocked networks).
"""

from __future__ import annotations

import logging
from datetime import time, timezone

from telegram import Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, JobQueue, MessageHandler, filters

from nichescope.bot.handler import handle_callback, handle_message
from nichescope.bot.watch_commands import (
    cmd_digest,
    cmd_digest_off,
    cmd_digest_on,
    cmd_digest_status,
    cmd_start,
    cmd_unwatch,
    cmd_watch,
    cmd_watch_help,
    cmd_watches,
)
from nichescope.config import settings

logger = logging.getLogger(__name__)


def register_digest_scheduler(application) -> None:
    """Daily UTC digest for every chat with at least one watched channel."""

    async def daily_job(context):
        from nichescope.services.digest import broadcast_daily_digests
        from nichescope.services.youtube import YouTubeAPI

        yt = YouTubeAPI()
        await broadcast_daily_digests(context.bot, yt)

    if not settings.digest_enabled:
        logger.info("Digest scheduler off (DIGEST_ENABLED=false)")
        return
    jq = application.job_queue
    if jq is None:
        logger.warning("JobQueue unavailable — install python-telegram-bot[job-queue]")
        return

    jq.run_daily(
        daily_job,
        time=time(hour=settings.digest_hour_utc % 24, minute=0, tzinfo=timezone.utc),
        name="nichescope_daily_digest",
    )
    logger.info("Daily digest scheduled %02d:00 UTC", settings.digest_hour_utc % 24)


def _corp_ssl_context():
    """Build an SSL context that trusts the corporate CA bundle (Uber + Zscaler)."""
    import os, ssl
    # SSL_CERT_FILE env var is the most reliable override on corporate networks.
    bundle = (
        os.environ.get("SSL_CERT_FILE")
        or (settings.ssl_ca_bundle or "").strip()
    )
    if not bundle or bundle.lower() == "false":
        return None
    from pathlib import Path
    if not Path(bundle).is_file():
        return None
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(bundle)
    logger.info("Telegram bot TLS: loaded corporate CA bundle from %s", bundle)
    return ctx


def create_bot_app():
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set — bot will not start")
        return None

    builder = ApplicationBuilder().token(settings.telegram_bot_token).job_queue(JobQueue())

    ssl_ctx = _corp_ssl_context()
    if ssl_ctx is not None:
        from telegram.request import HTTPXRequest
        builder = builder.request(HTTPXRequest(ssl=ssl_ctx))

    app = builder.build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("unwatch", cmd_unwatch))
    app.add_handler(CommandHandler("watches", cmd_watches))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("digest_off", cmd_digest_off))
    app.add_handler(CommandHandler("digest_on", cmd_digest_on))
    app.add_handler(CommandHandler("digest_status", cmd_digest_status))
    app.add_handler(CommandHandler("radar", cmd_watch_help))

    register_digest_scheduler(app)

    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT, handle_message))
    logger.info("Telegram bot handlers registered")
    return app


# ── Webhook mode ────────────────────────────────────────────────────────────

async def start_webhook_mode() -> object | None:
    """Register webhook with Telegram and start the Application (no updater/polling)."""
    app = create_bot_app()
    if not app:
        return None

    await app.initialize()
    await app.start()

    url = settings.telegram_webhook_url.rstrip("/")
    secret = settings.telegram_webhook_secret or None

    await app.bot.set_webhook(
        url=url,
        secret_token=secret,
        allowed_updates=["message", "callback_query", "inline_query"],
        drop_pending_updates=True,
    )
    info = await app.bot.get_webhook_info()
    logger.info(
        "Webhook registered — url=%s pending=%s",
        info.url,
        info.pending_update_count,
    )
    return app


async def process_webhook_update(app, data: dict) -> None:
    """Feed a raw JSON dict from the webhook POST into the Application."""
    update = Update.de_json(data, app.bot)
    await app.process_update(update)


async def stop_webhook_mode(app) -> None:
    if not app:
        return
    try:
        await app.bot.delete_webhook(drop_pending_updates=False)
        logger.info("Webhook deregistered")
    except Exception as exc:
        logger.warning("Could not deregister webhook: %s", exc)
    await app.stop()
    await app.shutdown()


# ── Polling mode ─────────────────────────────────────────────────────────────

async def start_bot_polling() -> object | None:
    app = create_bot_app()
    if not app:
        return None
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram bot started (polling mode)")
    return app


async def stop_polling_mode(app) -> None:
    if not app:
        return
    try:
        await app.updater.stop()
    except Exception as exc:
        logger.warning("Updater stop error: %s", exc)
    await app.stop()
    await app.shutdown()


# ── Unified stop (works for both modes) ──────────────────────────────────────

async def stop_bot(app) -> None:
    if not app:
        return
    if settings.telegram_webhook_url:
        await stop_webhook_mode(app)
    else:
        await stop_polling_mode(app)
