"""Moat MVP: competitor watchlist + digest commands.

Exposes both Update-based command handlers (for slash commands)
and _execute_* coroutines usable directly by the callback handler.
"""

from __future__ import annotations

import asyncio
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

# One digest at a time per chat (double-tap / slow callback answer no longer duplicates work).
_digest_state_lock = asyncio.Lock()
_digest_busy_chats: set[int] = set()


async def digest_chat_is_busy(chat_id: int) -> bool:
    """True if a digest is in progress for this chat (for fast callback UX)."""
    async with _digest_state_lock:
        return chat_id in _digest_busy_chats


def _compose_digest_display(llm_text: str) -> str:
    """Avoid doubling titles when the model already echoes a digest-style header."""
    raw = llm_text.strip()
    if not raw:
        return digest_preview_header()
    first = raw.split("\n", 1)[0].strip().lower()
    if (
        first.startswith("📡")
        or first.startswith("competitor digest")
        or first.startswith("nichescope digest")
    ):
        return raw + "\n"
    return digest_preview_header() + raw


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
    async with _digest_state_lock:
        if chat_id in _digest_busy_chats:
            await bot.send_message(
                chat_id,
                "A digest is already generating — check your latest messages.",
            )
            return
        _digest_busy_chats.add(chat_id)

    try:
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

        body = _compose_digest_display(text)
        for part in telegram_chunks(body):
            await bot.send_message(chat_id, part)

        from nichescope.services.chat_prefs import is_daily_digest_enabled
        auto_on = await is_daily_digest_enabled(chat_id)
        await bot.send_message(
            chat_id,
            "\u2500\u2500 Take it further:\n"
            f"Your scheduled auto-digest: {'on' if auto_on else 'off'} "
            f"(~{settings.digest_hour_utc}:00 UTC). "
            "/digest_off  /digest_on  /digest_status",
            reply_markup=_after_digest_keyboard(),
        )
    finally:
        async with _digest_state_lock:
            _digest_busy_chats.discard(chat_id)


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
    from nichescope.services.chat_prefs import is_daily_digest_enabled
    auto_on = await is_daily_digest_enabled(chat_id)
    lines.append(
        f"\nServer digest scheduler: {'on' if settings.digest_enabled else 'off'}  "
        f"(~{settings.digest_hour_utc}:00 UTC)"
    )
    lines.append(f"Your auto-digest: {'on' if auto_on else 'off'}  (/digest_off /digest_on)")

    await bot.send_message(
        chat_id,
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📡 Digest now", callback_data="c:digest")],
            [
                InlineKeyboardButton("🔕 Pause auto-digest", callback_data="c:digest_off"),
                InlineKeyboardButton("🔔 Resume", callback_data="c:digest_on"),
            ],
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


async def _execute_digest_auto_toggle(chat_id: int, bot: Bot, enabled: bool) -> None:
    from nichescope.services.chat_prefs import apply_daily_digest_toggle

    msg = await apply_daily_digest_toggle(chat_id, enabled)
    await bot.send_message(chat_id, msg)


async def _execute_digest_status(chat_id: int, bot: Bot) -> None:
    from nichescope.services.chat_prefs import daily_digest_status_message

    msg = await daily_digest_status_message(chat_id)
    await bot.send_message(
        chat_id,
        msg,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔕 Pause auto-digest", callback_data="c:digest_off"),
                InlineKeyboardButton("🔔 Resume", callback_data="c:digest_on"),
            ],
        ]),
    )


async def cmd_digest_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await _execute_digest_auto_toggle(update.effective_chat.id, context.bot, False)


async def cmd_digest_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await _execute_digest_auto_toggle(update.effective_chat.id, context.bot, True)


async def cmd_digest_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await _execute_digest_status(update.effective_chat.id, context.bot)


async def _execute_radar_help(chat_id: int, bot: Bot) -> None:
    """Competitor radar help — used by /radar and inline c:radar chips."""
    await bot.send_message(
        chat_id,
        "Competitor radar\n\n"
        "/watch <name>  \u2014 add to watchlist\n"
        "/watches  \u2014 numbered list\n"
        "/unwatch N  \u2014 remove by number\n"
        "/digest  \u2014 AI pulse now (on demand)\n"
        "/digest_off  \u2014 stop scheduled daily digest for you\n"
        "/digest_on  \u2014 turn scheduled daily digest back on\n"
        "/digest_status  \u2014 your digest settings\n\n"
        f"Server digest scheduler: ~{settings.digest_hour_utc}:00 UTC "
        f"({'on' if settings.digest_enabled else 'off'} for all chats)\n\n"
        "You can also say e.g. \"stop daily digest\" or \"resume daily digest\" in chat.\n\n"
        "For YouTube questions — just ask.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📡 Digest now",       callback_data="c:digest"),
             InlineKeyboardButton("📋 My watchlist",     callback_data="c:watches")],
            [
                InlineKeyboardButton("🔕 Pause auto-digest", callback_data="c:digest_off"),
                InlineKeyboardButton("🔔 Resume",           callback_data="c:digest_on"),
            ],
            [InlineKeyboardButton("⚙️ Digest status",     callback_data="c:digest_status")],
        ]),
    )


async def cmd_watch_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await _execute_radar_help(update.effective_chat.id, context.bot)
