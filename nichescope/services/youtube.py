"""YouTube Data API v3 client — clean, stateless, quota-aware."""

from __future__ import annotations

import logging

from googleapiclient.discovery import build

from nichescope.config import settings

logger = logging.getLogger(__name__)


def _looks_like_handle_query(name: str) -> bool:
    """Single-token @handle-style query (skip broad search when possible)."""
    n = name.strip()
    if not n or " " in n:
        return False
    core = n[1:] if n.startswith("@") else n
    # YouTube handles: letters, digits, underscores, dots, hyphens
    allowed = frozenset(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    )
    return bool(core) and all(c in allowed for c in core)


class YouTubeAPI:
    def __init__(self):
        self._service = build("youtube", "v3", developerKey=settings.youtube_api_key)
        self._quota_used = 0

    def _charge(self, cost: int = 1):
        self._quota_used += cost

    # ── Channel lookup ───────────────────────────────────────────────

    def lookup_channel(self, name: str) -> dict | None:
        """Find a YouTube channel by name or @handle. Returns dict or None."""
        # Try as @handle first (cheap: 1 unit)
        if _looks_like_handle_query(name):
            ch = self._by_handle(name.lstrip("@"))
            if ch:
                return ch

        # Fall back to search (100 units)
        return self._by_search(name)

    def get_channel_by_id(self, channel_id: str) -> dict | None:
        """Fetch channel by canonical id (UC…). Used for saved watchlist rows."""
        return self._by_id(channel_id)

    def _by_handle(self, handle: str) -> dict | None:
        self._charge(1)
        try:
            resp = self._service.channels().list(
                part="snippet,statistics,contentDetails",
                forHandle=handle,
            ).execute()
            items = resp.get("items", [])
            return self._parse_channel(items[0]) if items else None
        except Exception:
            return None

    def _by_search(self, query: str) -> dict | None:
        self._charge(100)
        try:
            resp = self._service.search().list(
                part="snippet", q=query, type="channel", maxResults=1,
            ).execute()
            items = resp.get("items", [])
            if not items:
                return None
            channel_id = items[0]["snippet"]["channelId"]
            return self._by_id(channel_id)
        except Exception:
            return None

    def _by_id(self, channel_id: str) -> dict | None:
        self._charge(1)
        try:
            resp = self._service.channels().list(
                part="snippet,statistics,contentDetails",
                id=channel_id,
            ).execute()
            items = resp.get("items", [])
            return self._parse_channel(items[0]) if items else None
        except Exception:
            return None

    def _parse_channel(self, item: dict) -> dict:
        stats = item.get("statistics", {})
        snippet = item.get("snippet", {})
        content = item.get("contentDetails", {})
        return {
            "channel_id": item["id"],
            "title": snippet.get("title", ""),
            "handle": snippet.get("customUrl", ""),
            "description": (snippet.get("description", "") or "")[:500],
            "subscriber_count": int(stats.get("subscriberCount", 0)),
            "video_count": int(stats.get("videoCount", 0)),
            "view_count": int(stats.get("viewCount", 0)),
            "thumbnail_url": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
            "uploads_playlist_id": content.get("relatedPlaylists", {}).get("uploads"),
            "created_at": snippet.get("publishedAt", ""),
        }

    # ── Video operations ─────────────────────────────────────────────

    def get_recent_videos(self, uploads_playlist_id: str, count: int = 10) -> list[dict]:
        """Fetch recent videos from a channel's uploads playlist."""
        self._charge(1)
        try:
            resp = self._service.playlistItems().list(
                part="contentDetails",
                playlistId=uploads_playlist_id,
                maxResults=min(count, 50),
            ).execute()
            video_ids = [
                item["contentDetails"]["videoId"]
                for item in resp.get("items", [])
            ]
            if not video_ids:
                return []
            return self._get_video_details(video_ids)
        except Exception:
            return []

    def _get_video_details(self, video_ids: list[str]) -> list[dict]:
        self._charge(1)
        try:
            resp = self._service.videos().list(
                part="snippet,statistics,contentDetails",
                id=",".join(video_ids[:50]),
            ).execute()
            return [self._parse_video(item) for item in resp.get("items", [])]
        except Exception:
            return []

    def _parse_video(self, item: dict) -> dict:
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        return {
            "video_id": item["id"],
            "title": snippet.get("title", ""),
            "published_at": snippet.get("publishedAt", ""),
            "view_count": int(stats.get("viewCount", 0)),
            "like_count": int(stats.get("likeCount", 0)),
            "comment_count": int(stats.get("commentCount", 0)),
            "duration": item.get("contentDetails", {}).get("duration", ""),
        }
