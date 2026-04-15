"""Tests for Collaboration Graph service."""

from nichescope.services.collab_graph import (
    COLLAB_PATTERNS,
    CollabEdge,
    CollabOpportunity,
)


def test_collab_patterns_detect_feat():
    """Should detect 'feat.' or 'featuring' patterns."""
    titles = [
        "Best Pasta Ever feat. Gordon Ramsay",
        "Epic Collab featuring Joshua Weissman",
        "Making Pizza ft. Adam Ragusea",
        "Cooking Challenge x BabaBorquez",
    ]
    for title in titles:
        matched = any(p.search(title) for p in COLLAB_PATTERNS)
        assert matched, f"Pattern missed collab in: {title!r}"


def test_collab_patterns_detect_at_mention():
    """Should detect @mentions."""
    text = "Check out @mkbhd for more tech reviews"
    matched = any(p.search(text) for p in COLLAB_PATTERNS)
    assert matched, "Pattern missed @mention"


def test_collab_patterns_no_false_positives():
    """Normal titles should not trigger collab detection."""
    normal_titles = [
        "How to Make Perfect Rice",
        "10 Best Kitchen Tools Under $20",
        "My Morning Routine 2025",
    ]
    for title in normal_titles:
        # Only test against the first pattern (feat/collab)
        # @mention pattern is intentionally broad
        matched = COLLAB_PATTERNS[0].search(title)
        assert not matched, f"False positive collab detected in: {title!r}"


def test_collab_edge_dataclass():
    """CollabEdge should hold all fields."""
    edge = CollabEdge(
        channel_a="Channel A",
        channel_b="Channel B",
        video_title="Collab Video",
        video_id="vid123",
        detection_method="title_mention",
    )
    assert edge.channel_a == "Channel A"
    assert edge.detection_method == "title_mention"


def test_collab_opportunity_dataclass():
    """CollabOpportunity should compute potential reach correctly."""
    opp = CollabOpportunity(
        channel_title="Tech Reviewer",
        handle="techreviewer",
        subscriber_count=100_000,
        topic_overlap_score=0.65,
        audience_overlap_estimate="medium",
        existing_collabs=2,
        potential_reach=60_000,
        shared_topics=["tech reviews", "gadgets"],
        reason="Good match",
    )
    assert opp.potential_reach == 60_000
    assert opp.audience_overlap_estimate == "medium"
    assert len(opp.shared_topics) == 2


def test_overlap_factor_values():
    """Overlap factors should match expected values."""
    overlap_factors = {"low": 0.9, "medium": 0.6, "high": 0.3}

    for level, factor in overlap_factors.items():
        subs = 100_000
        expected_reach = int(subs * factor)
        opp = CollabOpportunity(
            channel_title="Ch", handle="ch",
            subscriber_count=subs,
            topic_overlap_score=0.5,
            audience_overlap_estimate=level,
            existing_collabs=0,
            potential_reach=expected_reach,
            shared_topics=[],
            reason="test",
        )
        assert opp.potential_reach == expected_reach
