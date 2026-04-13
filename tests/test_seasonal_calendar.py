"""Tests for Seasonal Calendar service."""
from nichescope.services.seasonal_calendar import MONTH_NAMES, SeasonalPattern, CalendarEntry

def test_month_names(): assert len(MONTH_NAMES) == 13 and MONTH_NAMES[1] == "January"
def test_seasonal_pattern():
    p = SeasonalPattern(topic_label="grilling", topic_id=1,
        monthly_index={m: 1.0 for m in range(1,13)},
        peak_month=6, peak_multiplier=2.5, trough_month=12, is_seasonal=True, confidence=0.8)
    assert p.is_seasonal and p.peak_multiplier == 2.5
def test_calendar_entry():
    e = CalendarEntry(topic_label="grilling", recommended_publish_window="May",
        peak_month="June", peak_multiplier=2.5, reason="Peaks in June", urgency="upcoming")
    assert e.urgency == "upcoming"
