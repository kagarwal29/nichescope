"""General message handler — fully conversational, zero-onboarding flow."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time

from sqlalchemy import select
from telegram import Bot, Update
from telegram.ext import ContextTypes

from nichescope.config import settings
from nichescope.models import (
    Channel, Niche, User, Video, async_session, niche_channels,
)
from nichescope.services.guardrails import check_message

logger = logging.getLogger(__name__)

_onboarding_in_progress: set[int] = set()


async def general_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text
    chat_id = update.effective_chat.id

    result = check_message(chat_id, raw)
    if not result.safe:
        await update.message.reply_text(result.reason, parse_mode="Markdown")
        return

    text = result.sanitized_text

    async with async_session() as session:
        user = (await session.execute(
            select(User).where(User.telegram_chat_id == chat_id)
        )).scalar_one_or_none()

    if not user:
        await _handle_new_user(update, context, chat_id, text)
        return

    async with async_session() as session:
        niche = (await session.execute(
            select(Niche).where(Niche.user_id == user.id).limit(1)
        )).scalar_one_or_none()

    if not niche:
        await _handle_no_niche(update, context, chat_id, user.id, text)
        return

    if chat_id in _onboarding_in_progress:
        await update.message.reply_text(
            f"⏳ Still analyzing *{niche.name}* for you — hang tight!\n"
            f"I'll message you as soon as results are ready.",
            parse_mode="Markdown",
        )
        return

    from nichescope.services.niche_discoverer import extract_niche
    mentioned_niche = extract_niche(text)
    if mentioned_niche and _is_different_niche(mentioned_niche, niche.name):
        await _switch_niche(update, chat_id, user.id, mentioned_niche, text)
        return

    from nichescope.services.insights_engine import answer_question

    thinking = await update.message.reply_text("🤔")
    try:
        answer = await answer_question(chat_id, text)
        await thinking.edit_text(answer, parse_mode="Markdown")
    except Exception:
        logger.exception("Insights engine error for chat_id=%d", chat_id)
        await thinking.edit_text(
            "😅 Sorry, I couldn't process that. Try rephrasing your question!",
        )


async def _handle_new_user(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            chat_id: int, text: str):
    from nichescope.services.niche_discoverer import extract_niche
    niche_name = extract_niche(text)

    if niche_name:
        from nichescope.services.niche_discoverer import extract_reference_channel
        ref_channel = extract_reference_channel(text)

        ref_msg = ""
        if ref_channel:
            ref_msg = f"\n\nI'll use *{ref_channel}* as a reference to find the best competitors."

        await update.message.reply_text(
            f"👋 Welcome! I see you're interested in *{niche_name}*.{ref_msg}\n\n"
            f"🔍 Setting up your dashboard now — finding top channels and "
            f"analyzing content opportunities.\n\n"
            f"_Usually takes about a minute. I'll ping you when it's ready!_",
            parse_mode="Markdown",
        )

        user_id, niche_id = await _auto_create_account(chat_id, niche_name)
        _onboarding_in_progress.add(chat_id)

        asyncio.create_task(
            _auto_discover_and_analyze(chat_id, user_id, niche_id, niche_name, text, ref_channel)
        )
    else:
        await update.message.reply_text(
            "👋 Hey! I'm *NicheScope* — I help YouTube creators find "
            "content gaps and understand what works in their space.\n\n"
            "Tell me what you're interested in:\n\n"
            "• _\"I want to start a mock interview channel\"_\n"
            "• _\"What's working in home cooking on YouTube?\"_\n"
            "• _\"Find channels similar to MKBHD\"_\n\n"
            "_Just describe it naturally — I'll handle the rest!_",
            parse_mode="Markdown",
        )


async def _handle_no_niche(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            chat_id: int, user_id: int, text: str):
    from nichescope.services.niche_discoverer import extract_niche
    niche_name = extract_niche(text)

    if niche_name:
        from nichescope.services.niche_discoverer import extract_reference_channel
        ref_channel = extract_reference_channel(text)

        await update.message.reply_text(
            f"🔍 Analyzing *{niche_name}* for you now...\n"
            f"_Finding top channels and content gaps. Back in ~1 min!_",
            parse_mode="Markdown",
        )

        niche_id = await _create_niche(user_id, niche_name)
        _onboarding_in_progress.add(chat_id)

        asyncio.create_task(
            _auto_discover_and_analyze(chat_id, user_id, niche_id, niche_name, text, ref_channel)
        )
    else:
        await update.message.reply_text(
            "What kind of YouTube channel are you interested in?\n\n"
            "Tell me a topic — like _\"mock interviews\"_, "
            "_\"budget cooking\"_, or _\"indie game dev\"_ — "
            "and I'll map out the landscape for you.",
            parse_mode="Markdown",
        )


def _is_different_niche(new_niche: str, current_niche: str) -> bool:
    n = new_niche.lower().strip()
    c = current_niche.lower().strip()
    if n in c or c in n:
        return False
    n_words = set(n.split())
    c_words = set(c.split())
    overlap = len(n_words & c_words)
    total = max(len(n_words), len(c_words))
    if total > 0 and overlap / total > 0.5:
        return False
    return True


async def _switch_niche(update: Update, chat_id: int, user_id: int,
                        new_niche: str, original_text: str):
    from nichescope.services.niche_discoverer import extract_reference_channel
    ref_channel = extract_reference_channel(original_text)

    await update.message.reply_text(
        f"🔄 Switching to *{new_niche}*!\n"
        f"_Finding top channels and analyzing opportunities..._",
        parse_mode="Markdown",
    )

    niche_id = await _create_niche(user_id, new_niche)
    _onboarding_in_progress.add(chat_id)

    asyncio.create_task(
        _auto_discover_and_analyze(chat_id, user_id, niche_id, new_niche, original_text, ref_channel)
    )


async def _auto_create_account(chat_id: int, niche_name: str) -> tuple[int, int]:
    async with async_session() as session:
        existing = (await session.execute(
            select(User).where(User.telegram_chat_id == chat_id)
        )).scalar_one_or_none()

        if existing:
            user = existing
        else:
            user = User(
                telegram_chat_id=chat_id,
                api_key=secrets.token_urlsafe(32),
            )
            session.add(user)
            await session.flush()

        niche = Niche(
            user_id=user.id,
            name=niche_name,
            seed_keywords=json.dumps(niche_name.split()),
        )
        session.add(niche)
        await session.flush()
        await session.commit()

        return user.id, niche.id


async def _create_niche(user_id: int, niche_name: str) -> int:
    async with async_session() as session:
        niche = Niche(
            user_id=user_id,
            name=niche_name,
            seed_keywords=json.dumps(niche_name.split()),
        )
        session.add(niche)
        await session.flush()
        await session.commit()
        return niche.id


def _opportunity_label(score: float) -> str:
    """Convert raw gap score to a human-readable opportunity level."""
    if score >= 75:
        return "🟢 Easy win"
    elif score >= 50:
        return "🟡 Good opportunity"
    elif score >= 30:
        return "🟠 Moderate competition"
    else:
        return "🔴 Crowded"


def _fmt_num(n: int | float) -> str:
    """Format a number for display."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,.0f}"


