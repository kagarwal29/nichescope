"""Channel model — represents a YouTube channel (user's own or competitor)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Table, Column, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nichescope.models.base import Base

# --- Association tables ---

niche_channels = Table(
    "niche_channels",
    Base.metadata,
    Column("niche_id", Integer, ForeignKey("niches.id", ondelete="CASCADE"), primary_key=True),
    Column("channel_id", Integer, ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True),
)


class Niche(Base):
    """A user-defined niche (e.g. 'home cooking') with competitor channels."""

    __tablename__ = "niches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    seed_keywords: Mapped[str] = mapped_column(String(2000), default="[]")  # JSON list
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="niches")
    competitor_channels: Mapped[list["Channel"]] = relationship(
        "Channel", secondary=niche_channels, back_populates="niches"
    )


class Channel(Base):
    """A YouTube channel being tracked."""

    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    youtube_channel_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    handle: Mapped[str | None] = mapped_column(String(100), index=True)  # @handle
    subscriber_count: Mapped[int] = mapped_column(Integer, default=0)
    video_count: Mapped[int] = mapped_column(Integer, default=0)
    thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    uploads_playlist_id: Mapped[str | None] = mapped_column(String(64))
    last_rss_poll: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_full_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    niches: Mapped[list[Niche]] = relationship("Niche", secondary=niche_channels, back_populates="competitor_channels")
    videos: Mapped[list["Video"]] = relationship("Video", back_populates="channel", cascade="all, delete-orphan")

    @property
    def rss_feed_url(self) -> str:
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={self.youtube_channel_id}"
