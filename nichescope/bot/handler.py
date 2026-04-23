"""Single message handler — conversational GenAI + live YouTube Data API.

Flow:
  1. Guardrails (rate limit, basic safety checks)
  2. GenAI decides direct reply vs. which channel(s) to look up + whether to load videos
  3. YouTube API returns current channel/video data
  4. GenAI writes a grounded conversational answer (plain text)
  5. Separate inline-keyboard message with tappable contextual suggestions
  6. Tapping a suggestion re-runs it through the same pipeline (callback handler)
"""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from nichescope.config import settings
from nichescope.services.guardrails import check_message
from nichescope.services.llm import ResponseMeta, classify_and_respond
from nichescope.services.youtube import YouTubeAPI

logger = logging.getLogger(__name__)

_youtube = YouTubeAPI()

# ── Suggestion chip definitions ───────────────────────────────────────────────
# Each tuple: (button label, callback_data)
# callback_data prefixes:
#   q:<text>  — run as a free-text question
#   w:<name>  — run /watch <name>
#   c:<cmd>   — digest | watches | radar | digest_* | support_usage

# Shown when there is no channel context yet — guide toward commands
_COMMAND_CHIPS = [
    ("📡 /digest  — channel pulse",  "c:digest"),
    ("📋 /watches  — my watchlist",     "c:watches"),
    ("🛰️ /radar  — all commands",      "c:radar"),
]


def _channel_chips(first: str, had_videos: bool) -> list[tuple[str, str]]:
    """Build contextual chips using the ACTUAL channel name found in this query."""
    name = first[:24]
    if had_videos:
        return [
            (f"🧠 Strategy behind {name}",      f"q:What content strategy is driving views for {first}?"),
            (f"📏 Best video length for {name}", f"q:Which video length is working best for {first}?"),
            (f"🕳️ Gaps in {name}'s niche",      f"q:What niche gaps exist in {first}'s content space?"),
        ]
    return [
        (f"📹 Recent videos by {name}",       f"q:Show me recent videos from {first}"),
        (f"🕐 Upload cadence of {name}",      f"q:How often does {first} upload?"),
        (f"🕵️ Who competes with {name}?",    f"q:Who are {first}'s main competitors?"),
    ]


def _multi_channel_chips(channels: list[str]) -> list[tuple[str, str]]:
    """Chips for a comparison / multi-channel query."""
    combined = " and ".join(c[:15] for c in channels[:2])
    return [
        (f"🕳️ Gaps between them",           f"q:What niche gaps exist between {channels[0]} and {channels[1] if len(channels)>1 else channels[0]}?"),
        (f"🚀 Open lane in this space",     f"q:Where is the open lane between {combined}?"),
        (f"⚡ What format is winning?",     f"q:Which video format is winning for {combined} right now?"),
    ]


def _build_chips(meta: ResponseMeta, user_text: str) -> list[tuple[str, str]]:
    """Return up to 3 (label, callback_data) chips tailored to what was just answered."""
    channels = meta.channels_found or meta.channels_queried

    # No channel context → guide toward commands
    if meta.plan_type == "direct" or not channels:
        return list(_COMMAND_CHIPS)

    first = channels[0]
    multi = len(channels) > 1
    chips: list[tuple[str, str]] = []

    # Offer to track the channel found — only if not already a watch command
    if first and "watch" not in user_text.lower() and "/watch" not in user_text:
        chips.append((f"➕ Track {first[:20]}", f"w:{first}"))

    if multi:
        chips += _multi_channel_chips(channels)[:2]
    else:
        chips += _channel_chips(first, meta.had_videos)[:2]

    # Deduplicate, cap at 3
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for chip in chips:
        if chip[1] not in seen:
            seen.add(chip[1])
            out.append(chip)
        if len(out) == 3:
            break
    return out