async def _auto_discover_and_analyze(
    chat_id: int,
    user_id: int,
    niche_id: int,
    niche_name: str,
    original_question: str,
    reference_channel: str | None = None,
):
    bot = Bot(token=settings.telegram_bot_token)

    async def msg(text, **kwargs):
        try:
            return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception as e:
            logger.warning("Failed to send msg to %d: %s", chat_id, e)
            return None

    try:
        # ── Step 1: Discover competitor channels ──
        from nichescope.services.niche_discoverer import discover_competitor_channels

        channels_found = discover_competitor_channels(
            niche_name, max_channels=5, reference_channel=reference_channel
        )

        if not channels_found:
            await msg(
                f"😕 Couldn't find channels in *{niche_name}*.\n\n"
                f"Try describing it differently — e.g. instead of "
                f"\"FAANG mock interviews\", try \"coding interviews\".",
                parse_mode="Markdown",
            )
            _onboarding_in_progress.discard(chat_id)
            return

        # Short progress update with channel names
        ch_names = "\n".join(
            f"  {i+1}. {ch['title']}" for i, ch in enumerate(channels_found[:5])
        )
        await msg(
            f"Found {len(channels_found)} channels in *{niche_name}*:\n\n"
            f"{ch_names}\n\n"
            f"📡 Fetching their videos now...",
            parse_mode="Markdown",
        )

        # ── Step 2: Ingest each channel ──
        from nichescope.services.channel_ingester import ingest_channel

        ingested_count = 0
        total_videos = 0

        for ch_data in channels_found:
            try:
                async with async_session() as session:
                    channel = await ingest_channel(session, ch_data["youtube_channel_id"])

                    from sqlalchemy import func
                    count_result = await session.execute(
                        select(func.count(Video.id)).where(Video.channel_id == channel.id)
                    )
                    vid_count = count_result.scalar() or 0
                    total_videos += vid_count

                    existing_assoc = (await session.execute(
                        select(niche_channels.c.channel_id).where(
                            niche_channels.c.niche_id == niche_id,
                            niche_channels.c.channel_id == channel.id,
                        )
                    )).scalar_one_or_none()

                    if not existing_assoc:
                        await session.execute(
                            niche_channels.insert().values(
                                niche_id=niche_id, channel_id=channel.id
                            )
                        )
                    await session.commit()

                ingested_count += 1
            except Exception as e:
                logger.warning("Failed to ingest channel %s: %s", ch_data.get("title"), e)

        if ingested_count == 0:
            await msg(
                "😕 Couldn't fetch video data — try again in a moment.",
            )
            _onboarding_in_progress.discard(chat_id)
            return

        await msg(f"🧠 Analyzing {total_videos} videos from {ingested_count} channels...")

        # ── Step 3: Topic clustering ──
        from nichescope.services.topic_clusterer import cluster_niche_topics

        clusters = []
        try:
            async with async_session() as session:
                clusters = await cluster_niche_topics(session, niche_id)
        except Exception as e:
            logger.warning("Clustering failed for niche %d: %s", niche_id, e)

        # ── Step 4: Gap scoring ──
        gaps = []
        if clusters:
            try:
                from nichescope.services.gap_analyzer import compute_gap_scores
                async with async_session() as session:
                    gaps = await compute_gap_scores(session, user_id, niche_id)
            except Exception as e:
                logger.warning("Gap scoring failed: %s", e)

        _onboarding_in_progress.discard(chat_id)

        # ── Step 5: Build the consultant-style brief ──
        response = f"✅ *{niche_name} — Your Brief*\n\n"

        # ── A) Top competitors — clean table ──
        response += "*🏆 Top Competitors*\n"
        for i, ch in enumerate(channels_found[:5], 1):
            subs = _fmt_num(ch.get("subscriber_count", 0))
            response += f"  {i}. *{ch['title']}* — {subs} subscribers\n"

        # ── B) Where the opportunity is ──
        if gaps and clusters:
            sorted_gaps = sorted(gaps, key=lambda g: g.score, reverse=True)
            response += "\n*🎯 Where You Should Start*\n"
            async with async_session() as session:
                from nichescope.models import TopicCluster
                shown = 0
                for g in sorted_gaps:
                    if shown >= 3:
                        break
                    tc = await session.get(TopicCluster, g.topic_cluster_id)
                    if not tc:
                        continue
                    shown += 1
                    label = _opportunity_label(g.score)
                    viewers = _fmt_num(tc.avg_views)
                    competitor_count = tc.video_count

                    # Explain WHY this is an opportunity
                    if g.score >= 75:
                        reason = f"only {competitor_count} videos covering this, but they avg {viewers} views"
                    elif g.score >= 50:
                        reason = f"{competitor_count} videos in this space, avg {viewers} views — room for a fresh take"
                    else:
                        reason = f"popular topic ({viewers} avg views) but {competitor_count}+ videos already"

                    response += f"\n  {label} *{tc.label}*\n"
                    response += f"  ↳ {reason}\n"

        elif clusters:
            # No gaps computed, show trending topics
            trending = sorted(clusters, key=lambda c: c.avg_views, reverse=True)[:3]
            response += "\n*📈 Hot Topics*\n"
            for tc in trending:
                trend = {"up": "🔥 Trending up", "stable": "➡️ Steady", "down": "📉 Cooling down"}.get(tc.trend_direction, "➡️ Steady")
                response += f"  • *{tc.label}* — {_fmt_num(tc.avg_views)} avg views, {trend}\n"

        # ── C) Quick action plan ──
        response += "\n*⚡ Quick Action Plan*\n"
        if gaps:
            best_gap = sorted(gaps, key=lambda g: g.score, reverse=True)[0]
            async with async_session() as session:
                from nichescope.models import TopicCluster
                best_tc = await session.get(TopicCluster, best_gap.topic_cluster_id)
                if best_tc:
                    response += f"  1. Start with *{best_tc.label}* — lowest competition, highest upside\n"
                else:
                    response += f"  1. Pick the topic with fewest competitors\n"
        else:
            response += f"  1. Pick a trending topic from above\n"
        response += f"  2. Study the top channel's best video — make yours better\n"
        response += f"  3. Post consistently (2x/week beats 1 viral video)\n"

        # ── D) What to ask next ──
        response += (
            "\n\n💬 *Ask me anything:*\n"
            "  • _\"How much can I earn in this niche?\"_\n"
            "  • _\"What's the top channel doing differently?\"_\n"
            "  • _\"Give me content ideas\"_\n"
        )

        await msg(response, parse_mode="Markdown")

        # ── Step 6: If user asked a specific question, answer it ──
        if "?" in original_question or any(
            w in original_question.lower()
            for w in ["what", "how", "why", "show", "tell", "give", "compare", "analyze"]
        ):
            try:
                from nichescope.services.insights_engine import answer_question
                answer = await answer_question(chat_id, original_question)
                if answer and "not registered" not in answer.lower():
                    await msg(answer, parse_mode="Markdown")
            except Exception:
                logger.exception("Failed to answer initial question")

    except Exception:
        logger.exception("Auto-onboard pipeline error for chat_id=%d", chat_id)
        _onboarding_in_progress.discard(chat_id)
        await msg(
            "😅 Something went wrong during setup. Try sending your question again!",
        )
