"""Topic clustering engine — TF-IDF + KMeans over video titles/descriptions."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nichescope.models import Niche, TopicCluster, Video
from nichescope.models.channel import niche_channels

logger = logging.getLogger(__name__)

_EXTRA_STOPS = frozenset({
    "video", "recipe", "recipes", "how", "make", "easy", "best", "top",
    "new", "2024", "2025", "2026", "tutorial", "tips", "review", "day",
    "vs", "try", "trying", "first", "time", "ever", "ultimate", "asmr",
})

_executor = ThreadPoolExecutor(max_workers=2)


def _fit_clusters(corpus: list, max_clusters: int):
    """CPU-bound: TF-IDF + KMeans. Runs in ThreadPoolExecutor so event loop stays free."""
    vectorizer = TfidfVectorizer(
        max_features=3000, ngram_range=(1, 2),
        stop_words="english", min_df=2, max_df=0.8,
    )
    tfidf_matrix = vectorizer.fit_transform(corpus)
    feature_names = vectorizer.get_feature_names_out()
    n_samples = tfidf_matrix.shape[0]
    k = min(max_clusters, max(3, int(math.sqrt(n_samples / 2))))
    logger.info("KMeans k=%d on %d docs", k, n_samples)
    kmeans = KMeans(n_clusters=k, random_state=42, n_init=10, max_iter=300)
    labels = kmeans.fit_predict(tfidf_matrix)
    return kmeans, labels, feature_names, k


async def cluster_niche_topics(
    session: AsyncSession,
    niche_id: int,
    max_clusters: int = 40,
    lookback_days: int = 3650,   # 10 years — effectively all videos
) -> list:
    niche = await session.get(Niche, niche_id)
    if not niche:
        raise ValueError(f"Niche {niche_id} not found")

    # ── Load ALL videos for channels in this niche (no date filter — include everything) ──
    # Use a subquery to avoid ORM relationship join issues
    channel_ids_subq = (
        select(niche_channels.c.channel_id)
        .where(niche_channels.c.niche_id == niche_id)
        .scalar_subquery()
    )
    stmt = select(Video).where(Video.channel_id.in_(channel_ids_subq))
    result = await session.execute(stmt)
    videos = list(result.scalars().all())

    logger.info(
        "Niche '%s' (id=%d): found %d videos across competitor channels",
        niche.name, niche_id, len(videos)
    )

    if len(videos) < 5:   # Lowered threshold from 10 to 5
        logger.warning("Not enough videos to cluster: %d (need ≥5)", len(videos))
        return []

    # ── Build text corpus ──
    corpus = [f"{v.title} {(v.description or '')[:200]}".lower() for v in videos]

    # ── Run ML in thread pool (non-blocking) ──
    loop = asyncio.get_event_loop()
    kmeans, labels, feature_names, k = await loop.run_in_executor(
        _executor, _fit_clusters, corpus, max_clusters
    )

    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)
    ninety_days_ago = now - timedelta(days=90)

    # ── Delete old clusters ──
    old_stmt = select(TopicCluster).where(TopicCluster.niche_id == niche_id)
    for old in (await session.execute(old_stmt)).scalars().all():
        await session.delete(old)
    await session.flush()

    # ── Create new clusters ──
    clusters = []
    for cluster_idx in range(k):
        mask = labels == cluster_idx
        cluster_videos = [v for v, m in zip(videos, mask) if m]
        if not cluster_videos:
            continue

        centroid = kmeans.cluster_centers_[cluster_idx]
        top_term_indices = centroid.argsort()[-5:][::-1]
        top_terms = [
            feature_names[i]
            for i in top_term_indices
            if feature_names[i] not in _EXTRA_STOPS
        ][:3]
        label = " + ".join(top_terms) if top_terms else f"topic_{cluster_idx}"

        views = [v.view_count for v in cluster_videos]
        avg_views = sum(views) / len(views) if views else 0

        def safe_views_in_window(window_start):
            recent = []
            for v in cluster_videos:
                if v.published_at is None:
                    continue
                pub = v.published_at
                # Handle both timezone-aware and naive datetimes
                if pub.tzinfo is not None:
                    start = window_start
                else:
                    start = window_start.replace(tzinfo=None)
                if pub >= start:
                    recent.append(v.view_count)
            return sum(recent) / len(recent) if recent else 0

        avg_views_30d = safe_views_in_window(thirty_days_ago)
        avg_views_90d = safe_views_in_window(ninety_days_ago)

        if avg_views_90d > 0 and avg_views_30d > avg_views_90d * 1.2:
            trend = "up"
        elif avg_views_90d > 0 and avg_views_30d < avg_views_90d * 0.8:
            trend = "down"
        else:
            trend = "stable"

        tc = TopicCluster(
            niche_id=niche_id, label=label, keywords=json.dumps(top_terms),
            video_count=len(cluster_videos), avg_views=avg_views,
            avg_views_30d=avg_views_30d, trend_direction=trend, last_computed=now,
        )
        session.add(tc)
        await session.flush()

        for v, m in zip(videos, mask):
            if m:
                v.topic_cluster_id = tc.id

        clusters.append(tc)

    await session.commit()
    logger.info("Created %d clusters for niche '%s'", len(clusters), niche.name)
    return clusters
