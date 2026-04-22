"""Privacy copy, /support (email to admin), /privacy."""

from __future__ import annotations

import logging
import re

from telegram import Bot, Update
from telegram.ext import ContextTypes

from nichescope.config import settings
from nichescope.services.notify import send_admin_email, smtp_configured

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$",
)

PRIVACY_SUMMARY = """NicheScope — privacy (short)

What we process
• Messages you send in this chat (to answer questions and run commands).
• Your Telegram chat id (to tie watchlist + digest preferences to you).
• Channel names/handles you add to your watchlist and related YouTube Data API results we fetch for you.

What we do not do
• We do not read your Telegram contacts or DMs outside this bot.
• We do not sell your data.

Retention
• Watchlist and preferences stay in the bot database until you remove them or ask us to delete them.

Your controls
• /digest_off — stop scheduled digests for this chat.
• /support — email the operator (you must type your email; Telegram does not provide it).

Questions: use /support with your email."""


def support_usage_text() -> str:
    return (
        "📧 Support\n\n"
        "Telegram does not give us your email. Send one message like this:\n\n"
        "/support you@example.com Your question or bug report here\n\n"
        "That emails the team directly with your Telegram id so we can follow up.\n\n"
        "Privacy summary: /privacy"
    )


async def cmd_support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    args = context.args or []
    chat_id = update.effective_chat.id
    user = update.effective_user
    uname = f"@{user.username}" if user and user.username else "(no username)"
    uid = user.id if user else "?"

    if len(args) < 2 or "@" not in args[0]:
        await update.message.reply_text(support_usage_text())
        return

    contact_email = args[0].strip()
    if not _EMAIL_RE.match(contact_email):
        await update.message.reply_text(
            "That does not look like a valid email. Try:\n"
            "/support you@example.com Your message"
        )
        return

    user_message = " ".join(args[1:]).strip()
    if len(user_message) < 3:
        await update.message.reply_text("Please add a short message after your email.")
        return

    if not settings.admin_email.strip():
        await update.message.reply_text(
            "Support email is not configured on the server yet. "
            "Please try again later."
        )
        return

    body = (
        f"NicheScope support request\n\n"
        f"Contact email: {contact_email}\n"
        f"Telegram user: {uname}  user_id={uid}\n"
        f"chat_id: {chat_id}\n\n"
        f"Message:\n{user_message}\n"
    )
    subject = f"[NicheScope Support] {contact_email}"[:200]
    ok = await send_admin_email(subject, body)
    if ok:
        await update.message.reply_text(
            "Thanks — your note was sent to the team. "
            "We may reply at the email you provided."
        )
    else:
        if not smtp_configured():
            await update.message.reply_text(
                "Email is not fully configured (SMTP). The operator needs to set "
                "ADMIN_EMAIL and SMTP_* environment variables."
            )
        else:
            await update.message.reply_text(
                "Could not send email right now. Please try again in a few minutes."
            )
        logger.warning("Support ticket failed for chat_id=%s", chat_id)


async def cmd_privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(PRIVACY_SUMMARY)


async def send_support_hint(chat_id: int, bot: Bot) -> None:
    await bot.send_message(chat_id, support_usage_text())
