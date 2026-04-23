"""Conversational YouTube assistant via GenAI + live YouTube Data API.

Flow: plan (JSON) → fetch channel/video data → answer with grounded context.
Supports competitor intel, the user’s own channel, growth, diversification, and brainstorm/jam — not only “vs competitors.”
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

_APP_ACTIONS = frozenset({"digest_off", "digest_on", "digest_status"})

_PLAN_SYSTEM = """You are NicheScope, a Telegram assistant for YouTube creators: competitor intel, YOUR OWN channel, growth, diversification, format ideas, and casual brainstorm/jam — all grounded in live channel/video data when a channel is in scope.

Read the user's message and output ONLY valid JSON (no markdown fences) with this exact shape:
{
  "reply_direct": boolean,
  "direct_message": string | null,
  "channels_to_lookup": string[],
  "include_recent_videos": boolean,
  "video_sample_size": number,
  "app_action": null | "digest_off" | "digest_on" | "digest_status"
}

Rules:
- Plain text only inside direct_message when used (no markdown, no * or _).
- app_action (NicheScope app — NOT YouTube API):
  - digest_off: user wants to stop/pause/remove/cancel the scheduled daily competitor digest, automated digest, digest notifications, or "don't message me daily".
  - digest_on: user wants to turn daily/scheduled digest back on, resume automation, re-enable digest notifications.
  - digest_status: user asks whether daily digest is on, how to change digest, or bot notification/digest settings for NicheScope.
  - Otherwise app_action=null.
- When app_action is non-null: set channels_to_lookup=[], include_recent_videos=false, video_sample_size=0, reply_direct=false (the app will handle the reply).
- If the user greets, thanks you, asks what you do, or chats without a YouTube-related need: reply_direct=true, short friendly direct_message (under ~200 characters), app_action=null.
- If the topic is unrelated to both YouTube creator work AND this bot's settings: reply_direct=true with a brief polite message, app_action=null.
- When the user needs stats, comparisons, uploads, schedules, channel info, OR wants to brainstorm/jam on growth, diversification, packaging, content ideas, or strategy for THEIR channel or ANY named channel: reply_direct=false, app_action=null, fill channels_to_lookup with the 1–3 channel names or @handles they mean (include their own channel if they name it). If they want ideas but name no channel, reply_direct=true and direct_message asks for their @handle or channel name to pull real data.
- include_recent_videos=true when recent uploads, video titles, top/most-viewed lists, posting patterns, "latest", format experiments, or brainstorms about what to make next matter; false for subscriber-only questions where video lists add nothing.
- video_sample_size: integer 5–15 when include_recent_videos is true, else use 0.
- If you cannot tell which channel they mean: reply_direct=true and direct_message asks them to name the channel or @handle clearly, app_action=null.
"""

_ANSWER_SYSTEM = """You are NicheScope. Answer in a crisp Telegram style. Ground every factual claim (subs, views, titles, cadence) in the YouTube API JSON below — never invent stats or video titles.

The user may be on a competitor, their own channel, or any mix. They may want a quick jam: growth, diversification, formats, packaging, or content ideas.

Length and shape (strict):
- Aim for at most ~900 characters total (about 8–12 short lines). Do not ramble.
- Open with the direct read on the data in 1–2 tight sentences. Then, if useful: up to 3 bullets, one line each.
- Comparisons: one short paragraph or a few labeled lines — not an essay.
- Facts: only what the JSON supports.
- Brainstorm / ideas: when they ask to ideate, jam, diversify, or "what should I try", add up to 3 extra lines starting with "Idea:" — short, concrete, clearly suggestions (not facts). Tie each idea to a pattern visible in the data when you can; if not, say it is a general experiment to test.
- No preamble ("Sure", "Here is"). No restating the full question. No closing lecture.

If a lookup failed or data is missing, say so in one short sentence.

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
        "niche", "stats", "sub", "vlog", "grow", "growth", "brainstorm", "idea",
        "ideas", "diversify", "diversification", "jam", "ideate", "strategy",
        "format", "formats", "audience",
    }
)
_CAPABILITIES_BLURB = (
    "Ask about any channel (yours or anyone else's): stats, recent videos, comparisons, "
    "niche gaps, growth, diversification, or a quick brainstorm — with live YouTube data. "
    "Watchlist + scheduled pulse: /watch, /digest, /watches. Tap /start for buttons."
)

