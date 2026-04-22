"""Conversational YouTube assistant via GenAI + live YouTube Data API.

Flow: plan (JSON) → fetch channel/video data → answer with grounded context.
No regex-based routing; no slash-command logic here.
"""

from __future__ import annotations

import json
import logging
import unicodedata
from typing import Any

import httpx

from nichescope.config import settings
from nichescope.services.youtube import YouTubeAPI

logger = logging.getLogger(__name__)

_http: httpx.AsyncClient | None = None

_PLAN_SYSTEM = """You are NicheScope, a Telegram assistant focused on YouTube creators and videos.

Read the user's message and output ONLY valid JSON (no markdown fences) with this exact shape:
{
  "reply_direct": boolean,
  "direct_message": string | null,
  "channels_to_lookup": string[],
  "include_recent_videos": boolean,
  "video_sample_size": number
}

Rules:
- Plain text only inside direct_message when used (no markdown, no * or _).
- If the user greets, thanks you, asks what you do, or chats without a YouTube-related need: reply_direct=true, short friendly direct_message (under ~200 characters).
- If the topic is clearly not about YouTube (creators, channels, videos, views, uploads, subscribers, etc.): reply_direct=true with a brief polite message that you only help with YouTube-related questions.
- When the user needs stats, comparisons, recent uploads, top videos, schedules, or channel info: reply_direct=false and fill channels_to_lookup with 1–3 search strings (names or @handles) that work in YouTube search.
- include_recent_videos=true when recent uploads, video titles, top/most-viewed lists, posting patterns, or "latest" matters; false for subscriber-only or generic stat questions where listing videos is unnecessary.
- video_sample_size: integer 5–15 when include_recent_videos is true, else use 0.
- If you cannot tell which channel they mean: reply_direct=true and direct_message asks them to name the channel or @handle clearly.
"""

_ANSWER_SYSTEM = """You are NicheScope. Answer in a crisp Telegram style using ONLY the YouTube API data below.

Length and shape (strict):
- Aim for at most ~900 characters total (about 8–12 short lines). Do not ramble.
- Open with the direct answer in 1–2 tight sentences. Only then, if needed: up to 3 bullets, one line each.
- Comparisons: one short paragraph or a few labeled lines — not an essay.
- Strategy / "what to do next" angles: at most 3 bullets, each under 12 words, grounded only in the data shown.
- No preamble ("Sure", "Here is", "I'd be happy"). No restating the user's question. No closing lecture.

If a lookup failed or data is missing, say so in one short sentence. Do not invent statistics or video titles.

Plain text only — no markdown, asterisks, or underscores."""


def _ssl_verify():
    """Return the httpx `verify=` value: path string, False, or True (system CAs)."""
    import os
    # SSL_CERT_FILE is set in docker-compose and respected by Python's ssl module globally.
    # Passing it explicitly to httpx ensures it's used even if the env var propagation is delayed.
    bundle = (
        os.environ.get("SSL_CERT_FILE")
        or os.environ.get("REQUESTS_CA_BUNDLE")
        or (settings.ssl_ca_bundle or "").strip()
    )
    if not bundle:
        return True
    if bundle.lower() == "false":
        return False
    from pathlib import Path
    return str(bundle) if Path(bundle).is_file() else True


def _get_http() -> httpx.AsyncClient | None:
    global _http
    if not settings.genai_token:
        return None
    if _http is None:
        _http = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0),
            verify=_ssl_verify(),
            headers={
                "Authorization": f"Bearer {settings.genai_token}",
                "Content-Type": "application/json",
            },
        )
    return _http


async def close_genai_http_client() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


