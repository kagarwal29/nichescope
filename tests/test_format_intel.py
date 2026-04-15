"""Tests for Format Intelligence service."""

from nichescope.services.format_intel import (
    classify_format,
    classify_duration,
    DURATION_BUCKETS,
    FORMAT_CLASSIFIERS,
    FormatInsight,
    FormatProfile,
)


# --- Format classification tests ---


def test_classify_format_tutorial():
    assert classify_format("How to Make Sourdough Bread") == "tutorial"
    assert classify_format("Step by Step Guide to Pasta") == "tutorial"
    assert classify_format("Learn Python in 10 Minutes") == "tutorial"
    assert classify_format("Beginner's Guide to Baking") == "tutorial"


def test_classify_format_listicle():
    assert classify_format("10 Best Kitchen Gadgets") == "listicle"
    assert classify_format("5 Top Tips for Meal Prep") == "listicle"
    assert classify_format("7 Mistakes Every Cook Makes") == "listicle"


def test_classify_format_review():
    assert classify_format("iPhone 16 Honest Review") == "review"
    assert classify_format("Unboxing the New MacBook Pro") == "review"
    assert classify_format("Is This Stand Mixer Worth It?") == "review"


def test_classify_format_challenge():
    assert classify_format("$1 vs $1000 Steak Challenge") == "challenge"
    assert classify_format("Blind Taste Test: Premium vs Budget") == "challenge"
    assert classify_format("Home Cook vs Professional Chef") == "challenge"


def test_classify_format_vlog():
    assert classify_format("A Day in My Life as a Chef") == "vlog"
    assert classify_format("What I Eat in a Week") == "vlog"
    assert classify_format("My Morning Routine 2025") == "vlog"


def test_classify_format_reaction():
    assert classify_format("Reacting to TikTok Recipes") == "reaction"
    assert classify_format("Watching Gordon Ramsay Cook") == "reaction"


def test_classify_format_other():
    assert classify_format("Random Things Happening") == "other"
    assert classify_format("") == "other"


# --- Duration classification tests ---


def test_classify_duration_short():
    assert classify_duration(0) == "short (<5m)"
    assert classify_duration(120) == "short (<5m)"
    assert classify_duration(299) == "short (<5m)"


def test_classify_duration_medium():
    assert classify_duration(300) == "medium (5-15m)"
    assert classify_duration(600) == "medium (5-15m)"
    assert classify_duration(899) == "medium (5-15m)"


def test_classify_duration_long():
    assert classify_duration(900) == "long (15-30m)"
    assert classify_duration(1500) == "long (15-30m)"
    assert classify_duration(1799) == "long (15-30m)"


def test_classify_duration_extra_long():
    assert classify_duration(1800) == "extra_long (30m+)"
    assert classify_duration(3600) == "extra_long (30m+)"
    assert classify_duration(99999) == "extra_long (30m+)"


# --- Duration buckets config test ---


def test_duration_buckets_are_contiguous():
    """Duration buckets should cover 0 to 999999 without gaps."""
    assert DURATION_BUCKETS[0][1] == 0  # starts at 0
    for i in range(len(DURATION_BUCKETS) - 1):
        _, _, high = DURATION_BUCKETS[i]
        _, low, _ = DURATION_BUCKETS[i + 1]
        assert high == low, f"Gap between buckets at index {i}: {high} != {low}"


# --- Format classifiers config test ---


def test_format_classifiers_are_compiled_regex():
    """All format classifiers should be compiled regex patterns."""
    import re
    for name, pattern in FORMAT_CLASSIFIERS.items():
        assert isinstance(pattern, re.Pattern), f"{name} is not a compiled regex"


def test_format_insight_multiplier():
    """FormatInsight multiplier should reflect best/worst ratio."""
    insight = FormatInsight(
        topic_label="cooking",
        best_format="tutorial",
        best_duration="medium (5-15m)",
        best_avg_views=100_000,
        worst_format="vlog",
        worst_avg_views=25_000,
        multiplier=4.0,
        recommendation="tutorials get 4x more views",
        profiles=[],
    )
    assert insight.multiplier == 4.0
    assert insight.best_avg_views / insight.worst_avg_views == 4.0
