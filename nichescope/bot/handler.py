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
import random

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

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
#   c:<cmd>   — run a slash command (digest | watches | radar)

_ONBOARDING_CHIPS = [
    ("📊 MrBeast stats",          "q:How many subscribers does MrBeast have?"),
    ("📹 Kurzgesagt top videos",  "q:What are Kurzgesagt's top videos?"),
    ("⚔️ MKBHD vs Linus",        "q:Compare MKBHD and Linus Tech Tips"),
    ("📅 Veritasium cadence",     "q:How often does Veritasium upload?"),
    ("🕳️ Niche gaps",            "q:What topics are underserved in tech YouTube?"),
    ("📈 3Blue1Brown growth",     "q:Is 3Blue1Brown growing?"),
]

_DEEPEN_STATS = [
    ("📹 See their recent videos",      "q:Show me their recent uploads"),
    ("🕐 How often do they upload?",    "q:What is their upload frequency?"),
    ("🏆 Which format wins for them?",  "q:Which video format performs best for them?"),
]

_DEEPEN_VIDEOS = [
    ("🧠 What's their strategy?",       "q:What content strategy is driving their views?"),
    ("📏 Best video length for them?",  "q:Which video length is working best for them?"),
    ("📉 Any drop in performance?",     "q:Are their view counts trending up or down?"),
]

_COMPETITOR_ANGLES = [
    ("🕵️ Who are their rivals?",        "q:Who are their main competitors?"),
    ("🕳️ What gaps exist here?",        "q:What niche gaps do you see in this space?"),
    ("🚫 What are they NOT covering?",  "q:What topics are they not covering?"),
]

_STRATEGY_IDEAS = [
    ("🚀 What should I make next?",     "q:What should I make next to stay ahead?"),
    ("🛣️ Where is the open lane?",      "q:Where is the open lane in this niche?"),
    ("⚡ What's working right now?",    "q:What content formats are winning right now?"),
]


def _build_chips(meta: ResponseMeta, user_text: str) -> list[tuple[str, str]]:
    """Return 2–3 (label, callback_data) tuples tailored to what was just answered."""
    if meta.plan_type == "direct":
        return random.sample(_ONBOARDING_CHIPS, 3)

    channels = meta.channels_found or meta.channels_queried
    first = channels[0] if channels else ""
    multi = len(channels) > 1
    chips: list[tuple[str, str]] = []

    # Offer to track the channel(s) found — most valuable recurring action
    if first and "watch" not in user_text.lower() and "/watch" not in user_text:
        label = f"➕ Track {first[:20]}"
        chips.append((label, f"w:{first}"))

    if multi:
        chips += random.sample(_COMPETITOR_ANGLES, 1)
        chips += random.sample(_STRATEGY_IDEAS, 1)
    else:
        if meta.had_videos:
            chips += random.sample(_DEEPEN_VIDEOS, 1)
            chips += random.sample(_STRATEGY_IDEAS, 1)
        else:
            chips += random.sample(_DEEPEN_STATS, 1)
            chips += random.sample(_COMPETITOR_ANGLES, 1)

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

async def _process_query(
    text: str,
    chat_id: int,
    reply_fn,        # async callable(str) → Message  (sends the 🤔 placeholder)
    edit_fn,         # async callable(Message, str)   (edits placeholder → answer)
    followup_fn,     # async callable(str, keyboard)  (sends the chip strip)
) -> None:
    result = check_message(chat_id, text)
    if not result.safe:
        await followup_fn(result.reason, None)
        return

    thinking = await reply_fn("\U0001f914")
    try:
        answer, meta = await classify_and_respond(result.sanitized_text, _youtube)
        await edit_fn(thinking, answer)

        chips = _build_chips(meta, text)
        if chips:
            keyboard = _make_keyboard(chips)
            await followup_fn("\u2500\u2500 Try next:", keyboard)
    except Exception:
        logger.exception("Query error for chat_id=%d", chat_id)
        await edit_fn(
            thinking,
            "\U0001f605 Something went wrong. Try rephrasing!\n\n"
            "Examples:\n"
            "\u2022 How many subs does MrBeast have?\n"
            "\u2022 Compare MKBHD and Linus Tech Tips\n"
            "\u2022 What are Kurzgesagt's top videos?",
        )


# ── Message handler ───────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point for every non-command text message."""
    text = update.message.text
    chat_id = update.effective_chat.id

    async def _reply(t):
        return await update.message.reply_text(t)

    async def _edit(msg, t):
        await msg.edit_text(t)

    async def _followup(t, kb):
        await update.message.reply_text(t, reply_markup=kb)

    await _process_query(text, chat_id, _reply, _edit, _followup)


# ── Callback handler (button taps) ────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles taps on any inline keyboard button produced by this bot."""
    query = update.callback_query
    await query.answer()  # clears the Telegram loading spinner

    data = query.data or ""
    chat_id = update.effective_chat.id
    bot = context.bot

    # ── /watch shortcut ──
    if data.startswith("w:"):
        channel = data[2:].strip()
        if not channel:
            await bot.send_message(chat_id, "Usage: /watch <channel name or @handle>")
            return
        # Simulate the /watch command by delegating to watch_commands
        from nichescope.bot.watch_commands import _execute_watch
        await bot.send_message(chat_id, f"Watching \u2026 searching for \"{channel}\"")
        await _execute_watch(chat_id, channel, bot)
        return

    # ── Built-in command shortcuts ──
    if data.startswith("c:"):
        cmd = data[2:]
        if cmd == "digest":
            from nichescope.bot.watch_commands import _execute_digest
            await _execute_digest(chat_id, bot)
        elif cmd == "watches":
            from nichescope.bot.watch_commands import _execute_watches
            await _execute_watches(chat_id, bot)
        return

    # ── Free-text question ──
    if data.startswith("q:"):
        text = data[2:].strip()
        if not text:
            return

        # Show the chosen question so the conversation feels natural
        await bot.send_message(chat_id, f"\U0001f449 {text}")

        async def _reply(_t):
            return await bot.send_message(chat_id, _t)

        async def _edit(msg, t):
            await msg.edit_text(t)

        async def _followup(t, kb):
            await bot.send_message(chat_id, t, reply_markup=kb)

        await _process_query(text, chat_id, _reply, _edit, _followup)
