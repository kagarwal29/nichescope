"""/start — Onboarding flow for new Telegram users."""

from __future__ import annotations

import asyncio
import json
import secrets

from sqlalchemy import select
from telegram import Bot, Update
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from nichescope.config import settings
from nichescope.models import Niche, User, async_session, niche_channels
from nichescope.services.channel_ingester import ingest_channel_by_handle

CHANNEL, NICHE_NAME, COMPETITORS = range(3)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome to NicheScope!*\n\n"
        "I'll help you find content gaps and track competitors.\n\n"
        "First, what's your YouTube channel? Send me your @handle.\n"
        "(e.g. @mkbhd)\n\n"
        "Or send /skip if you don't have a channel yet.",
        parse_mode="Markdown",
    )
    return CHANNEL


async def receive_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "/skip":
        context.user_data["youtube_channel_id"] = None
        await update.message.reply_text(
            "No problem! You can add your channel later.\n\n"
            "Now, name your niche (e.g. 'home cooking', 'mock interviews', 'personal finance'):"
        )
        return NICHE_NAME

    handle = text.lstrip("@")
    context.user_data["channel_handle"] = handle
    await update.message.reply_text(f"Looking up @{handle}... 🔍")

    try:
        from nichescope.services.youtube_api import youtube_api
        meta = youtube_api.get_channel_by_handle(handle)
        if meta:
            context.user_data["youtube_channel_id"] = meta["youtube_channel_id"]
            await update.message.reply_text(
                f"✅ Found: *{meta['title']}* ({meta['subscriber_count']:,} subs)\n\n"
                f"Now, name your niche (e.g. 'home cooking', 'mock interviews'):",
                parse_mode="Markdown",
            )
            return NICHE_NAME
        else:
            await update.message.reply_text("❌ Channel not found. Try again or /skip.")
            return CHANNEL
    except Exception as e:
        await update.message.reply_text(f"Error: {e}\nTry again or /skip.")
        return CHANNEL


async def receive_niche_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    niche_name = update.message.text.strip()
    context.user_data["niche_name"] = niche_name
    await update.message.reply_text(
        f"Great! Niche: *{niche_name}*\n\n"
        "Now add 1-5 competitor channels (one per line or comma-separated):\n\n"
        "```\n@channelhandle1\n@channelhandle2\n```\n\n"
        "Send /done when finished, or add handles now.",
        parse_mode="Markdown",
    )
    context.user_data["competitors"] = []
    return COMPETITORS


async def receive_competitors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "/done":
        return await finalize_onboarding(update, context)

    handles = [h.strip().lstrip("@") for h in text.replace(",", "\n").split("\n") if h.strip()]
    for handle in handles:
        if handle and handle != "/done":
            context.user_data["competitors"].append(handle)
            await update.message.reply_text(f"  ✅ Added @{handle}")

    count = len(context.user_data["competitors"])
    await update.message.reply_text(
        f"Added {count} competitor(s). Send more @handles or /done to finish."
    )
    return COMPETITORS


async def finalize_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text("⏳ Creating your account...")

    async with async_session() as session:
        existing = (await session.execute(
            select(User).where(User.telegram_chat_id == chat_id)
        )).scalar_one_or_none()

        if existing:
            await update.message.reply_text(
                f"👋 Welcome back! Account already exists.\n"
                f"API Key: `{existing.api_key}`\n\n"
                f"Use /analyze to re-run analysis, /gaps for content gaps.",
                parse_mode="Markdown",
            )
            return ConversationHandler.END

        user = User(
            telegram_chat_id=chat_id,
            youtube_channel_id=context.user_data.get("youtube_channel_id"),
            api_key=secrets.token_urlsafe(32),
        )
        session.add(user)
        await session.flush()

        niche = Niche(
            user_id=user.id,
            name=context.user_data.get("niche_name", "My Niche"),
            seed_keywords=json.dumps([]),
        )
        session.add(niche)
        await session.flush()

        await session.commit()
        user_id = user.id
        niche_id = niche.id
        api_key = user.api_key

    competitors = context.user_data.get("competitors", [])
    niche_name = context.user_data.get("niche_name", "My Niche")

    await update.message.reply_text(
        f"✅ *Account created!*\n\n"
        f"• Niche: *{niche_name}*\n"
        f"• API Key: `{api_key}`\n\n"
        f"Now ingesting {len(competitors)} competitor channel(s) in the background.\n"
        f"I'll send you a message when insights are ready (usually 1-3 min) 🚀",
        parse_mode="Markdown",
    )

    # ── Run everything in background — bot responds instantly ──
    asyncio.create_task(
        _background_ingest_and_analyze(chat_id, user_id, niche_id, niche_name, competitors)
    )

    return ConversationHandler.END


