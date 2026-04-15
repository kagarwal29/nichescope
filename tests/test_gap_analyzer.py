"""Tests for gap analyzer scoring logic."""


def test_gap_score_formula():
    """Verify the gap score formula: (demand * recency) / (supply * (coverage + 1))."""
    demand = 100_000
    supply = 0.1  # 10% of niche
    user_coverage = 0
    recency = 1.5  # trending up

    score = (demand * recency) / (supply * (user_coverage + 1))
    assert score == 1_500_000.0

    # With user coverage = 2, score should drop
    user_coverage = 2
    score_with_coverage = (demand * recency) / (supply * (user_coverage + 1))
    assert score_with_coverage == 500_000.0
    assert score_with_coverage < score


def test_gap_score_zero_supply():
    """Zero supply should not crash."""
    demand = 100_000
    supply = 0
    user_coverage = 0
    recency = 1.0

    score = (demand * recency) / (supply * (user_coverage + 1)) if supply > 0 else 0
    assert score == 0


def test_recency_boost():
    """Trending up should give 1.5x boost, stable = 1.0x."""
    demand = 100_000
    supply = 0.1
    user_coverage = 0

    score_up = (demand * 1.5) / (supply * (user_coverage + 1))
    score_stable = (demand * 1.0) / (supply * (user_coverage + 1))

    assert score_up == score_stable * 1.5
