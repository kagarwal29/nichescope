"""YouTube Data API v3 client — quota-aware, batch-optimized."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from googleapiclient.discovery import build

from nichescope.config import settings

logger = logging.getLogger(__name__)

QUOTA_COSTS = {
    "search.list": 100,
    "videos.list": 1,
    "channels.list": 1,
    "playlistItems.list": 1,
    "commentThreads.list": 1,
}


class QuotaExhaustedError(Exception):
    pass


class YouTubeAPI:
    def __init__(self):
        self._service = build("youtube", "v3", developerKey=settings.youtube_api_key)
        self._quota_used: int = 0

    @property
    def quota_remaining(self) -> int:
        return settings.youtube_daily_quota - self._quota_used

    def _charge(self, operation: str, n: int = 1) -> None:
        cost = QUOTA_COSTS.get(operation, 1) * n
        if self._quota_used + cost > settings.youtube_daily_quota:
            raise QuotaExhaustedError(
                f"Would exceed daily quota: {self._quota_used}+{cost} > {settings.youtube_daily_quota}"
            )
        self._quota_used += cost
        logger.debug("Quota: %d / %d (charged %d for %s)", self._quota_used, settings.youtube_daily_quota, cost, operation)

    def get_channel_by_id(self, channel_id: str) -> dict | None:
        self._charge("channels.list")
        resp = (
            self._service.channels()
            .list(part="snippet,statistics,contentDetails", id=channel_id)
            .execute()
        )
        items = resp.get("items", [])
        return self._parse_channel(items[0]) if items else None

    def get_channel_by_handle(self, handle: str) -> dict | None:
        clean = handle.lstrip("@")
        self._charge("channels.list")
        resp = (
            self._service.channels()
            .list(part="snippet,statistics,contentDetails", forHandle=clean)
            .execute()
        )
        items = resp.get("items", [])
        return self._parse_channel(items[0]) if items else None

    def search_channel(self, query: str) -> dict | None:
        self._charge("search.list")
        resp = (
            self._service.search()
            .list(part="snippet", q=query, type="channel", maxResults=1)
            .execute()
        )
        items = resp.get("items", [])
        if not items:
            return None
        channel_id = items[0]["snippet"]["channelId"]
        return self.get_channel_by_id(channel_id)

    def search_channels(self, query: str, max_results: int = 5) -> list[dict]:
        self._charge("search.list")
        resp = (
            self._service.search()
            .list(part="snippet", q=query, type="channel", maxResults=max_results)
            .execute()
        )
        channels = []
        for item in resp.get("items", []):
            channel_id = item["snippet"]["channelId"]
            try:
                ch_data = self.get_channel_by_id(channel_id)
                if ch_data:
                    channels.append(ch_data)
            except Exception as e:
                logger.warning("Failed to fetch channel %s: %s", channel_id, e)
        return channels

    def search_channels_by_videos(self, query: str, max_videos: int = 25) -> list[dict]:
        """Find channels that actually produce content in a niche by searching
        for VIDEOS first, then extracting the unique channels."""
        self._charge("search.list")
        resp = (
            self._service.search()
            .list(
                part="snippet",
                q=query,
                type="video",
                maxResults=max_videos,
                relevanceLanguage="en",
                order="relevance",
            )
            .execute()
        )
        seen_channel_ids: set[str] = set()
        ordered_channel_ids: list[str] = []
        for item in resp.get("items", []):
            ch_id = item["snippet"]["channelId"]
            if ch_id not in seen_channel_ids:
                seen_channel_ids.add(ch_id)
                ordered_channel_ids.append(ch_id)
        channels: list[dict] = []
        for ch_id in ordered_channel_ids:
            try:
                ch_data = self.get_channel_by_id(ch_id)
                if ch_data:
                    channels.append(ch_data)
            except Exception as e:
                logger.warning("Failed to fetch channel %s: %s", ch_id, e)
        return channels

    def get_channel_videos_sample(self, channel_id: str, max_results: int = 10) -> list[str]:
        """Get recent video titles from a channel for relevance matching."""
        ch_data = self.get_channel_by_id(channel_id)
        if not ch_data or not ch_data.get("uploads_playlist_id"):
            return []
        self._charge("playlistItems.list")
        resp = (
            self._service.playlistItems()
            .list(
                part="snippet",
                playlistId=ch_data["uploads_playlist_id"],
                maxResults=max_results,
            )
            .execute()
        )
        return [
            item["snippet"].get("title", "")
            for item in resp.get("items", [])
            if item["snippet"].get("title")
        ]

    def _parse_channel(self, item: dict) -> dict:
        stats = item.get("statistics", {})
        content = item.get("contentDetails", {})
        snippet = item.get("snippet", {})
        return {
            "youtube_channel_id": item["id"],
            "title": snippet.get("title", ""),
            "handle": snippet.get("customUrl", ""),
            "subscriber_count": int(stats.get("subscriberCount", 0)),
            "video_count": int(stats.get("videoCount", 0)),
            "thumbnail_url": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
            "uploads_playlist_id": content.get("relatedPlaylists", {}).get("uploads"),
        }

    def get_uploads(self, uploads_playlist_id: str, max_results: int = 200) -> list[dict]:
        video_ids: list[str] = []
        page_token = None
        while len(video_ids) < max_results:
            self._charge("playlistItems.list")
            resp = (
                self._service.playlistItems()
                .list(
                    part="contentDetails",
                    playlistId=uploads_playlist_id,
                    maxResults=min(50, max_results - len(video_ids)),
                    pageToken=page_token,
                )
                .execute()
            )
            for item in resp.get("items", []):
                video_ids.append(item["contentDetails"]["videoId"])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return self.get_videos_batch(video_ids)

    def get_videos_batch(self, video_ids: list[str]) -> list[dict]:
        results: list[dict] = []
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i : i + 50]
            self._charge("videos.list")
            resp = (
                self._service.videos()
                .list(part="snippet,statistics,contentDetails", id=",".join(batch))
                .execute()
            )
            for item in resp.get("items", []):
                results.append(self._parse_video(item))
        return results

    def _parse_video(self, item: dict) -> dict:
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        content = item.get("contentDetails", {})
        return {
            "youtube_video_id": item["id"],
            "title": snippet.get("title", ""),
            "description": (snippet.get("description", "") or "")[:2000],
            "tags": json.dumps(snippet.get("tags", [])),
            "published_at": datetime.fromisoformat(
                snippet["publishedAt"].replace("Z", "+00:00")
            ),
            "view_count": int(stats.get("viewCount", 0)),
            "like_count": int(stats.get("likeCount", 0)),
            "comment_count": int(stats.get("commentCount", 0)),
            "duration_seconds": self._parse_duration(content.get("duration", "PT0S")),
            "thumbnail_url": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
        }

    @staticmethod
    def _parse_duration(iso_duration: str) -> int:
        match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
        if not match:
            return 0
        h, m, s = (int(g) if g else 0 for g in match.groups())
        return h * 3600 + m * 60 + s


youtube_api = YouTubeAPI()