_WELCOME_REPLY = (
    "Hi! I'm NicheScope — your YouTube copilot for intel and ideas.\n\n"
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
    plan.setdefault("app_action", None)
    if not isinstance(plan["channels_to_lookup"], list):
        plan["channels_to_lookup"] = []
    plan["channels_to_lookup"] = [
        str(x).strip() for x in plan["channels_to_lookup"][:3] if str(x).strip()
    ]
    vs = int(plan.get("video_sample_size") or 0)
    plan["video_sample_size"] = max(5, min(15, vs)) if plan["include_recent_videos"] else 0
    raw_aa = plan.get("app_action")
    if raw_aa is None or str(raw_aa).strip().lower() in ("null", "none", ""):
        plan["app_action"] = None
    else:
        aa = str(raw_aa).strip().lower()
        plan["app_action"] = aa if aa in _APP_ACTIONS else None
    if plan["app_action"] in _APP_ACTIONS:
        plan["channels_to_lookup"] = []
        plan["reply_direct"] = False
        plan["include_recent_videos"] = False
        plan["video_sample_size"] = 0
    return plan


def _heuristic_app_action(text: str) -> str | None:
    """Backup when the planner misses obvious digest-setting phrases."""
    t = _normalize_chat_text(text).lower()
    if not t:
        return None
    off = (
        "remove daily digest",
        "stop daily digest",
        "turn off daily digest",
        "disable daily digest",
        "cancel daily digest",
        "no more daily digest",
        "pause daily digest",
        "stop scheduled digest",
        "turn off scheduled digest",
        "stop digest notifications",
        "disable digest notifications",
        "don't send daily digest",
        "dont send daily digest",
        "unsubscribe from digest",
    )
    on = (
        "resume daily digest",
        "turn on daily digest",
        "enable daily digest",
        "start daily digest",
        "turn daily digest back on",
        "digest back on",
        "reenable daily digest",
        "re-enable daily digest",
    )
    status = (
        "digest status",
        "daily digest status",
        "is daily digest on",
        "digest settings",
        "notification settings",
    )
    for p in off:
        if p in t:
            return "digest_off"
    for p in on:
        if p in t:
            return "digest_on"
    for p in status:
        if p in t:
            return "digest_status"
    return None


async def _apply_app_action(chat_id: int, action: str) -> str:
    from nichescope.services.chat_prefs import (
        apply_daily_digest_toggle,
        daily_digest_status_message,
    )

    if action == "digest_off":
        return await apply_daily_digest_toggle(chat_id, False)
    if action == "digest_on":
        return await apply_daily_digest_toggle(chat_id, True)
    if action == "digest_status":
        return await daily_digest_status_message(chat_id)
    return "Unknown action."


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
        temperature=0.48,
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


async def classify_and_respond(
    text: str,
    youtube: YouTubeAPI,
    *,
    chat_id: int | None = None,
) -> tuple[str, ResponseMeta]:
    """Conversational entry: plan → YouTube data → answer.

    chat_id is required for in-bot settings (e.g. digest on/off).
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
            "I could not interpret that request. Try naming a channel or @handle and what you want "
            "(stats, compare, growth brainstorm, diversification ideas, etc.).",
            _direct,
        )

    channels = plan.get("channels_to_lookup") or []

    aa = plan.get("app_action")
    if aa not in _APP_ACTIONS:
        aa = _heuristic_app_action(text)
    if aa in _APP_ACTIONS:
        if chat_id is None:
            return (
                "Open this chat in Telegram and try again, or use /digest_off and /digest_on.",
                _direct,
            )
        msg = await _apply_app_action(chat_id, aa)
        return msg, _direct

    if plan.get("reply_direct"):
        dm = plan.get("direct_message")
        if dm:
            return str(dm).strip(), _direct
        if not channels:
        return (
            "I can help with any channel — yours or someone else's: stats, uploads, comparisons, "
            "growth ideas, or a quick jam. Name the @handle or channel and what you want.",
            _direct,
        )

    if not channels:
        return (
            "Which channel should I use — yours or another? "
            "Name the @handle or channel title and what you want (stats, compare, brainstorm, etc.).",
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
