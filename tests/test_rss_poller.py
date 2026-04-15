"""Tests for RSS poller."""

from nichescope.services.rss_poller import poll_channel_rss


def test_rss_returns_list():
    """RSS poll should return a list (even if empty for invalid channel)."""
    result = poll_channel_rss("UC_nonexistent_channel_12345")
    assert isinstance(result, list)


def test_rss_real_channel():
    """Smoke test: poll a real YouTube channel's RSS feed."""
    # Adam Ragusea's channel — stable, always has content
    result = poll_channel_rss("UCVHFbqXqoYvEWM1Ddxl0QDg")
    assert isinstance(result, list)
    if result:  # May fail in CI without network
        video = result[0]
        assert "youtube_video_id" in video
        assert "title" in video
        assert "published_at" in video
        assert len(video["youtube_video_id"]) > 0
