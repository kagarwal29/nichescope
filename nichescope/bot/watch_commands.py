"""Moat MVP: competitor watchlist + digest commands.

Exposes both Update-based command handlers (for slash commands)
and _execute_* coroutines usable directly by the callback handler.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
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


# ── Inline keyboards ──────────────────────────────────────────────────────────

def _start_commands_keyboard() -> InlineKeyboardMarkup:
    """Commands shown on /start — no assumed channels."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 /digest  — competitor pulse",  callback_data="c:digest")],
        [InlineKeyboardButton("📋 /watches  — my watchlist",     callback_data="c:watches")],
        [InlineKeyboardButton("🛰️ /radar  — all commands",      callback_data="c:radar")],
    ])

def _after_watch_keyboard(title: str) -> InlineKeyboardMarkup:
    """Chips shown right after /watch succeeds."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Get competitor pulse now", callback_data="c:digest")],
        [InlineKeyboardButton("📋 See my watchlist",         callback_data="c:watches")],
        [InlineKeyboardButton("🕳️ Find niche gaps",         callback_data="q:What niche gaps exist in this space?")],
    ])

def _after_digest_keyboard() -> InlineKeyboardMarkup:
    """Chips shown after /digest — push into strategy territory."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛣️ Where is the open lane?",    callback_data="q:Where is the open lane in this niche?")],
        [InlineKeyboardButton("🚀 What should I make next?",   callback_data="q:What should I make next to beat them?")],
        [InlineKeyboardButton("⚡ What format is winning?",    callback_data="q:Which video format is winning right now?")],
    ])

def _empty_watchlist_keyboard() -> InlineKeyboardMarkup:
    """Shown when /watches or /digest is run with no channels."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛰️ How to add channels (/radar)", callback_data="c:radar")],
    ])


# ── /start — onboarding ───────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Onboarding — clear session state, show commands."""
    if not update.message:
        return

    from nichescope.services.guardrails import clear_user_state
    clear_user_state(update.effective_chat.id)

    await update.message.reply_text(
        "Welcome to NicheScope \U0001f52d\n\n"
        "Your YouTube intelligence agent.\n\n"
        "Just type any YouTube channel name or ask a question \u2014 "
        "I'll look up real data and answer.\n\n"
        "Or jump straight to a command:",
        reply_markup=_start_commands_keyboard(),
    )


# ── _execute_* helpers (called by both commands and the callback handler) ─────

async def _execute_watch(chat_id: int, query: str, bot: Bot) -> None:
    if not settings.youtube_api_key:
        await bot.send_message(chat_id, "YouTube API key is not configured.")
        return

    ch = _youtube.lookup_channel(query)
    if not ch:
        await bot.send_message(chat_id, f'Could not find a channel for "{query}". Try another name or @handle.')
        return

    cid = ch["channel_id"]
    title = ch.get("title") or query

    try:
        async with get_session() as session:
            session.add(WatchChannel(
                chat_id=chat_id,
                youtube_channel_id=cid,
                channel_title=title[:500],
            ))
    except IntegrityError:
        await bot.send_message(chat_id, f'Already watching "{title}".')
        return

    await bot.send_message(
        chat_id,
        f'Watching "{title}".\n\nAuto-digest drops daily at ~{settings.digest_hour_utc}:00 UTC.',
        reply_markup=_after_watch_keyboard(title),
    )


async def _execute_digest(chat_id: int, bot: Bot) -> None:
    if not settings.youtube_api_key:
        await bot.send_message(chat_id, "YouTube API key is not configured.")
        return

    text = await generate_digest_message(chat_id, _youtube)
    if not text:
        await bot.send_message(
            chat_id,
            "Your watchlist is empty.\n\n"
            "Add a channel you want to track:\n"
            "/watch <channel name>\n\n"
            "Example: /watch <name of a channel you care about>",
            reply_markup=_empty_watchlist_keyboard(),
        )
        return

    body = digest_preview_header() + text
    for part in telegram_chunks(body):
        await bot.send_message(chat_id, part)

    await bot.send_message(
        chat_id,
        "\u2500\u2500 Take it further:",
        reply_markup=_after_digest_keyboard(),
    )


async def _execute_watches(chat_id: int, bot: Bot) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(WatchChannel)
            .where(WatchChannel.chat_id == chat_id)
            .order_by(WatchChannel.created_at.asc()),
        )
        rows = list(result.scalars().all())

    if not rows:
        await bot.send_message(
            chat_id,
            "Your watchlist is empty.\n\n"
            "Use /watch <channel name> to add a channel you want to track.",
            reply_markup=_empty_watchlist_keyboard(),
        )
        return

    lines = ["Your competitor watchlist (use /unwatch N to remove):\n"]
    for i, w in enumerate(rows, start=1):
        lines.append(f"{i}. {w.channel_title or w.youtube_channel_id}")
    lines.append(f"\nDaily digest: {settings.digest_hour_utc}:00 UTC  ({'on' if settings.digest_enabled else 'off'})")

    await bot.send_message(
        chat_id,
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📡 Digest now", callback_data="c:digest")],
        ]),
    )


# ── Slash command handlers (thin wrappers around _execute_*) ─────────────────

async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a competitor channel to your digest watchlist."""
    if not update.message:
        return
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /watch <channel name or @handle>\nExample: /watch MKBHD"
        )
        return
    await _execute_watch(chat_id, " ".join(args).strip(), context.bot)


async def cmd_unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    await update.message.reply_text(
        f"Stopped watching: {label}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 View updated watchlist", callback_data="c:watches")],
        ]),
    )


async def cmd_watches(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await _execute_watches(update.effective_chat.id, context.bot)


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await _execute_digest(update.effective_chat.id, context.bot)


async def _execute_radar_help(chat_id: int, bot: Bot) -> None:
    """Competitor radar help — used by /radar and inline c:radar chips."""
    await bot.send_message(
        chat_id,
        "Competitor radar\n\n"
        "/watch <name>  \u2014 add to watchlist\n"
        "/watches  \u2014 numbered list\n"
        "/unwatch N  \u2014 remove by number\n"
        "/digest  \u2014 AI pulse + 3 next moves\n\n"
        f"Daily digest: ~{settings.digest_hour_utc}:00 UTC "
        f"({'enabled' if settings.digest_enabled else 'disabled'})\n\n"
        "For anything else — just ask in chat.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📡 Digest now",       callback_data="c:digest"),
             InlineKeyboardButton("📋 My watchlist",     callback_data="c:watches")],
        ]),
    )


async def cmd_watch_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await _execute_radar_help(update.effective_chat.id, context.bot)
