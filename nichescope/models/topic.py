"""TopicCluster and GapScore models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nichescope.models.base import Base


class TopicCluster(Base):
    """A cluster of videos about the same topic within a niche."""

    __tablename__ = "topic_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    niche_id: Mapped[int] = mapped_column(Integer, ForeignKey("niches.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(200))  # e.g. "meal prep", "air fryer"
    keywords: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of top terms
    video_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_views: Mapped[float] = mapped_column(Float, default=0.0)
    avg_views_30d: Mapped[float] = mapped_column(Float, default=0.0)
    trend_direction: Mapped[str] = mapped_column(String(10), default="stable")  # up | down | stable
    last_computed: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    niche = relationship("Niche")
    videos: Mapped[list] = relationship("Video", back_populates="topic_cluster")
    gap_scores: Mapped[list["GapScore"]] = relationship("GapScore", back_populates="topic_cluster")


class GapScore(Base):
    """Daily snapshot of content gap opportunities for a user × topic."""

    __tablename__ = "gap_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    topic_cluster_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("topic_clusters.id", ondelete="CASCADE")
    )
    niche_id: Mapped[int] = mapped_column(Integer, ForeignKey("niches.id", ondelete="CASCADE"))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    demand_score: Mapped[float] = mapped_column(Float, default=0.0)
    supply_score: Mapped[float] = mapped_column(Float, default=0.0)
    user_coverage: Mapped[int] = mapped_column(Integer, default=0)
    recency_boost: Mapped[float] = mapped_column(Float, default=1.0)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    topic_cluster = relationship("TopicCluster", back_populates="gap_scores")