async def chat_completion(
    messages: list[dict[str, Any]],
    *,
    max_tokens: int = 1024,
    temperature: float = 0.4,
) -> str | None:
    http = _get_http()
    if not http:
        return None
    model = settings.genai_model.strip()
    if not model:
        logger.warning("GENAI_MODEL is empty — set it to a model your GenAI project allows")
        return None
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    try:
        r = await http.post(settings.genai_chat_url, json=body)
        r.raise_for_status()
        data = r.json()
        choices = data.get("choices") or []
        if not choices:
            logger.warning("GenAI response missing choices: %s", data)
            return None
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if content is None:
            return None
        return str(content).strip()
    except httpx.HTTPStatusError as e:
        txt = e.response.text[:800] if e.response.text else ""
        logger.warning(
            "GenAI HTTP error: %s — %s", e.response.status_code, txt
        )
        if e.response.status_code == 403 and (
            "does not have access to model" in txt or "access to model" in txt
        ):
            logger.warning(
                "403 model access: set GENAI_MODEL in .env to a model id enabled for your "
                "GenAI project (internal catalog / project settings)."
            )
        return None
    except Exception as e:
        logger.warning("GenAI request failed: %s", e)
        return None


def _strip_json_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.lower().startswith("json"):
            raw = raw[4:].lstrip("\n")
    return raw.strip()


def _parse_plan(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    stripped = _strip_json_fences(raw)
    candidates = [stripped]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        candidates.append(stripped[start : end + 1])
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    logger.warning("Plan JSON parse failed (first 120 chars): %s", stripped[:120])
    return None


_GREETING_WORDS = frozenset(
    {"hi", "hello", "hey", "yo", "hiya", "howdy", "sup", "greetings"}
)
_GREETING_TAIL = frozenset(
    {
        "there", "you", "ya", "u", "all", "team", "folks", "everyone", "again", "buddy",
        "bro", "mate", "friend", "pal", "morning", "afternoon", "evening", "day", "night",
        "good",
    }
)
_THANKS_WORDS = frozenset({"thanks", "thank", "thx", "ty", "cheers"})
# After a greeting, these suggest a real request — do not treat as small talk.
_REQUEST_VERBS = frozenset(
    {"can", "could", "would", "will", "show", "tell", "find", "look", "get", "give", "list", "check"}
)
# If the user mentions YouTube-related intent, always run the planner — never short-circuit.
_YT_INTENT_WORDS = frozenset(
    {
        "youtube", "yt", "channel", "channels", "video", "videos", "subscriber",
        "subscribers", "subs", "views", "view", "upload", "uploads", "compare",
        "vs", "watch", "digest", "creator", "creators", "shorts", "trend", "trends",
        "niche", "stats", "sub", "vlog",
    }
)
_CAPABILITIES_BLURB = (
    "Ask about any channel by name or @handle — stats, recent videos, comparisons, "
    "or niche ideas. For recurring competitor tracking: /watch, /digest, /watches. "
    "Tap /start for command buttons."
)

_WELCOME_REPLY = (
    "Hi! I'm NicheScope — your YouTube intel assistant.\n\n"
    f"{_CAPABILITIES_BLURB}"
)


def _normalize_chat_text(text: str) -> str:
    """Strip ZWSP/BOM and normalize Unicode so Telegram / copy-paste variants still match."""
    t = unicodedata.normalize("NFKC", (text or "").strip())
    for z in ("\u200b", "\u200c", "\u200d", "\ufeff"):
        t = t.replace(z, "")
    return t.strip()


def _loose_greeting_word(w: str) -> bool:
    """Match hi/hii/hiii, hey/heyy, and dictionary greetings."""
    w = w.lower().strip("!.?…,")
    if w in _GREETING_WORDS:
        return True
    if 2 <= len(w) <= 5 and w.startswith("hi") and all(c == "h" or c == "i" for c in w):
        return True
    if 3 <= len(w) <= 6 and w.startswith("hey") and all(c in "hey" for c in w):
        return True
    return False


def _small_talk_reply(text: str) -> str | None:
    """Short openers (Hi, thanks) and capability questions — without stealing real YouTube queries."""
    raw = _normalize_chat_text(text)
    if not raw:
        return None
    lowered = raw.lower()
    simple = "".join(c if c.isalnum() or c.isspace() else " " for c in lowered)
    words = [w for w in simple.split() if w]
    if not words:
        return None

    if _YT_INTENT_WORDS.intersection(words):
        return None
    if "?" in raw:
        return None

    joined = " ".join(words)

    # "what can you do" / "who are you" style (exact short phrases only)
    if joined in {
        "what can you do",
        "what do you do",
        "who are you",
        "what are you",
    }:
        return (
            "I'm NicheScope — I answer questions using live YouTube Data API results.\n\n"
            f"{_CAPABILITIES_BLURB}"
        )

    if words == ["help"] or joined in {"help me", "need help"}:
        return f"Happy to help.\n\n{_CAPABILITIES_BLURB}"

    # Thanks — keep short; avoid matching "thanks youtube"
    if words[0] in _THANKS_WORDS and len(words) <= 3:
        return "You're welcome! Ask anytime about channels, videos, or your watchlist."

    # Time-of-day openers
    if joined in {"good morning", "good afternoon", "good evening", "good day", "good night"}:
        return _WELCOME_REPLY

    # Greetings: hi/hii/hello + optional tail word from a safe list (Hi bro, Hey there)
    if (
        len(words) <= 3
        and _loose_greeting_word(words[0])
        and not _REQUEST_VERBS.intersection(words[1:])
    ):
        rest = words[1:]
        if not rest or all(
            w in _GREETING_TAIL or _loose_greeting_word(w) for w in rest
        ):
            return _WELCOME_REPLY

    return None


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,}"


