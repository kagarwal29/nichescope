"""User account model."""

from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nichescope.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    youtube_channel_id: Mapped[str | None] = mapped_column(String(64))
    youtube_access_token: Mapped[str | None] = mapped_column(String(512))
    youtube_refresh_token: Mapped[str | None] = mapped_column(String(512))
    api_key: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: secrets.token_urlsafe(32))
    tier: Mapped[str] = mapped_column(String(20), default="free")  # free | pro | creator_pro
    brief_time: Mapped[str] = mapped_column(String(5), default="08:00")
    timezone: Mapped[str] = mapped_column(String(40), default="UTC")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    niches: Mapped[list["Niche"]] = relationship("Niche", back_populates="user", cascade="all, delete-orphan")

    def max_competitors(self) -> int:
        limits = {"free": 3, "pro": 15, "creator_pro": 100}
        return limits.get(self.tier, 3)