async def _background_ingest_and_analyze(
    chat_id: int,
    user_id: int,
    niche_id: int,
    niche_name: str,
    competitors: list[str],
):
    """Background task: ingest channels then run analysis. Sends progress via bot."""
    bot = Bot(token=settings.telegram_bot_token)

    async def msg(text, **kwargs):
        try:
            await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to send msg: %s", e)

    # Step 1: Ingest each competitor channel
    ingested_count = 0
    for handle in competitors:
        try:
            await msg(f"📡 Fetching videos from @{handle}...")
            async with async_session() as session:
                channel = await ingest_channel_by_handle(session, handle)
                # Count actual videos stored
                from sqlalchemy import func, select as sa_select
                from nichescope.models import Video
                count_result = await session.execute(
                    sa_select(func.count(Video.id)).where(Video.channel_id == channel.id)
                )
                actual_video_count = count_result.scalar() or 0
                # Associate channel with niche
                from nichescope.models import niche_channels as nc_table
                await session.execute(
                    nc_table.insert().values(niche_id=niche_id, channel_id=channel.id)
                )
                await session.commit()

            await msg(f"  📥 @{handle}: {actual_video_count} videos stored ✓")
            ingested_count += 1
        except Exception as e:
            await msg(f"  ⚠️ @{handle} failed: {e}")

    if ingested_count == 0:
        await msg(
            "❌ No channels were ingested successfully.\n"
            "Check the handles are correct and try /analyze to retry."
        )
        return

    # Step 2: Topic clustering + gap analysis
    await msg("🧠 Clustering topics across competitor videos...")
    try:
        from nichescope.services.topic_clusterer import cluster_niche_topics
        async with async_session() as session:
            clusters = await cluster_niche_topics(session, niche_id)
        await msg(f"  📊 Discovered {len(clusters)} topic clusters")
    except Exception as e:
        await msg(f"  ⚠️ Clustering failed: {e}\nRun /analyze to retry.")
        return

    if clusters:
        await msg("🎯 Computing content gap scores...")
        try:
            from nichescope.services.gap_analyzer import compute_gap_scores
            async with async_session() as session:
                gaps = await compute_gap_scores(session, user_id, niche_id)
            top = sorted(gaps, key=lambda g: g.score, reverse=True)[:3]
            top_labels = []
            async with async_session() as session:
                from nichescope.models import TopicCluster
                for g in top:
                    tc = await session.get(TopicCluster, g.topic_cluster_id)
                    if tc:
                        top_labels.append(f"  • {tc.label} (score: {g.score:.0f})")
            preview = "\n".join(top_labels) if top_labels else "  (run /gaps to see)"
            await msg(
                f"✅ *Analysis complete!*\n\n"
                f"📊 {len(clusters)} topic clusters\n"
                f"🎯 {len(gaps)} content gap opportunities\n\n"
                f"*Top gaps:*\n{preview}\n\n"
                f"Try these commands:\n"
                f"/gaps — Full content gap analysis\n"
                f"/brief — Daily briefing\n"
                f"/trending — Hot topics\n"
                f"/rival @handle — Competitor deep-dive",
                parse_mode="Markdown",
            )
        except Exception as e:
            await msg(f"⚠️ Gap scoring failed: {e}\nBut clustering worked — try /gaps")
    else:
        await msg(
            "⚠️ Not enough video data to cluster topics.\n"
            "Try adding more competitors with /analyze."
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Onboarding cancelled. Run /start to try again.")
    return ConversationHandler.END


def get_onboarding_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHANNEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_channel),
                CommandHandler("skip", receive_channel),
            ],
            NICHE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_niche_name)],
            COMPETITORS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_competitors),
                CommandHandler("done", finalize_onboarding),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