def bundle_channel_data(
    query: str,
    channel_data: dict | None,
    videos: list[dict],
) -> dict[str, Any]:
    if not channel_data:
        return {"lookup_query": query, "found": False, "error": "No channel matched."}
    by_views = sorted(
        videos, key=lambda v: v.get("view_count", 0), reverse=True
    )
    return {
        "lookup_query": query,
        "found": True,
        "channel": {
            "title": channel_data.get("title"),
            "handle": channel_data.get("handle"),
            "subscribers": channel_data.get("subscriber_count"),
            "subscribers_display": _fmt(int(channel_data.get("subscriber_count", 0))),
            "total_views": channel_data.get("view_count"),
            "total_views_display": _fmt(int(channel_data.get("view_count", 0))),
            "video_count": channel_data.get("video_count"),
            "created_at": channel_data.get("created_at", ""),
            "description_excerpt": (channel_data.get("description") or "")[:400],
        },
        "videos_recent": videos[:20],
        "videos_highest_views": by_views[:10],
    }


def _summarize_fallback(bundles: list[dict[str, Any]]) -> str:
    """Minimal grounded text if the final LLM call fails."""
    lines: list[str] = []
    for b in bundles:
        if not b.get("found"):
            lines.append(f"Channel search \"{b.get('lookup_query', '')}\": not found.")
            continue
        ch = b.get("channel") or {}
        lines.append(
            f"{ch.get('title', 'Channel')}: "
            f"{ch.get('subscribers_display', '?')} subscribers, "
            f"{ch.get('video_count', '?')} videos, "
            f"{ch.get('total_views_display', '?')} total views."
        )
    return "\n".join(lines) if lines else "I could not load YouTube data for that request."


async def _plan_turn(user_message: str) -> dict[str, Any] | None:
    raw = await chat_completion(
        [
            {"role": "system", "content": _PLAN_SYSTEM},
            {"role": "user", "content": user_message},
        ],
        max_tokens=500,
        temperature=0.2,
    )
    plan = _parse_plan(raw)
    if plan is None:
        return None
    # Normalize
    plan.setdefault("reply_direct", False)
    plan.setdefault("direct_message", None)
    plan.setdefault("channels_to_lookup", [])
    plan.setdefault("include_recent_videos", False)
    plan.setdefault("video_sample_size", 10)
    if not isinstance(plan["channels_to_lookup"], list):
        plan["channels_to_lookup"] = []
    plan["channels_to_lookup"] = [
        str(x).strip() for x in plan["channels_to_lookup"][:3] if str(x).strip()
    ]
    vs = int(plan.get("video_sample_size") or 0)
    plan["video_sample_size"] = max(5, min(15, vs)) if plan["include_recent_videos"] else 0
    return plan


async def _answer_turn(user_message: str, bundles: list[dict[str, Any]]) -> str | None:
    payload = json.dumps(bundles, indent=2, default=str)
    if len(payload) > 28000:
        payload = payload[:28000] + "\n…(truncated)"
    return await chat_completion(
        [
            {"role": "system", "content": _ANSWER_SYSTEM},
            {
                "role": "user",
                "content": f"User message:\n{user_message}\n\nYouTube data (JSON):\n{payload}",
            },
        ],
        max_tokens=700,
        temperature=0.42,
    )


