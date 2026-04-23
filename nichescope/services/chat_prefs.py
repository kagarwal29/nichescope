"""Per-chat preferences (e.g. daily digest opt-out)."""

from __future__ import annotations

from nichescope.config import settings
from nichescope.db.models import ChatPreferences
from nichescope.db.session import get_session


async def is_daily_digest_enabled(chat_id: int) -> bool:
    """Default True when no row exists (opt-out model)."""
    async with get_session() as session:
        row = await session.get(ChatPreferences, chat_id)
        if row is None:
            return True
        return bool(row.daily_digest_enabled)


async def set_daily_digest_enabled(chat_id: int, enabled: bool) -> None:
    async with get_session() as session:
        row = await session.get(ChatPreferences, chat_id)
        if row is None:
            session.add(ChatPreferences(chat_id=chat_id, daily_digest_enabled=enabled))
        else:
            row.daily_digest_enabled = enabled


def _digest_toggle_reply(enabled: bool) -> str:
    """User-facing confirmation (global server flag noted when relevant)."""
    if enabled:
        body = (
            f"Daily auto-digest is ON for you (~{settings.digest_hour_utc}:00 UTC). "
            "You will get the scheduled channel pulse if you have channels on your watchlist."
        )
    else:
        body = (
            "Daily auto-digest is OFF for you. I will not send the scheduled digest. "
            "You can still run /digest anytime. "
            "Turn it back on with /digest_on or say \"enable daily digest\"."
        )
    if not settings.digest_enabled:
        body += "\n\n(Note: DIGEST_ENABLED is off for this bot deployment, so no chats get scheduled runs until an admin turns that on.)"
    return body


async def apply_daily_digest_toggle(chat_id: int, enable: bool) -> str:
    await set_daily_digest_enabled(chat_id, enable)
    return _digest_toggle_reply(enable)


async def daily_digest_status_message(chat_id: int) -> str:
    """Summarize digest scheduling for this chat."""
    mine = await is_daily_digest_enabled(chat_id)
    glob = settings.digest_enabled
    lines = [
        f"Your daily auto-digest: {'on' if mine else 'off'}.",
        f"Scheduled time (UTC): ~{settings.digest_hour_utc}:00.",
        f"Server scheduler: {'on' if glob else 'off'} (DIGEST_ENABLED).",
        "",
        "Toggle: /digest_off  /digest_on  — or say e.g. \"stop daily digest\" / \"resume daily digest\".",
    ]
    return "\n".join(lines)
