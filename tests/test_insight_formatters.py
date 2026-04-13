"""Tests for forward-looking formatters."""
from nichescope.bot.formatters import (
    format_demands, format_calendar, format_collabs,
    format_format_insights, format_title_scores, urgency_emoji,
)
def test_urgency(): assert urgency_emoji("now") == "🔴"; assert urgency_emoji("plan_ahead") == "🟢"
def test_demands_empty(): assert "No demand signals" in format_demands("cooking", [])
def test_calendar_empty(): assert "No seasonal patterns" in format_calendar("cooking", [])
def test_collabs_empty(): assert "No collaboration data" in format_collabs("cooking", [])
def test_formats_empty(): assert "Not enough data" in format_format_insights("cooking", [])
def test_titles_empty(): assert "No titles" in format_title_scores("cooking", [])
