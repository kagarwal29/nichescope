"""Shared realtime analysis pipeline with live Telegram progress updates."""

from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import func, select

from nichescope.models import TopicCluster, Video, async_session
from nichescope.models.channel import niche_channels
from nichescope.services.gap_analyzer import compute_gap_scores
from nichescope.services.topic_clusterer import cluster_niche_topics

logger = logging.getLogger(__name__)


def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


async def count_niche_videos(niche_id: int) -> int:
    """Count how many videos we have stored for channels in this niche."""
    async with async_session() as session:
        channel_ids_subq = (
            select(niche_channels.c.channel_id)
            .where(niche_channels.c.niche_id == niche_id)
            .scalar_subquery()
        )
        count_stmt = select(func.count(Video.id)).where(
            Video.channel_id.in_(channel_ids_subq)
        )
        result = await session.execute(count_stmt)
        return result.scalar() or 0


async def ensure_fresh_analysis(
    update,
    user_id: int,
    niche_id: int,
    niche_name: str,
    force: bool = False,
) -> bool:
    """Check if analysis data exists. If not, run the full pipeline with
    live Telegram progress updates. Returns True when data is available."""
    if not force:
        async with async_session() as session:
            check = select(TopicCluster).where(TopicCluster.niche_id == niche_id).limit(1)
            result = await session.execute(check)
            if result.scalar_one_or_none():
                return True  # Already analyzed

    # Count videos first — give clear error if nothing ingested
    video_count = await count_niche_videos(niche_id)
    if video_count == 0:
        await update.message.reply_text(
            "⚠️ *No competitor videos in database yet.*\n\n"
            "It looks like channel ingestion hasn't completed. "
            "Please wait a moment and try again, or just ask me your question again.",
            parse_mode="Markdown",
        )
        return False

    start = time.time()
    step = {"text": f"🚀 Found {video_count} videos — starting analysis..."}

    msg = await update.message.reply_text(
        f"🔬 *Running analysis for: {niche_name}*\n\n"
        f"⏱ 0:00 — {step['text']}\n\n"
        f"_First run takes 1–3 min. Results cached after that._",
        parse_mode="Markdown",
    )

    running = {"active": True}

    async def _heartbeat():
        while running["active"]:
            await asyncio.sleep(4)
            if not running["active"]:
                break
            try:
                elapsed = time.time() - start
                await msg.edit_text(
                    f"🔬 *Running analysis for: {niche_name}*\n\n"
                    f"⏱ {_fmt(elapsed)} — {step['text']}\n\n"
                    f"_Results cached after first run — future commands instant_",
                    parse_mode="Markdown",
                )
            except Exception:
                pass

    heartbeat = asyncio.create_task(_heartbeat())

    try:
        step["text"] = f"🧠 Clustering {video_count} videos (TF-IDF + KMeans)..."
        clusters = []
        try:
            async with async_session() as session:
                clusters = await cluster_niche_topics(session, niche_id)
        except Exception as exc:
            running["active"] = False
            heartbeat.cancel()
            await msg.edit_text(
                f"❌ *Clustering failed* after {_fmt(time.time()-start)}\n\n"
                f"`{exc}`\n\nTry asking your question again in a moment.",
                parse_mode="Markdown",
            )
            return False

        n = len(clusters)
        if n == 0:
            running["active"] = False
            heartbeat.cancel()
            await msg.edit_text(
                f"⚠️ *Clustering returned 0 clusters* ({video_count} videos found)\n\n"
                "This usually means videos don't have enough unique text. "
                "Try adding more competitor channels or ask your question again.",
                parse_mode="Markdown",
            )
            return False

        step["text"] = f"📊 {n} clusters found — computing gap scores..."
        gaps = []
        try:
            async with async_session() as session:
                gaps = await compute_gap_scores(session, user_id, niche_id)
        except Exception as exc:
            logger.warning("Gap scoring non-fatal error: %s", exc)

        elapsed = time.time() - start
        running["active"] = False
        heartbeat.cancel()

        preview = "\n".join(f"  • {c.label}" for c in clusters[:5])
        if n > 5:
            preview += f"\n  … and {n - 5} more"

        await msg.edit_text(
            f"✅ *Analysis complete!* _{_fmt(elapsed)} total_\n\n"
            f"📊 {n} topic clusters from {video_count} videos\n"
            f"🎯 {len(gaps)} content gap opportunities\n\n"
            f"*Topics discovered:*\n{preview}\n\n"
            f"👇 Showing results now...",
            parse_mode="Markdown",
        )
        return True

    except Exception as exc:
        running["active"] = False
        heartbeat.cancel()
        logger.exception("Pipeline error")
        try:
            await msg.edit_text(
                f"❌ *Pipeline error:* `{exc}`\n\nTry asking again in a moment.",
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return False
