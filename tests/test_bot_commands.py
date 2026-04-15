"""Tests for Telegram bot formatters."""

from nichescope.bot.formatters import format_number, trend_emoji, format_gap_insight


def test_format_number():
    assert format_number(500) == "500"
    assert format_number(1_500) == "1.5K"
    assert format_number(12_345) == "12.3K"
    assert format_number(1_500_000) == "1.5M"
    assert format_number(0) == "0"


def test_trend_emoji():
    assert trend_emoji("up") == "📈"
    assert trend_emoji("down") == "📉"
    assert trend_emoji("stable") == "➡️"
    assert trend_emoji("unknown") == ""


def test_format_gap_insight():
    gap = {
        "topic": "meal prep",
        "score": 150.5,
        "avg_views": 250000,
        "competitor_videos": 12,
        "your_videos": 0,
        "trend": "up",
        "example_videos": ["Weekly Meal Prep for Beginners", "5 Day Meal Prep"],
    }
    result = format_gap_insight(gap, 1)
    assert "meal prep" in result
    assert "150.5" in result
    assert "250.0K" in result
    assert "📈" in result
    assert "#1" not in result  # rank is shown as "1."
