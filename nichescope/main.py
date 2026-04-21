"""NicheScope v2 — FastAPI entrypoint.

Bot transport is auto-selected:
  TELEGRAM_WEBHOOK_URL set  →  webhook mode (Telegram pushes updates in)
  not set                   →  polling mode (bot pulls from Telegram)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status

from nichescope.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# Shared bot Application instance — set during lifespan, used by /webhook route.
_bot_app: Any = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bot_app

    from nichescope.db.session import close_db, init_db
    await init_db()

    if settings.telegram_bot_token:
        use_webhook = bool(settings.telegram_webhook_url)
        mode = "webhook" if use_webhook else "polling"
        logger.info("Starting Telegram bot in %s mode", mode)

        try:
            if use_webhook:
                from nichescope.bot.bot import start_webhook_mode
                _bot_app = await start_webhook_mode()
            else:
                from nichescope.bot.bot import start_bot_polling
                _bot_app = await start_bot_polling()
        except Exception as exc:
            logger.warning(
                "Telegram bot failed to start in %s mode: %s: %s",
                mode, type(exc).__name__, exc,
            )
            if not use_webhook:
                logger.warning(
                    "Polling requires outbound access to api.telegram.org. "
                    "Set TELEGRAM_WEBHOOK_URL to switch to webhook mode."
                )

    yield

    from nichescope.bot.bot import stop_bot
    try:
        await stop_bot(_bot_app)
    except Exception as exc:
        logger.warning("Bot shutdown error (ignored): %s", exc)
    finally:
        _bot_app = None

    from nichescope.services.llm import close_genai_http_client
    await close_genai_http_client()
    await close_db()
    logger.info("Shutdown complete")


app = FastAPI(
    title="NicheScope",
    description="YouTube channel intelligence — LLM-powered",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/debug/webhook")
async def debug_webhook():
    """Returns live Telegram getWebhookInfo — useful for diagnosing delivery issues."""
    if _bot_app is None:
        return {"error": "bot not initialised"}
    try:
        info = await _bot_app.bot.get_webhook_info()
        return {
            "url": info.url,
            "has_custom_certificate": info.has_custom_certificate,
            "pending_update_count": info.pending_update_count,
            "last_error_date": str(info.last_error_date) if info.last_error_date else None,
            "last_error_message": info.last_error_message,
            "max_connections": info.max_connections,
            "allowed_updates": list(info.allowed_updates or []),
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/health")
async def health():
    mode = "webhook" if settings.telegram_webhook_url else "polling"
    return {
        "status": "ok",
        "service": "nichescope",
        "version": "2.0.0",
        "bot_mode": mode,
        "bot_connected": _bot_app is not None,
    }


@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Receive updates pushed by Telegram (webhook mode only)."""
    if not settings.telegram_webhook_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook mode not enabled.",
        )

    # Verify secret token when configured — prevents spoofed requests.
    if settings.telegram_webhook_secret:
        header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if header != settings.telegram_webhook_secret:
            logger.warning("Webhook: invalid secret token from %s", request.client)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid secret token.",
            )

    if _bot_app is None:
        logger.warning("Webhook received but bot is not initialised — dropping update")
        # Still return 200 so Telegram does not retry indefinitely.
        return {"ok": False, "detail": "bot not ready"}

    try:
        data = await request.json()
        from nichescope.bot.bot import process_webhook_update
        await process_webhook_update(_bot_app, data)
    except Exception as exc:
        logger.exception("Error processing webhook update: %s", exc)
        # Return 200 to prevent Telegram retrying a broken update.

    return {"ok": True}
