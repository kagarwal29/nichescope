"""Security guardrails — standalone validation layer for user input."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class GuardrailResult:
    """Result of a guardrail check."""
    safe: bool
    reason: str = ""
    sanitized_text: str = ""


_rate_windows: dict[int, list[float]] = {}
_RATE_LIMIT_MSGS = 30
_RATE_LIMIT_WINDOW = 60


_SQL_INJECTION_PATTERNS = [
    r"(DROP\s+TABLE|DELETE\s+FROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|ALTER\s+TABLE)",
    r"(SELECT\s+\*\s+FROM|UNION\s+SELECT|;\s*DROP|OR\s+1\s*=\s*1)",
    r"(-{2}|/\*|\*/|xp_|sp_)",
]

_SHELL_INJECTION_PATTERNS = [
    r"(rm\s+-rf|chmod|chown|sudo|/bin/|/usr/bin/)",
    r"(\$\(|`|&&|;|\||>\s*/dev/null)",
]

_HTML_INJECTION_PATTERNS = [
    r"(<script|javascript:|onerror=|onclick=|onload=|<iframe)",
    r"(<img\s+src=|<body|<form|<input)",
]

_PATH_TRAVERSAL_PATTERNS = [
    r"(\.\./|\.\.\\|/etc/|/home/|/root/|/proc/|~)",
]

_SYSTEM_MANIPULATION_PATTERNS = [
    r"(__|import\s|exec\s*\(|eval\s*\(|os\.|sys\.|subprocess|__builtins__)",
    r"(open\s*\(|file\s*\(|compile\s*\()",
]

_PROMPT_INJECTION_PATTERNS = [
    r"(ignore.*instruction|forget.*prompt|system prompt|as if you were|pretend you are)",
    r"(you are now|act like|role play as|simulate)",
]

_PII_PATTERNS = [
    r"\b\d{3}-\d{2}-\d{4}\b",
    r"\b\d{16}\b",
    r"\b[A-Z]{2}\d{7}\b",
]

_BLOCKED_PATTERNS = [
    r"(hack|exploit|crack|brute.?force|ddos|malware)",
    r"(fake.*view|bot.*view|inflate.*sub|buy.*subscriber)",
    r"(spam|phish|scam)",
    r"(dox|doxx|swat|stalk|harass)",
    r"(weapon|bomb|drug|launder|fraud)",
    r"(copyright.?infring|pirat|torrent|steal.*content)",
]

_YOUTUBE_TOS_PATTERNS = [
    r"(impersonat|fake.*channel|stolen.*content|copyright)",
    r"(harassment|abuse|hate|discrimin)",
]

_SQL_RE = [re.compile(p, re.IGNORECASE) for p in _SQL_INJECTION_PATTERNS]
_SHELL_RE = [re.compile(p, re.IGNORECASE) for p in _SHELL_INJECTION_PATTERNS]
_HTML_RE = [re.compile(p, re.IGNORECASE) for p in _HTML_INJECTION_PATTERNS]
_PATH_RE = [re.compile(p, re.IGNORECASE) for p in _PATH_TRAVERSAL_PATTERNS]
_SYSTEM_RE = [re.compile(p, re.IGNORECASE) for p in _SYSTEM_MANIPULATION_PATTERNS]
_PROMPT_RE = [re.compile(p, re.IGNORECASE) for p in _PROMPT_INJECTION_PATTERNS]
_PII_RE = [re.compile(p) for p in _PII_PATTERNS]
_BLOCKED_RE = [re.compile(p, re.IGNORECASE) for p in _BLOCKED_PATTERNS]
_TOS_RE = [re.compile(p, re.IGNORECASE) for p in _YOUTUBE_TOS_PATTERNS]


def check_message(chat_id: int, text: str) -> GuardrailResult:
    """Validate user input against security guardrails."""
    if not text or not text.strip():
        return GuardrailResult(safe=False, reason="Empty message")

    text = text.strip()

    if not _check_rate_limit(chat_id):
        return GuardrailResult(
            safe=False,
            reason="⏳ You're sending messages too fast. Please wait a moment."
        )

    if len(text) > 2000:
        text = text[:2000]

    for pattern in _SQL_RE:
        if pattern.search(text):
            logger.warning("SQL injection attempt from chat_id=%d", chat_id)
            return GuardrailResult(safe=False, reason="🚫 I can only help with YouTube content strategy. That request is outside my scope.")

    for pattern in _SHELL_RE:
        if pattern.search(text):
            logger.warning("Shell injection attempt from chat_id=%d", chat_id)
            return GuardrailResult(safe=False, reason="🚫 I can only help with YouTube content strategy. That request is outside my scope.")

    for pattern in _HTML_RE:
        if pattern.search(text):
            logger.warning("HTML injection attempt from chat_id=%d", chat_id)
            return GuardrailResult(safe=False, reason="🚫 I can only help with YouTube content strategy. That request is outside my scope.")

    for pattern in _PATH_RE:
        if pattern.search(text):
            logger.warning("Path traversal attempt from chat_id=%d", chat_id)
            return GuardrailResult(safe=False, reason="🚫 I can only help with YouTube content strategy. That request is outside my scope.")

    for pattern in _SYSTEM_RE:
        if pattern.search(text):
            logger.warning("System manipulation attempt from chat_id=%d", chat_id)
            return GuardrailResult(safe=False, reason="🚫 I can only help with YouTube content strategy. That request is outside my scope.")

    for pattern in _PROMPT_RE:
        if pattern.search(text):
            logger.warning("Prompt injection attempt from chat_id=%d", chat_id)
            return GuardrailResult(safe=False, reason="🚫 I can only help with YouTube content strategy. That request is outside my scope.")

    for pattern in _PII_RE:
        if pattern.search(text):
            logger.warning("PII harvesting attempt from chat_id=%d", chat_id)
            return GuardrailResult(safe=False, reason="🚫 I can't help with that. I'm designed for YouTube niche analysis only.")

    for pattern in _BLOCKED_RE:
        if pattern.search(text):
            logger.warning("Harmful content attempt from chat_id=%d", chat_id)
            return GuardrailResult(safe=False, reason="🚫 I can't help with that. I'm designed for YouTube niche analysis only.")

    for pattern in _TOS_RE:
        if pattern.search(text):
            logger.warning("YouTube ToS violation attempt from chat_id=%d", chat_id)
            return GuardrailResult(safe=False, reason="🚫 I can't help with content that violates YouTube's Terms of Service.")

    sanitized = _sanitize_text(text)
    return GuardrailResult(safe=True, reason="", sanitized_text=sanitized)


def _check_rate_limit(chat_id: int) -> bool:
    now = time.time()
    if chat_id not in _rate_windows:
        _rate_windows[chat_id] = []
    _rate_windows[chat_id] = [t for t in _rate_windows[chat_id] if now - t < _RATE_LIMIT_WINDOW]
    if len(_rate_windows[chat_id]) >= _RATE_LIMIT_MSGS:
        return False
    _rate_windows[chat_id].append(now)
    return True


def _sanitize_text(text: str) -> str:
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text.strip()
