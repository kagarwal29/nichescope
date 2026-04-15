"""Title Performance Predictor — score title variants BEFORE publishing.

NO COMPETITOR DOES THIS (pre-publish).
TubeBuddy does post-publish A/B testing. We do PRE-publish prediction.

The insight: Titles with certain patterns consistently outperform in a niche.
"5 MISTAKES..." outperforms "My thoughts on..." by 3x in cooking niches.
Numbers in titles boost CTR. Question titles drive engagement.

This service:
1. Analyzes all high-performing titles in the niche for patterns
2. Builds a feature vector from title characteristics
3. Scores new title candidates against niche-specific success patterns
4. Suggests improvements based on what works in YOUR niche
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nichescope.models import TopicCluster, Video
from nichescope.models.channel import niche_channels

logger = logging.getLogger(__name__)


@dataclass
class TitleFeatures:
    """Extracted features from a video title."""

    has_number: bool
    has_question: bool
    has_how_to: bool
    has_listicle: bool  # "X best/top/ways"
    has_emotional_word: bool  # "amazing", "insane", "worst", "best"
    has_brackets: bool  # [HONEST REVIEW]
    has_year: bool  # "in 2025"
    has_vs: bool
    word_count: int
    char_count: int
    all_caps_word_count: int


@dataclass
class TitleScore:
    """Score and analysis for a title candidate."""

    title: str
    score: float  # 0-100, predicted relative performance
    strengths: list[str]
    weaknesses: list[str]
    suggestions: list[str]
    niche_avg_score: float  # what the average title in this niche scores


EMOTIONAL_WORDS = frozenset({
    "amazing", "insane", "incredible", "worst", "best", "perfect", "ultimate",
    "shocking", "crazy", "unbelievable", "mind-blowing", "life-changing",
    "honest", "real", "truth", "secret", "hack", "mistake", "never", "always",
    "actually", "finally", "stop", "don't", "wrong", "better",
})


def extract_title_features(title: str) -> TitleFeatures:
    """Extract predictive features from a title."""
    words = title.split()
    lower = title.lower()

    return TitleFeatures(
        has_number=bool(re.search(r"\d+", title)),
        has_question=title.strip().endswith("?"),
        has_how_to=bool(re.search(r"\bhow to\b", lower)),
        has_listicle=bool(re.search(r"\d+\s+(?:best|top|ways|tips|things|mistakes|reasons|hacks)", lower)),
        has_emotional_word=bool(EMOTIONAL_WORDS & {w.lower().strip(",.!?") for w in words}),
        has_brackets=bool(re.search(r"[\[\(].+[\]\)]", title)),
        has_year=bool(re.search(r"20\d{2}", title)),
        has_vs=bool(re.search(r"\bvs\.?\b", lower)),
        word_count=len(words),
        char_count=len(title),
        all_caps_word_count=sum(1 for w in words if w.isupper() and len(w) > 1),
    )


async def build_niche_title_model(
    session: AsyncSession,
    niche_id: int,
) -> dict[str, float]:
    """Build a niche-specific title scoring model from historical data.

    Returns: feature_name → weight (correlation with views_per_day).
    """

    # Get all videos in niche
    stmt = (
        select(Video)
        .join(Video.channel)
        .join(niche_channels, niche_channels.c.channel_id == Video.channel_id)
        .where(niche_channels.c.niche_id == niche_id)
        .where(Video.views_per_day > 0)
    )
    result = await session.execute(stmt)
    videos = list(result.scalars().all())

    if len(videos) < 20:
        return {}

    # Extract features for all videos
    feature_data: list[tuple[TitleFeatures, float]] = []
    for v in videos:
        features = extract_title_features(v.title)
        feature_data.append((features, v.views_per_day))

    # Compute correlation: avg vpd when feature=True vs feature=False
    feature_names = [
        "has_number", "has_question", "has_how_to", "has_listicle",
        "has_emotional_word", "has_brackets", "has_year", "has_vs",
    ]

    weights: dict[str, float] = {}
    baseline_vpd = sum(vpd for _, vpd in feature_data) / len(feature_data)

    for fname in feature_names:
        with_feature = [vpd for f, vpd in feature_data if getattr(f, fname)]
        without_feature = [vpd for f, vpd in feature_data if not getattr(f, fname)]

        if with_feature and without_feature:
            avg_with = sum(with_feature) / len(with_feature)
            avg_without = sum(without_feature) / len(without_feature)
            weights[fname] = round(avg_with / avg_without, 2) if avg_without else 1.0
        else:
            weights[fname] = 1.0

    # Word count sweet spot
    # Group by word count buckets and find optimal range
    wc_buckets: dict[int, list[float]] = {}
    for f, vpd in feature_data:
        bucket = min(f.word_count // 3, 5)  # 0-2, 3-5, 6-8, 9-11, 12-14, 15+
        if bucket not in wc_buckets:
            wc_buckets[bucket] = []
        wc_buckets[bucket].append(vpd)

    if wc_buckets:
        best_wc_bucket = max(wc_buckets, key=lambda b: sum(wc_buckets[b]) / len(wc_buckets[b]))
        weights["optimal_word_count_bucket"] = best_wc_bucket

    return weights


async def score_title(
    session: AsyncSession,
    niche_id: int,
    title: str,
) -> TitleScore:
    """Score a title candidate against niche-specific patterns."""

    weights = await build_niche_title_model(session, niche_id)
    features = extract_title_features(title)

    if not weights:
        return TitleScore(
            title=title, score=50.0, strengths=[], weaknesses=[],
            suggestions=["Not enough data to score — add more competitor videos"],
            niche_avg_score=50.0,
        )

    # Compute score
    score = 50.0  # baseline
    strengths: list[str] = []
    weaknesses: list[str] = []
    suggestions: list[str] = []

    feature_impacts = {
        "has_number": ("Contains a number", "Add a number (e.g., '5 Ways...')"),
        "has_question": ("Question format drives curiosity", "Try framing as a question"),
        "has_how_to": ("'How to' format is proven", "Consider 'How to...' framing"),
        "has_listicle": ("Listicle format performs well", "Try 'X Best/Top...' format"),
        "has_emotional_word": ("Emotional hook word present", "Add a hook word (best, worst, secret, honest)"),
        "has_brackets": ("Bracket tag adds context", "Add [HONEST] or (2025) tag"),
    }

    for fname, (strength_msg, suggestion_msg) in feature_impacts.items():
        weight = weights.get(fname, 1.0)
        has_feature = getattr(features, fname, False)

        if has_feature and weight > 1.1:
            score += (weight - 1.0) * 20
            strengths.append(f"✅ {strength_msg} ({weight:.1f}x boost in your niche)")
        elif not has_feature and weight > 1.3:
            suggestions.append(f"💡 {suggestion_msg} — {weight:.1f}x boost in your niche")

        if has_feature and weight < 0.9:
            score -= (1.0 - weight) * 15
            weaknesses.append(f"⚠️ This pattern underperforms in your niche ({weight:.1f}x)")

    # Word count check
    optimal_bucket = weights.get("optimal_word_count_bucket", 2)
    actual_bucket = min(features.word_count // 3, 5)
    if abs(actual_bucket - optimal_bucket) > 1:
        optimal_range = f"{int(optimal_bucket) * 3 + 1}-{int(optimal_bucket) * 3 + 5}"
        suggestions.append(
            f"💡 Optimal title length in your niche: {optimal_range} words "
            f"(yours: {features.word_count})"
        )
    else:
        strengths.append(f"✅ Good title length ({features.word_count} words)")

    # Cap score
    score = max(0, min(100, score))

    return TitleScore(
        title=title,
        score=round(score, 1),
        strengths=strengths,
        weaknesses=weaknesses,
        suggestions=suggestions,
        niche_avg_score=50.0,
    )


async def compare_titles(
    session: AsyncSession,
    niche_id: int,
    titles: list[str],
) -> list[TitleScore]:
    """Score multiple title candidates and rank them."""
    scores = []
    for title in titles:
        score = await score_title(session, niche_id, title)
        scores.append(score)

    scores.sort(key=lambda s: s.score, reverse=True)
    return scores
