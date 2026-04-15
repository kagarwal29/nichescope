"""/analyze — Re-run the analysis pipeline on demand."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from sqlalchemy import select

from nichescope.models import Niche, User, async_session
from nichescope.services.gap_analyzer import compute_gap_scores
from nichescope.services.topic_clusterer import cluster_niche_topics


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    try:
        async with async_session() as session:
            stmt = select(User).where(User.telegram_chat_id == chat_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                await update.message.reply_text("Not registered. Run /start first!")
                return

            niche_stmt = select(Niche).where(Niche.user_id == user.id).limit(1)
            niche_result = await session.execute(niche_stmt)
            niche = niche_result.scalar_one_or_none()

            if not niche:
                await update.message.reply_text("No niche configured. Run /start to set up.")
                return

            user_id = user.id
            niche_id = niche.id
            niche_name = niche.name

        await update.message.reply_text(
            f"🔄 *Re-analyzing niche: {niche_name}*\nThis may take a minute...",
            parse_mode="Markdown",
        )

        # Step 1: Topic clustering
        await update.message.reply_text("🧠 Step 1/2: Clustering topics...")
        try:
            async with async_session() as session:
                clusters = await cluster_niche_topics(session, niche_id)
                await update.message.reply_text(f"  📊 Found {len(clusters)} topic clusters")
        except Exception as e:
            await update.message.reply_text(f"  ❌ Clustering failed: {e}")
            import logging
            logging.exception("Clustering error")
            return

        # Step 2: Gap analysis
        if clusters:
            await update.message.reply_text("🎯 Step 2/2: Computing gaps...")
            try:
                async with async_session() as session:
                    gaps = await compute_gap_scores(session, user_id, niche_id)
                    top_gaps = sorted(gaps, key=lambda g: g.score, reverse=True)[:5]

                    if top_gaps:
                        from nichescope.models import TopicCluster
                        gap_lines = []
                        for g in top_gaps:
                            tc_stmt = select(TopicCluster).where(TopicCluster.id == g.topic_cluster_id)
                            tc_result = await session.execute(tc_stmt)
                            tc = tc_result.scalar_one_or_none()
                            label = tc.label if tc else f"Cluster #{g.topic_cluster_id}"
                            gap_lines.append(f"  • *{label}* — score {g.score:.0f}")

                        await update.message.reply_text(
                            f"✅ *Analysis complete!*\n\n"
                            f"Found {len(gaps)} gap opportunities.\n\n"
                            f"*Top 5:*\n" + "\n".join(gap_lines) + "\n\n"
                            f"Run /gaps for details, /brief for your briefing.",
                            parse_mode="Markdown",
                        )
                    else:
                        await update.message.reply_text("✅ Analysis complete! Run /gaps to see results.")
            except Exception as e:
                await update.message.reply_text(f"  ❌ Gap analysis failed: {e}")
                import logging
                logging.exception("Gap analysis error")
                return
        else:
            await update.message.reply_text(
                "⚠️ Not enough videos to cluster. Add more competitors with /start."
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Analysis failed: {e}")
        import logging
        logging.exception("Analyze command error")
