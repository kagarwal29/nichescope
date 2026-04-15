"""Daily gap computation job — re-clusters topics and scores gaps."""

from __future__ import annotations

import logging

from sqlalchemy import select

from nichescope.models import Niche, User, async_session
from nichescope.services.gap_analyzer import compute_gap_scores
from nichescope.services.topic_clusterer import cluster_niche_topics

logger = logging.getLogger(__name__)


async def compute_all_gaps():
    """Nightly job: re-cluster topics and recompute gap scores for all users."""
    async with async_session() as session:
        stmt = select(Niche)
        result = await session.execute(stmt)
        niches = list(result.scalars().all())

    logger.info("Computing gaps for %d niches", len(niches))

    for niche in niches:
        try:
            async with async_session() as session:
                # Step 1: Re-cluster topics
                clusters = await cluster_niche_topics(session, niche.id)
                logger.info("Niche '%s': %d clusters", niche.name, len(clusters))

                if not clusters:
                    logger.warning("Niche '%s' has no topic clusters — skipping gap computation", niche.name)
                    continue

                # Step 2: Compute gap scores for the niche owner
                user_stmt = select(User).where(User.id == niche.user_id)
                user_result = await session.execute(user_stmt)
                user = user_result.scalar_one_or_none()

                if user:
                    scores = await compute_gap_scores(session, user.id, niche.id)
                    logger.info(
                        "Niche '%s': %d gap scores computed for user %d",
                        niche.name, len(scores), user.id,
                    )

        except Exception:
            logger.exception("Failed to compute gaps for niche %d (%s)", niche.id, niche.name)

    logger.info("Gap computation complete")
