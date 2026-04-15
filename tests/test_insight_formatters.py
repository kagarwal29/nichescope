"""Tests for forward-looking feature formatters."""

from nichescope.bot.formatters import (
    format_demands,
    format_calendar,
    format_collabs,
    format_format_insights,
    format_title_scores,
    urgency_emoji,
)


def test_urgency_emoji():
    assert urgency_emoji("now") == "🔴"
    assert urgency_emoji("upcoming") == "🟡"
    assert urgency_emoji("plan_ahead") == "🟢"
    assert urgency_emoji("unknown") == "⚪"


def test_format_demands_empty():
    result = format_demands("cooking", [])
    assert "Audience Demands" in result
    assert "No demand signals" in result


def test_format_calendar_empty():
    result = format_calendar("cooking", [])
    assert "Content Calendar" in result
    assert "No seasonal patterns" in result


def test_format_collabs_empty():
    result = format_collabs("cooking", [])
    assert "Collab Opportunities" in result
    assert "No collaboration data" in result


def test_format_format_insights_empty():
    result = format_format_insights("cooking", [])
    assert "Format Intelligence" in result
    assert "Not enough data" in result


def test_format_title_scores_empty():
    result = format_title_scores("cooking", [])
    assert "Title Scorer" in result
    assert "No titles" in result
