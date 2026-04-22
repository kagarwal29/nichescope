"""Admin alerts via SMTP (server errors) — optional when env is configured."""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
import time
import traceback
from email.message import EmailMessage

from nichescope.config import settings

logger = logging.getLogger(__name__)

_last_server_error_email_at: float = 0.0
_SERVER_ERROR_COOLDOWN_SEC = 120.0


def smtp_configured() -> bool:
    return bool(
        settings.admin_email.strip()
        and settings.smtp_host.strip()
        and settings.smtp_from.strip()
    )


def _send_smtp_sync(subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject[:900]
    msg["From"] = settings.smtp_from.strip()
    msg["To"] = settings.admin_email.strip()
    msg.set_content(body[:500_000])
    ctx = ssl.create_default_context()

    if settings.smtp_ssl:
        with smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            context=ctx,
            timeout=30,
        ) as smtp:
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        return

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls(context=ctx)
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


async def send_admin_email(subject: str, body: str) -> bool:
    """Send one email to ADMIN_EMAIL. Returns False if SMTP not configured or send failed."""
    if not smtp_configured():
        logger.debug("SMTP not configured — skip email: %s", subject[:80])
        return False
    try:
        await asyncio.to_thread(_send_smtp_sync, subject, body)
        return True
    except Exception:
        logger.exception("Failed to send admin email: %s", subject[:80])
        return False


async def notify_server_error(exc: BaseException, context: str, *, extra: str = "") -> None:
    """Email admin on uncaught server errors (rate-limited to avoid SMTP floods)."""
    global _last_server_error_email_at
    if not smtp_configured():
        return
    now = time.monotonic()
    if now - _last_server_error_email_at < _SERVER_ERROR_COOLDOWN_SEC:
        logger.warning("Server error email skipped (cooldown): %s", context)
        return
    _last_server_error_email_at = now

    if exc.__traceback__ is not None:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    else:
        tb = "".join(traceback.format_exception_only(type(exc), exc))
    body = (
        f"Context: {context}\n\n"
        f"{type(exc).__name__}: {exc}\n\n"
        f"{extra}\n\n"
        f"--- Traceback ---\n{tb}"
    )
    subject = f"[NicheScope ERROR] {type(exc).__name__}: {context}"[:200]
    await send_admin_email(subject, body)
