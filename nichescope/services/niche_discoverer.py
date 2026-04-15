"""Auto-discover niche from natural language and find competitor channels.

Handles the zero-onboarding flow:
  1. User sends any question ("I want to start a mock interview channel")
  2. extract_niche() pulls out "mock interviews"
  3. discover_competitor_channels() finds top YouTube channels in that space

Channel discovery strategy:
  - Search for VIDEOS in the niche, then extract channels from the results.
    This is far more accurate than searching by channel name because it finds
    channels that *actually produce content* in the niche.
  - If user mentions a reference channel (e.g. "same space as mockschool"),
    look it up first, grab its recent video titles, and use those as
    additional search terms to find true competitors.
"""

from __future__ import annotations

import logging
import re

from nichescope.services.youtube_api import youtube_api

logger = logging.getLogger(__name__)

_NICHE_PATTERNS = [
    r"(?:start|launch|create|begin|build|grow|run|open)\s+(?:a\s+|an\s+|my\s+)?(.+?)\s+(?:channel|youtube|yt)\b",
    r"(?:thinking|thought|planning|considering)\s+(?:about|of)\s+(?:starting\s+|creating\s+|making\s+)?(?:a\s+|an\s+)?(.+?)\s+(?:channel|youtube|content|videos?)\b",
    r"(?:not\s+(?:being\s+)?covered|missing|gaps?|underserved|untapped|opportunities?|not\s+enough)\s+(?:in|for|on|about|with)\s+(?:youtube\s+)?(.+?)(?:\s+on\s+youtube)?(?:\.|,|\?|$)",
    r"(.+?)\s+(?:channel|youtube\s+channel|yt\s+channel)(?:\s|$|\?|,|\.)",
    r"(?:interested|curious)\s+(?:in|about)\s+(.+?)(?:\s+on\s+youtube|\s+content|\s+videos?)?\s*(?:\.|,|\?|$)",
    r"what(?:'s|\s+is)?\s+(?:the\s+)?(?:scope|scene|space|market|landscape)\s+(?:for|of|in|like)\s+(.+?)(?:\s+on\s+youtube)?(?:\.|,|\?|$)",
    r"(?:analyze|analyse|research|explore|study|look\s+into|check\s+out|investigate)\s+(?:the\s+)?(.+?)(?:\s+(?:niche|space|market|landscape|scene))?(?:\s+on\s+youtube)?(?:\.|,|\?|$)",
    r"(.+?)\s+niche\b",
    r"content\s+(?:about|on|for|in|around)\s+(.+?)(?:\s+on\s+youtube)?(?:\.|,|\?|$)",
    r"videos?\s+(?:about|on|for|in|around)\s+(.+?)(?:\s+on\s+youtube)?(?:\.|,|\?|$)",
    r"(?:money|revenue|earn|income|monetize)\s+(?:with|from|in|doing)\s+(.+?)(?:\s+on\s+youtube)?(?:\.|,|\?|$)",
    r"(?:succeed|grow|compete|win|make\s+it)\s+(?:in|with|doing)\s+(.+?)(?:\s+on\s+youtube)?(?:\.|,|\?|$)",
]

_STRIP_PREFIX = re.compile(r"^(a|an|the|my|some|new|this|that)\s+", re.I)
_STRIP_SUFFIX = re.compile(
    r"\s+(on\s+youtube|youtube|yt|video|videos|content|stuff|things?|type|kind|area|"
    r"genre|category|field|topic|subject|space|market|scene|landscape|niche)\s*$",
    re.I,
)

_REFERENCE_CHANNEL_PATTERNS = [
    r"(?:same|similar)\s+(?:space|niche|area|category|type|kind)\s+(?:as|to|like)\s+(.+?)(?:\s+channel|\s+youtube|\s+on\s+youtube)?(?:\.|,|\?|!|$)",
    r"(?:channels?|creators?|youtubers?)\s+(?:like|similar\s+to|competing\s+with)\s+(.+?)(?:\s+channel|\s+youtube)?(?:\.|,|\?|!|$)",
    r"(?:competitors?|competition|rivals?)\s+(?:of|for|to)\s+(.+?)(?:\s+channel|\s+youtube)?(?:\.|,|\?|!|$)",
    r"(?:compete|competing)\s+(?:with|against)\s+(.+?)(?:\s+channel)?(?:\.|,|\?|!|$)",
    r"(?:top\s+\d+|best|biggest)\s+(?:youtube\s+)?channels?\s+.*?(?:same\s+(?:space|niche)\s+as|like|similar\s+to|creating\s+.*?same\s+.*?as)\s+(.+?)(?:\s+channel)?(?:\.|,|\?|!|$)",
    r"creating\s+(?:in\s+)?(?:the\s+)?same\s+(?:space|niche|area)\s+(?:as|like)\s+(.+?)(?:\s+channel)?(?:\.|,|\?|!|$)",
    r"@(\w+)",
]


