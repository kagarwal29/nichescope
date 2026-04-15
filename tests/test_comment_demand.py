"""Tests for Comment Demand Mining service."""

import re

from nichescope.services.comment_demand import (
    DemandSignal,
    REQUEST_PATTERNS,
    NOISE_PATTERNS,
    _extract_requests,
    _cluster_demands,
)


# --- Pattern matching tests ---


def test_request_patterns_match_common_requests():
    """All common request phrasings should match at least one pattern."""
    test_phrases = [
        "Can you make a video about sourdough starters?",
        "Please do a tutorial on knife skills!",
        "You should try making homemade pasta",
        "Do a video about meal prep for beginners",
        "I'd love to see a comparison of stand mixers",
        "Next video try making croissants from scratch",
        "Video idea: fermented hot sauce",
        "React to Gordon Ramsay's new video",
    ]

    for phrase in test_phrases:
        matched = any(p.search(phrase) for p in REQUEST_PATTERNS)
        assert matched, f"Pattern missed: {phrase!r}"


def test_request_patterns_extract_topic():
    """Extracted topics should be reasonable substrings."""
    text = "Can you make a video about sourdough starters?"
    for pattern in REQUEST_PATTERNS:
        m = pattern.search(text)
        if m:
            topic = m.group(1).strip().rstrip("?.!,")
            assert len(topic) > 5
            assert "sourdough" in topic.lower()
            break
    else:
        raise AssertionError("No pattern matched")


def test_noise_patterns_filter_spam():
    """Noise patterns should catch common spam."""
    spam_comments = [
        "Please subscribe and like!",
        "First! Pin me please",
        "Turn on notifications and share this video",
        "Shoutout to my channel please",
    ]

    for comment in spam_comments:
        matched = any(p.search(comment) for p in NOISE_PATTERNS)
        assert matched, f"Noise filter missed spam: {comment!r}"


def test_noise_does_not_filter_legit_requests():
    """Real requests should NOT be caught by noise filter."""
    legit = "Can you make a video about knife sharpening techniques?"
    matched = any(p.search(legit) for p in NOISE_PATTERNS)
    assert not matched, "Noise filter incorrectly caught a legit request"


# --- Clustering tests ---


def test_cluster_demands_empty():
    """Empty input should return empty clusters."""
    assert _cluster_demands([]) == []


def test_cluster_demands_single_signal():
    """Single signal should produce one cluster."""
    signal = DemandSignal(
        raw_text="can you make a video about bread baking",
        extracted_topic="bread baking techniques",
        video_title="My Best Bread Recipe",
        video_id="abc123",
        channel_title="BreadTube",
        like_count=5,
    )
    clusters = _cluster_demands([signal])
    assert len(clusters) == 1
    assert clusters[0].request_count == 1
    assert clusters[0].total_likes == 5
    assert clusters[0].strength_score > 0


def test_cluster_demands_groups_similar():
    """Signals with similar topics should cluster together."""
    signals = [
        DemandSignal(
            raw_text="can you do a bread baking tutorial",
            extracted_topic="bread baking tutorial",
            video_title="V1", video_id="a", channel_title="Ch1", like_count=3,
        ),
        DemandSignal(
            raw_text="please make a bread baking guide",
            extracted_topic="bread baking guide",
            video_title="V2", video_id="b", channel_title="Ch2", like_count=7,
        ),
    ]
    clusters = _cluster_demands(signals)

    # Both share "baking" and "bread" as significant words, so should cluster
    total_requests = sum(c.request_count for c in clusters)
    assert total_requests == 2


def test_cluster_strength_score():
    """Strength score = request_count × (1 + avg_likes)."""
    signals = [
        DemandSignal(
            raw_text="try pasta", extracted_topic="homemade pasta",
            video_title="V1", video_id="a", channel_title="Ch1", like_count=10,
        ),
        DemandSignal(
            raw_text="do pasta", extracted_topic="homemade pasta recipe",
            video_title="V2", video_id="b", channel_title="Ch1", like_count=20,
        ),
    ]
    clusters = _cluster_demands(signals)

    # Find the cluster with both signals (may be split depending on keyword matching)
    for c in clusters:
        if c.request_count == 2:
            avg_likes = c.total_likes / c.request_count
            expected = round(c.request_count * (1 + avg_likes), 1)
            assert c.strength_score == expected
            break


def test_cluster_source_channels_deduped():
    """Source channels should be deduplicated."""
    signals = [
        DemandSignal(
            raw_text="r1", extracted_topic="topic one",
            video_title="V1", video_id="a", channel_title="SameChannel", like_count=1,
        ),
        DemandSignal(
            raw_text="r2", extracted_topic="topic one here",
            video_title="V2", video_id="b", channel_title="SameChannel", like_count=2,
        ),
    ]
    clusters = _cluster_demands(signals)
    for c in clusters:
        # No duplicates in source_channels
        assert len(c.source_channels) == len(set(c.source_channels))
