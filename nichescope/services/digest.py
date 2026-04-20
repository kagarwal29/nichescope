"""Competitor digest: watched channels + GenAI-grounded pulse and next moves."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import select

from nichescope.config import settings
from nichescope.db.models import WatchChannel
from nichescope.db.session import get_session
from nichescope.services.llm import bundle_channel_data, chat_completion
from nichescope.services.youtube import YouTubeAPI

logger = logging.getLogger(__name__)

_DIGEST_SYSTEM = """You are NicheScope — a competitor radar for YouTube creators.

The user tracks the channels in the JSON below. Using ONLY that data:

1) Pulse (short): What is moving — new uploads since your window, standout videos by views, obvious scale gaps vs others in the list (use only provided numbers/titles).

2) Next moves: Exactly 3 bullets — concrete actions this week (cadence, format, packaging, shorts vs long, collaboration angle) grounded in what the data shows competitors doing. No generic creator advice.

Rules: Plain text only. No markdown. Be specific; if data is thin, say what’s missing rather than guessing. Keep under 3500 characters."""

_TELEGRAM_CHUNK = 3900


def telegram_chunks(text: str) -> list[str]:
    if not text:
        return [""]
    parts: list[str] = []
    remaining = text.strip()
    while remaining:
        parts.append(remaining[:_TELEGRAM_CHUNK])
        remaining = remaining[_TELEGRAM_CHUNK:].lstrip()
    return parts


async def _bundles_for_chat(
    youtube: YouTubeAPI,
    chat_id: int,
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Returns (bundles, list of (youtube_channel_id, saved_title))."""
    async with get_session() as session:
        result = await session.execute(
            select(WatchChannel.youtube_channel_id, WatchChannel.channel_title)
            .where(WatchChannel.chat_id == chat_id)
            .order_by(WatchChannel.created_at.asc()),
        )
        watches = [(str(a), str(b or "")) for a, b in result.all()]

    bundles: list[dict[str, Any]] = []
    for channel_id, saved_title in watches:
        ch = youtube.get_channel_by_id(channel_id)
        videos: list[dict] = []
        if ch and ch.get("uploads_playlist_id"):
            try:
                videos = youtube.get_recent_videos(
                    ch["uploads_playlist_id"],
                    count=12,
                )
            except Exception as e:
                logger.warning("Digest video fetch failed %s: %s", channel_id, e)
        label = (ch.get("title") if ch else None) or saved_title or channel_id
        bundles.append(bundle_channel_data(label, ch, videos))
    return bundles, watches


async def generate_digest_message(chat_id: int, youtube: YouTubeAPI) -> str | None:
    """Returns digest text or None if nothing to send / config blocks GenAI."""
    if not settings.genai_token or not settings.genai_model.strip():
        return None

    bundles, watches = await _bundles_for_chat(youtube, chat_id)
    if not watches:
        return None

    payload = json.dumps(bundles, indent=2, default=str)
    if len(payload) > 28000:
        payload = payload[:28000] + "\n…(truncated)"

    text = await chat_completion(
        [
            {"role": "system", "content": _DIGEST_SYSTEM},
            {
                "role": "user",
                "content": f"Tracked channels snapshot (JSON):\n{payload}",
            },
        ],
        max_tokens=1800,
        temperature=0.45,
    )
    if text:
        return text.strip()

    # Fallback: minimal grounded summary without LLM
    lines = [
        "NicheScope digest (quick summary — GenAI unavailable):",
        "",
    ]
    for b in bundles:
        if not b.get("found"):
            lines.append(f"- {b.get('lookup_query')}: not found on YouTube.")
            continue
        c = b.get("channel") or {}
        lines.append(
            f"- {c.get('title')}: {c.get('subscribers_display')} subs, "
            f"{c.get('video_count')} videos, top recent title sample in JSON."
        )
    return "\n".join(lines)


async def distinct_watch_chat_ids() -> list[int]:
    async with get_session() as session:
        result = await session.execute(select(WatchChannel.chat_id).distinct())
        return [int(x) for x in result.scalars().all()]


async def broadcast_daily_digests(bot: Any, youtube: YouTubeAPI) -> None:
    """Called by scheduler; sends digest to every chat with ≥1 watch."""
    if not settings.digest_enabled:
        return
    if not settings.youtube_api_key:
        logger.warning("Skipping digest broadcast: no YouTube API key")
        return

    chat_ids = await distinct_watch_chat_ids()
    logger.info("Daily digest: %d chats with watches", len(chat_ids))

    for cid in chat_ids:
        try:
            body = await generate_digest_message(cid, youtube)
            if not body:
                continue
            header = "📡 Daily competitor digest\n\n"
            for part in telegram_chunks(header + body):
                await bot.send_message(chat_id=cid, text=part)
            await asyncio.sleep(0.35)
        except Exception:
            logger.exception("Digest send failed chat_id=%s", cid)


def digest_preview_header() -> str:
    return "📡 Competitor digest (your watchlist)\n\n"
