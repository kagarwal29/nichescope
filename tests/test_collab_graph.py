"""Tests for Collaboration Graph service."""
from nichescope.services.collab_graph import COLLAB_PATTERNS, CollabOpportunity

def test_detects_feat():
    for title in ["Best Pasta feat. Gordon Ramsay", "Pizza ft. Adam Ragusea", "Cook x BabaBorquez"]:
        assert any(p.search(title) for p in COLLAB_PATTERNS), f"Missed: {title!r}"

def test_opportunity():
    o = CollabOpportunity(channel_title="Tech", handle="tech", subscriber_count=100_000,
        topic_overlap_score=0.65, audience_overlap_estimate="medium",
        existing_collabs=2, potential_reach=60_000, shared_topics=["tech", "gadgets"], reason="Good")
    assert o.potential_reach == 60_000 and len(o.shared_topics) == 2
