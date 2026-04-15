"""Tests for Seasonal Calendar service."""

from nichescope.services.seasonal_calendar import (
    MONTH_NAMES,
    CalendarEntry,
    SeasonalPattern,
)


def test_month_names_length():
    """MONTH_NAMES should have 13 entries (index 0 is empty)."""
    assert len(MONTH_NAMES) == 13
    assert MONTH_NAMES[0] == ""
    assert MONTH_NAMES[1] == "January"
    assert MONTH_NAMES[12] == "December"


def test_seasonal_pattern_dataclass():
    """SeasonalPattern should store all required fields."""
    pattern = SeasonalPattern(
        topic_label="grilling",
        topic_id=1,
        monthly_index={m: 1.0 for m in range(1, 13)},
        peak_month=6,
        peak_multiplier=2.5,
        trough_month=12,
        is_seasonal=True,
        confidence=0.8,
    )
    assert pattern.topic_label == "grilling"
    assert pattern.peak_month == 6
    assert pattern.peak_multiplier == 2.5
    assert pattern.is_seasonal is True
    assert pattern.confidence == 0.8
    assert len(pattern.monthly_index) == 12


def test_calendar_entry_dataclass():
    """CalendarEntry should store all required fields."""
    entry = CalendarEntry(
        topic_label="grilling recipes",
        recommended_publish_window="May 15 — June 1",
        peak_month="June",
        peak_multiplier=2.5,
        reason="Peaks in June at 2.5x",
        urgency="upcoming",
    )
    assert entry.urgency == "upcoming"
    assert "June" in entry.peak_month
    assert entry.peak_multiplier == 2.5


def test_calendar_urgency_values():
    """Urgency should be one of the expected values."""
    valid_urgencies = {"now", "upcoming", "plan_ahead"}
    for urg in valid_urgencies:
        entry = CalendarEntry(
            topic_label="t", recommended_publish_window="w",
            peak_month="m", peak_multiplier=1.0, reason="r",
            urgency=urg,
        )
        assert entry.urgency in valid_urgencies
