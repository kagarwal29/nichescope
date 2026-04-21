"""Security guardrails — rate limiting + injection prevention."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class GuardrailResult:
    safe: bool
    reason: str = ""
    sanitized_text: str = ""


_rate_windows: dict[int, list[float]] = {}
_RATE_LIMIT = 30
_RATE_WINDOW = 60

_BLOCK_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"(DROP\s+TABLE|DELETE\s+FROM|INSERT\s+INTO|UNION\s+SELECT)",
        r"(rm\s+-rf|chmod|sudo|/bin/|/usr/bin/)",
        r"(<script|javascript:|onerror=|<iframe)",
        r"(\.\./)|(\.\.\\)|(/etc/)|(/proc/)",
        r"(ignore.*instruction|forget.*prompt|system prompt|pretend you are)",
        r"(hack|exploit|ddos|malware|phish|scam)",
    ]
]


def clear_user_state(chat_id: int) -> None:
    """Reset per-user session state. Call on /start to give a fresh session."""
    _rate_windows.pop(chat_id, None)


def check_message(chat_id: int, text: str) -> GuardrailResult:
    if not text or not text.strip():
        return GuardrailResult(safe=False, reason="Empty message")

    text = text.strip()

    # Rate limit
    now = time.time()
    window = _rate_windows.setdefault(chat_id, [])
    _rate_windows[chat_id] = [t for t in window if now - t < _RATE_WINDOW]
    if len(_rate_windows[chat_id]) >= _RATE_LIMIT:
        return GuardrailResult(safe=False, reason="⏳ Too many messages. Wait a moment.")
    _rate_windows[chat_id].append(now)

    # Length cap
    if len(text) > 2000:
        text = text[:2000]

    # Block patterns
    for pattern in _BLOCK_PATTERNS:
        if pattern.search(text):
            return GuardrailResult(safe=False, reason="🚫 I can only help with YouTube channels.")

    # Clean control chars
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return GuardrailResult(safe=True, sanitized_text=text.strip())
