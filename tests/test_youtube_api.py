"""Tests for YouTube API client."""

from nichescope.services.youtube_api import YouTubeAPI


def test_parse_duration():
    assert YouTubeAPI._parse_duration("PT1H2M3S") == 3723
    assert YouTubeAPI._parse_duration("PT10M30S") == 630
    assert YouTubeAPI._parse_duration("PT5M") == 300
    assert YouTubeAPI._parse_duration("PT30S") == 30
    assert YouTubeAPI._parse_duration("PT0S") == 0
    assert YouTubeAPI._parse_duration("PT1H") == 3600
    assert YouTubeAPI._parse_duration("") == 0


def test_quota_tracking():
    api = YouTubeAPI.__new__(YouTubeAPI)
    api._quota_used = 0
    api._service = None  # won't make real calls

    from nichescope.config import settings
    daily = settings.youtube_daily_quota

    assert api.quota_remaining == daily
