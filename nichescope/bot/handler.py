"""Single message handler — conversational GenAI + live YouTube Data API.

Flow:
  1. Guardrails (rate limit, basic safety checks)
  2. GenAI decides direct reply vs. which channel(s) to look up + whether to load videos
  3. YouTube API returns current channel/video data
  4. GenAI writes a grounded conversational answer (plain text)
  5. Contextual follow-up suggestions appended
  6. Reply to user
"""

from __future__ import annotations

import logging
import random

from telegram import Update
from telegram.ext import ContextTypes

from nichescope.services.guardrails import check_message
from nichescope.services.llm import ResponseMeta, classify_and_respond
from nichescope.services.youtube import YouTubeAPI

logger = logging.getLogger(__name__)

_youtube = YouTubeAPI()

# ── Suggestion pools ──────────────────────────────────────────────────────────

_ONBOARDING = [
    "How many subs does MrBeast have?",
    "What are Kurzgesagt's top videos?",
    "Compare MKBHD and Linus Tech Tips",
    "Is Veritasium uploading consistently?",
    "Which Python tutorial channel gets the most views?",
    "What topics are underserved in finance YouTube?",
]

_DEEPEN_STATS = [
    "Show me their recent uploads",
    "What's their upload frequency?",
    "Which video format performs best for them?",
]

_DEEPEN_VIDEOS = [
    "What's the strategy behind these titles?",
    "How are their view counts trending?",
    "Which video length is winning for them?",
]

_COMPETITOR_ANGLES = [
    "Who are their main competitors?",
    "What niche gaps do you see here?",
    "Which topics are they NOT covering?",
]

_WATCHLIST_NUDGE = [
    "/watch {ch}  — track daily",
    "/digest  — competitor pulse now",
]

_MOAT_IDEAS = [
    "What should I make next to beat them?",
    "Where is the open lane in this niche?",
    "What's working in this niche right now?",
]


def _build_suggestions(meta: ResponseMeta, user_text: str) -> list[str]:
    """Return 2–3 crisp follow-up prompts tailored to what was just answered."""
    if meta.plan_type == "direct":
        # Greeting / off-topic → onboarding examples
        picks = random.sample(_ONBOARDING, 3)
        return picks

    channels = meta.channels_found or meta.channels_queried
    first = channels[0] if channels else ""
    multi = len(channels) > 1

    suggestions: list[str] = []

    # Always offer to track if a channel was found and not already a /watch question
    if first and "/watch" not in user_text.lower():
        suggestions.append(f"/watch {first}  — add to competitor radar")

    if multi:
        # Already comparing — deepen into strategy and gaps
        suggestions += random.sample(_COMPETITOR_ANGLES, 1)
        suggestions += random.sample(_MOAT_IDEAS, 1)
    else:
        # Single channel — pivot depth axis based on what was already fetched
        if meta.had_videos:
            suggestions += random.sample(_DEEPEN_VIDEOS, 1)
            suggestions += random.sample(_COMPETITOR_ANGLES, 1)
        else:
            suggestions += random.sample(_DEEPEN_STATS, 1)
            suggestions += random.sample(_MOAT_IDEAS, 1)

    # Trim to 3, deduplicate
    seen: set[str] = set()
    out: list[str] = []
    for s in suggestions:
        if s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) == 3:
            break
    return out


def _format_suggestions(suggestions: list[str], channels: list[str]) -> str:
    """Format suggestions as a plain-text footer block."""
    if not suggestions:
        return ""

    lines = ["\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"]
    lines.append("Try next:")
    for s in suggestions:
        # Replace {ch} placeholder with first found channel name
        first = channels[0] if channels else ""
        s = s.replace("{ch}", first)
        lines.append(f"  \u2022 {s}")
    return "\n".join(lines)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for every non-command text message."""
    text = update.message.text
    chat_id = update.effective_chat.id

    # Step 1: Guardrails
    result = check_message(chat_id, text)
    if not result.safe:
        await update.message.reply_text(result.reason)
        return

    text = result.sanitized_text

    # Steps 2–4: LLM classifies → YouTube fetches → LLM responds
    thinking = await update.message.reply_text("\U0001f914")
    try:
        answer, meta = await classify_and_respond(text, _youtube)
        suggestions = _build_suggestions(meta, text)
        suffix = _format_suggestions(suggestions, meta.channels_found or meta.channels_queried)
        await thinking.edit_text(answer + suffix)
    except Exception:
        logger.exception("Handler error for chat_id=%d", chat_id)
        await thinking.edit_text(
            "\U0001f605 Something went wrong. Try rephrasing!\n\n"
            "Examples:\n"
            "\u2022 How many subs does MrBeast have?\n"
            "\u2022 Compare MKBHD and Linus Tech Tips\n"
            "\u2022 What are Kurzgesagt's top videos?",
        )