def _make_keyboard(chips: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """One button per row — mirrors the web tutorial's vertical chip strip."""
    rows = [[InlineKeyboardButton(text=label, callback_data=data[:64])]
            for label, data in chips]
    return InlineKeyboardMarkup(rows)


# ── Core processing (shared by message handler + callback handler) ────────────

async def _process_query(chat_id: int, text: str, bot) -> None:
    """Run the full pipeline and send results to chat_id using the bot directly.

    Uses bot.send_message / bot.edit_message_text exclusively — avoids the
    reply_to_message_id that reply_text() adds by default, which causes 400s
    when the original message can't be found by Telegram.
    """
    result = check_message(chat_id, text)
    if not result.safe:
        await bot.send_message(chat_id, result.reason)
        return

    thinking = None
    try:
        thinking = await bot.send_message(chat_id, "\U0001f914")

        answer, meta = await classify_and_respond(
            result.sanitized_text,
            _youtube,
            chat_id=chat_id,
        )

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=thinking.message_id,
            text=answer,
        )

        chips = _build_chips(meta, text)
        if chips:
            await bot.send_message(
                chat_id,
                "\u2500\u2500 Try next:",
                reply_markup=_make_keyboard(chips),
            )

    except Exception as exc:
        logger.exception("Query error for chat_id=%d", chat_id)
        try:
            if (settings.sentry_dsn or "").strip():
                import sentry_sdk
                sentry_sdk.capture_exception(exc)
            from nichescope.services.notify import notify_server_error
            await notify_server_error(
                exc,
                f"Telegram message pipeline chat_id={chat_id}",
                extra=f"User text (truncated): {text[:500]!r}",
            )
        except Exception:
            logger.exception("Failed to notify admin of query error")
        fallback = (
            "\U0001f605 Something went wrong. Try rephrasing!\n\n"
            "You can ask things like:\n"
            "\u2022 Stats or recent videos for your channel or anyone you name\n"
            "\u2022 Compare channels or brainstorm growth / diversification ideas\n"
            "\u2022 Niche gaps or what to try next\n\n"
            "Or use /radar to see all available commands."
        )
        if thinking:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=thinking.message_id,
                    text=fallback,
                )
            except Exception:
                await bot.send_message(chat_id, fallback)
        else:
            await bot.send_message(chat_id, fallback)


# ── Message handler ───────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point for every non-command text message."""
    await _process_query(
        update.effective_chat.id,
        update.message.text,
        context.bot,
    )


# ── Callback handler (button taps) ────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles taps on any inline keyboard button produced by this bot."""
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    chat_id = update.effective_chat.id
    bot = context.bot

    # ── /watch shortcut ──
    if data.startswith("w:"):
        await query.answer()
        channel = data[2:].strip()
        if not channel:
            await bot.send_message(chat_id, "Usage: /watch <channel name or @handle>")
            return
        from nichescope.bot.watch_commands import _execute_watch
        await bot.send_message(chat_id, f"Searching for \"{channel}\" \u2026")
        await _execute_watch(chat_id, channel, bot)
        return

    # ── Built-in command shortcuts ──
    if data.startswith("c:"):
        cmd = data[2:]
        if cmd == "digest":
            from nichescope.bot.watch_commands import _execute_digest, digest_chat_is_busy
            if await digest_chat_is_busy(chat_id):
                await query.answer(text="Already on it\u2026", show_alert=False)
                return
            # answerCallbackQuery ASAP + short text so the client stops the loading ring quickly
            await query.answer(text="Building digest\u2026", show_alert=False)
            await _execute_digest(chat_id, bot)
        elif cmd == "watches":
            await query.answer(text="Loading watchlist\u2026", show_alert=False)
            from nichescope.bot.watch_commands import _execute_watches
            await _execute_watches(chat_id, bot)
        elif cmd == "radar":
            await query.answer()
            from nichescope.bot.watch_commands import _execute_radar_help
            await _execute_radar_help(chat_id, bot)
        elif cmd == "digest_off":
            await query.answer(text="Auto-digest off", show_alert=False)
            from nichescope.bot.watch_commands import _execute_digest_auto_toggle
            await _execute_digest_auto_toggle(chat_id, bot, False)
        elif cmd == "digest_on":
            await query.answer(text="Auto-digest on", show_alert=False)
            from nichescope.bot.watch_commands import _execute_digest_auto_toggle
            await _execute_digest_auto_toggle(chat_id, bot, True)
        elif cmd == "digest_status":
            await query.answer()
            from nichescope.bot.watch_commands import _execute_digest_status
            await _execute_digest_status(chat_id, bot)
        elif cmd == "support_usage":
            await query.answer()
            from nichescope.bot.support_commands import send_support_hint
            await send_support_hint(chat_id, bot)
        else:
            await query.answer()
        return

    # ── Free-text question ──
    if data.startswith("q:"):
        await query.answer(text="On it\u2026", show_alert=False)
        text = data[2:].strip()
        if not text:
            return
        await bot.send_message(chat_id, f"\U0001f449 {text}")
        await _process_query(chat_id, text, bot)
        return

    await query.answer()
