"""Single message handler — conversational GenAI + live YouTube Data API.

Flow:
  1. Guardrails (rate limit, basic safety checks)
  2. GenAI decides direct reply vs. which channel(s) to look up + whether to load videos
  3. YouTube API returns current channel/video data
  4. GenAI writes a grounded conversational answer (plain text)
  5. Reply to user
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from nichescope.services.guardrails import check_message
from nichescope.services.llm import classify_and_respond
from nichescope.services.youtube import YouTubeAPI

logger = logging.getLogger(__name__)

_youtube = YouTubeAPI()


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

    # Step 2 + 3 + 4: LLM classifies → YouTube fetches → LLM responds
    thinking = await update.message.reply_text("🤔")
    try:
        answer = await classify_and_respond(text, _youtube)
        # Plain text: LLM output is not safe for Telegram Markdown/MarkdownV2.
        await thinking.edit_text(answer)
    except Exception:
        logger.exception("Handler error for chat_id=%d", chat_id)
        await thinking.edit_text(
            "😅 Something went wrong. Try rephrasing your question!\n\n"
            "Examples:\n"
            "• How many subs does MrBeast have?\n"
            "• Top videos on veritasium",
        )
