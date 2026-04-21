"""Moat MVP: competitor watchlist + digest commands."""

from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from telegram import Update
from telegram.ext import ContextTypes

from nichescope.config import settings
from nichescope.db.models import WatchChannel
from nichescope.db.session import get_session
from nichescope.services.digest import (
    digest_preview_header,
    generate_digest_message,
    telegram_chunks,
)
from nichescope.services.youtube import YouTubeAPI

logger = logging.getLogger(__name__)

_youtube = YouTubeAPI()


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Onboarding — sent when a user first opens the bot or types /start."""
    if not update.message:
        return
    await update.message.reply_text(
        "Welcome to NicheScope — your YouTube intelligence agent.\n\n"
        "Just chat naturally. No commands needed for questions.\n\n"
        "Things you can ask:\n"
        "  \u2022 How many subs does MrBeast have?\n"
        "  \u2022 Compare MKBHD and Linus Tech Tips\n"
        "  \u2022 What are Kurzgesagt's top videos this year?\n"
        "  \u2022 Which topics are underserved in finance YouTube?\n"
        "  \u2022 Is Veritasium uploading consistently?\n\n"
        "Competitor radar (tracks channels for you):\n"
        "  \u2022 /watch <channel>  \u2014 add to watchlist\n"
        "  \u2022 /digest  \u2014 AI pulse + 3 next moves\n"
        "  \u2022 /watches  \u2014 your list\n"
        "  \u2022 /unwatch N  \u2014 remove by number\n\n"
        "Daily digest auto-sends at 8:00 UTC once you have a watchlist."
    )


async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a competitor channel to your digest watchlist."""
    if not update.message:
        return
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /watch <channel name or @handle>\n"
            "Example: /watch MKBHD"
        )
        return
    if not settings.youtube_api_key:
        await update.message.reply_text("YouTube API key is not configured.")
        return

    query = " ".join(args).strip()
    ch = _youtube.lookup_channel(query)
    if not ch:
        await update.message.reply_text(f'Could not find a channel for "{query}". Try another name or @handle.')
        return

    cid = ch["channel_id"]
    title = ch.get("title") or ""

    try:
        async with get_session() as session:
            session.add(
                WatchChannel(
                    chat_id=chat_id,
                    youtube_channel_id=cid,
                    channel_title=title[:500],
                )
            )
    except IntegrityError:
        await update.message.reply_text(f'Already watching "{title}".')
        return

    await update.message.reply_text(
        f'Watching "{title}".\n\n'
        f"Try next:\n"
        f"  \u2022 /digest  \u2014 get a competitor pulse right now\n"
        f"  \u2022 /watch <another channel>  \u2014 add more to compare\n"
        f"  \u2022 /watches  \u2014 see your full list\n\n"
        f"Auto-digest drops daily at ~{settings.digest_hour_utc}:00 UTC."
    )


async def cmd_unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a channel by index from /watches."""
    if not update.message:
        return
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /unwatch <number>\nSee numbers in /watches")
        return
    try:
        n = int(args[0])
    except ValueError:
        await update.message.reply_text("Usage: /unwatch <number> (integer from /watches)")
        return

    async with get_session() as session:
        result = await session.execute(
            select(WatchChannel)
            .where(WatchChannel.chat_id == chat_id)
            .order_by(WatchChannel.created_at.asc()),
        )
        rows = list(result.scalars().all())

    if n < 1 or n > len(rows):
        await update.message.reply_text("Invalid number. Run /watches first.")
        return

    victim = rows[n - 1]
    label = victim.channel_title or victim.youtube_channel_id

    async with get_session() as session:
        await session.execute(delete(WatchChannel).where(WatchChannel.id == victim.id))

    await update.message.reply_text(f"Stopped watching: {label}")


async def cmd_watches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List tracked channels."""
    if not update.message:
        return
    chat_id = update.effective_chat.id

    async with get_session() as session:
        result = await session.execute(
            select(WatchChannel)
            .where(WatchChannel.chat_id == chat_id)
            .order_by(WatchChannel.created_at.asc()),
        )
        rows = list(result.scalars().all())

    if not rows:
        await update.message.reply_text(
            "Your watchlist is empty.\n"
            "/watch <channel> — track competitors for the daily digest + /digest pulse."
        )
        return

    lines = ["Your competitor watchlist (use /unwatch N to remove):\n"]
    for i, w in enumerate(rows, start=1):
        t = w.channel_title or w.youtube_channel_id
        lines.append(f"{i}. {t}")
    lines.append("")
    lines.append(f"Daily digest (UTC {settings.digest_hour_utc}:00): {'on' if settings.digest_enabled else 'off'}")
    await update.message.reply_text("\n".join(lines))


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate digest now using live YouTube data + GenAI."""
    if not update.message:
        return
    chat_id = update.effective_chat.id

    if not settings.youtube_api_key:
        await update.message.reply_text("YouTube API key is not configured.")
        return

    text = await generate_digest_message(chat_id, _youtube)
    if not text:
        await update.message.reply_text(
            "Nothing to digest yet — add channels with /watch.\n"
            "If you already added some, check GENAI_TOKEN and GENAI_MODEL for the AI summary."
        )
        return

    body = digest_preview_header() + text
    parts = telegram_chunks(body)
    for i, part in enumerate(parts):
        await update.message.reply_text(part)

    # Nudge toward strategy questions after digest
    await update.message.reply_text(
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        "Take it further:\n"
        "  \u2022 Where is the open lane in this niche?\n"
        "  \u2022 What should I make next to beat them?\n"
        "  \u2022 Which video format is winning for [channel name]?\n"
        "  \u2022 /watch <channel>  \u2014 add another competitor"
    )


async def cmd_watch_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "Competitor radar (Moat MVP)\n\n"
        "/watch <name or @handle> — add to your watchlist\n"
        "/watches — numbered list\n"
        "/unwatch <number> — remove\n"
        "/digest — competitor pulse + next moves now\n\n"
        f"Scheduled digest: ~{settings.digest_hour_utc}:00 UTC daily "
        f"({'enabled' if settings.digest_enabled else 'disabled'}).\n\n"
        "Everything else — ask in plain chat (channel intel)."
    )
