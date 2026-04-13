"""Tests for Comment Demand Mining service."""
from nichescope.services.comment_demand import REQUEST_PATTERNS, NOISE_PATTERNS, DemandSignal, _cluster_demands

def test_patterns_match():
    phrases = [
        "Can you make a video about sourdough?",
        "Please do a tutorial on knife skills!",
        "Video idea: fermented hot sauce",
        "You should try making homemade pasta",
    ]
    for phrase in phrases:
        assert any(p.search(phrase) for p in REQUEST_PATTERNS), f"Missed: {phrase!r}"

def test_noise_filters_spam():
    for spam in ["Please subscribe and like!", "First! Pin me please"]:
        assert any(p.search(spam) for p in NOISE_PATTERNS), f"Missed spam: {spam!r}"

def test_cluster_empty(): assert _cluster_demands([]) == []

def test_cluster_single():
    s = DemandSignal(raw_text="can you make bread", extracted_topic="bread baking",
                     video_title="V", video_id="a", channel_title="Ch", like_count=5)
    clusters = _cluster_demands([s])
    assert len(clusters) == 1 and clusters[0].request_count == 1
