"""Video model — a single YouTube video."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nichescope.models.base import Base


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    youtube_video_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    channel_id: Mapped[int] = mapped_column(Integer, ForeignKey("channels.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    thumbnail_url: Mapped[str | None] = mapped_column(String(500))
    last_stats_update: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Derived fields (computed by jobs)
    topic_cluster_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("topic_clusters.id", ondelete="SET NULL"), nullable=True
    )
    views_per_day: Mapped[float] = mapped_column(Float, default=0.0)

    # Relationships
    channel = relationship("Channel", back_populates="videos")
    topic_cluster = relationship("TopicCluster", back_populates="videos")

    def compute_views_per_day(self) -> float:
        if not self.published_at:
            return 0.0
        days = max((datetime.utcnow() - self.published_at.replace(tzinfo=None)).days, 1)
        return self.view_count / days