def extract_niche(text: str) -> str | None:
    lower = text.strip()
    for pattern in _NICHE_PATTERNS:
        match = re.search(pattern, lower, re.IGNORECASE)
        if match:
            niche = _clean_niche(match.group(1))
            if niche:
                return niche
    if re.search(r"(youtube|channel|video|content|niche|creator|upload)", lower, re.I):
        cleaned = re.sub(
            r"\b(what|how|why|where|when|which|can|could|should|would|do|does|is|are|"
            r"was|were|will|shall|i|me|you|we|they|my|your|our|the|a|an|it|its|"
            r"this|that|there|these|those|"
            r"want|need|like|think|know|see|tell|show|find|help|"
            r"about|youtube|yt|channel|video|videos|"
            r"content|niche|creator|upload|start|make|create|get|"
            r"not|being|covered|on|in|for|to|of|with|and|or|but|from|at|"
            r"much|many|best|good|great|top|most|really|very|just|also|"
            r"would|could|should|going|gonna)\b",
            "", lower, flags=re.I,
        )
        cleaned = re.sub(r"[^\w\s]", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if 3 <= len(cleaned) <= 80:
            return cleaned
    return None


def _clean_niche(raw: str) -> str | None:
    niche = raw.strip()
    niche = _STRIP_PREFIX.sub("", niche)
    niche = _STRIP_SUFFIX.sub("", niche)
    niche = re.sub(r"[^\w\s\-/&+]", "", niche)
    niche = re.sub(r"\s+", " ", niche).strip()
    if 2 <= len(niche) <= 100:
        return niche
    return None


def extract_reference_channel(text: str) -> str | None:
    """Detect when user mentions a specific YouTube channel as a reference point."""
    for pattern in _REFERENCE_CHANNEL_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            name = re.sub(r"[\s,.\?!]+$", "", name)
            name = re.sub(r"^(the|a|an)\s+", "", name, flags=re.I)
            if 2 <= len(name) <= 60:
                return name
    return None


def discover_competitor_channels(
    niche_name: str,
    max_channels: int = 5,
    reference_channel: str | None = None,
) -> list[dict]:
    """Find top YouTube channels in a niche using video-based discovery.

    Strategy:
      1. If a reference_channel is given, look it up, grab its recent video
         titles, and use those as search queries.
      2. Search for VIDEOS matching the niche / reference titles, then extract
         the unique channels producing those videos.
      3. Filter out very small channels and the reference channel itself.
    """
    reference_channel_id: str | None = None
    search_queries: list[str] = [niche_name]

    if reference_channel:
        ref_data = _lookup_reference_channel(reference_channel)
        if ref_data:
            reference_channel_id = ref_data.get("youtube_channel_id")
            logger.info(
                "Reference channel '%s' resolved to '%s' (%s)",
                reference_channel, ref_data.get("title"), reference_channel_id,
            )
            video_titles = youtube_api.get_channel_videos_sample(
                reference_channel_id, max_results=10
            )
            if video_titles:
                sample = video_titles[:4]
                content_query = " ".join(sample)
                if len(content_query) > 120:
                    content_query = content_query[:120]
                search_queries = [content_query, niche_name]
                logger.info("Using video-based query from reference channel: %s", content_query[:80])

    all_channels: dict[str, dict] = {}
    for query in search_queries:
        try:
            results = youtube_api.search_channels_by_videos(query, max_videos=25)
            for ch in results:
                ch_id = ch.get("youtube_channel_id")
                if ch_id and ch_id not in all_channels:
                    all_channels[ch_id] = ch
        except Exception as e:
            logger.warning("Video-based search failed for '%s': %s", query, e)

    channels = list(all_channels.values())

    if reference_channel_id:
        channels = [
            ch for ch in channels
            if ch.get("youtube_channel_id") != reference_channel_id
        ]

    channels = [ch for ch in channels if ch.get("subscriber_count", 0) >= 1000]
    channels.sort(key=lambda c: c.get("subscriber_count", 0), reverse=True)
    return channels[:max_channels]


def _lookup_reference_channel(name: str) -> dict | None:
    if re.match(r"^@?\w+$", name):
        try:
            ch = youtube_api.get_channel_by_handle(name)
            if ch:
                return ch
        except Exception:
            pass
    try:
        ch = youtube_api.search_channel(f"{name} youtube channel")
        if ch:
            return ch
    except Exception as e:
        logger.warning("Reference channel lookup failed for '%s': %s", name, e)
    return None