class ResponseMeta:
    """Metadata returned alongside the LLM answer for generating contextual suggestions."""
    __slots__ = ("plan_type", "channels_queried", "channels_found", "had_videos")

    def __init__(
        self,
        plan_type: str,
        channels_queried: list[str],
        channels_found: list[str],
        had_videos: bool,
    ):
        self.plan_type = plan_type          # "direct" | "channel_lookup"
        self.channels_queried = channels_queried
        self.channels_found = channels_found  # actual channel titles from the API
        self.had_videos = had_videos


async def classify_and_respond(text: str, youtube: YouTubeAPI) -> tuple[str, ResponseMeta]:
    """Conversational entry: plan → YouTube data → answer.

    Returns (answer_text, ResponseMeta) so callers can build contextual suggestions.
    """
    _direct = ResponseMeta("direct", [], [], False)

    if not settings.genai_token:
        logger.warning("GENAI_TOKEN not set")
        return "The bot is not configured yet. Set GENAI_TOKEN in the environment.", _direct

    if not settings.genai_model.strip():
        logger.warning("GENAI_MODEL not set")
        return (
            "Set GENAI_MODEL in your environment to a chat model id your Uber GenAI project "
            "is allowed to use (for example from your project's model allowlist). "
            "Plain gpt-4 often returns 403 until your project is provisioned for that model.",
            _direct,
        )

    text = _normalize_chat_text(text)
    logger.info("User message (truncated): %s", text[:200])

    st = _small_talk_reply(text)
    if st:
        return st, _direct

    plan = await _plan_turn(text)
    if plan is None:
        # Planner failed (invalid JSON, empty response): don't punish short chit-chat
        st2 = _small_talk_reply(text)
        if st2:
            return st2, _direct
        if len(text) <= 48 and not any(ch.isdigit() for ch in text):
            tokens = [w for w in "".join(
                c if c.isalnum() or c.isspace() else " " for c in text.lower()
            ).split() if w]
            if (
                len(tokens) <= 4
                and not _YT_INTENT_WORDS.intersection(tokens)
                and not _REQUEST_VERBS.intersection(tokens)
                and "?" not in text
            ):
                return _WELCOME_REPLY, _direct
        return (
            "I could not interpret that request. Please ask about a YouTube channel "
            "or video topic, and mention the channel name or @handle if you can.",
            _direct,
        )

    channels = plan.get("channels_to_lookup") or []

    if plan.get("reply_direct"):
        dm = plan.get("direct_message")
        if dm:
            return str(dm).strip(), _direct
        if not channels:
            return (
                "Hi! I can help with YouTube channels and videos — stats, recent uploads, "
                "top videos, or comparisons. Tell me which channel or @handle you care about.",
                _direct,
            )

    if not channels:
        return (
            "Which YouTube channel or creator should I look up? "
            "Name the channel or @handle and what you want to know.",
            _direct,
        )

    if not settings.youtube_api_key:
        return "YouTube API is not configured, so I cannot fetch live channel data.", _direct

    bundles: list[dict[str, Any]] = []
    sample = plan.get("video_sample_size") or 10
    want_videos = bool(plan.get("include_recent_videos"))
    found_titles: list[str] = []

    for q in channels:
        ch = youtube.lookup_channel(q)
        videos: list[dict] = []
        if ch:
            found_titles.append(ch.get("title") or q)
            if want_videos and ch.get("uploads_playlist_id"):
                try:
                    videos = youtube.get_recent_videos(
                        ch["uploads_playlist_id"],
                        count=sample,
                    )
                except Exception as e:
                    logger.warning("Video fetch failed for %s: %s", q, e)
        bundles.append(bundle_channel_data(q, ch, videos))

    answer = await _answer_turn(text, bundles)
    meta = ResponseMeta(
        plan_type="channel_lookup",
        channels_queried=channels,
        channels_found=found_titles,
        had_videos=want_videos and bool(videos),
    )
    if answer:
        return answer.strip(), meta
    return _summarize_fallback(bundles), meta
