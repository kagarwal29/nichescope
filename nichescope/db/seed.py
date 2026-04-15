"""Database seeding for development."""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nichescope.models import Channel, Niche, TopicCluster, User, Video
from nichescope.models.channel import niche_channels

logger = logging.getLogger(__name__)


async def seed_dev_data(db: AsyncSession):
    """Seed minimal test data for development."""
    # Check if data exists
    from sqlalchemy import select

    count_stmt = select(User)
    result = await db.execute(count_stmt)
    if result.first():
        return  # Data already exists

    now = datetime.now(timezone.utc)

    # Create test user
    user = User(
        telegram_chat_id=123456,
        tier="free",
        youtube_channel_id="UCtest123",
    )
    db.add(user)
    await db.flush()

    # Create test niche
    niche = Niche(
        user_id=user.id,
        name="Tech Reviews",
        seed_keywords=json.dumps(["tech", "gadgets", "reviews"]),
    )
    db.add(niche)
    await db.flush()

    # Create competitor channels
    channel1 = Channel(
        youtube_channel_id="UC1test",
        title="Tech Reviewer One",
        handle="@techreviewer1",
        subscriber_count=50000,
        video_count=120,
        last_full_sync=now,
    )
    channel2 = Channel(
        youtube_channel_id="UC2test",
        title="Tech Reviewer Two",
        handle="@techreviewer2",
        subscriber_count=75000,
        video_count=180,
        last_full_sync=now,
    )
    db.add(channel1)
    db.add(channel2)
    await db.flush()

    # Link channels to niche using direct SQL to avoid relationship loading
    await db.execute(insert(niche_channels).values(niche_id=niche.id, channel_id=channel1.id))
    await db.execute(insert(niche_channels).values(niche_id=niche.id, channel_id=channel2.id))

    # Create topic clusters
    cluster1 = TopicCluster(
        niche_id=niche.id,
        label="Smartphone Reviews",
        keywords=json.dumps(["iphone", "android", "smartphone", "review"]),
        video_count=45,
        avg_views=25000,
        avg_views_30d=27000,
        trend_direction="up",
    )
    cluster2 = TopicCluster(
        niche_id=niche.id,
        label="Laptop Comparisons",
        keywords=json.dumps(["laptop", "macbook", "windows", "comparison"]),
        video_count=30,
        avg_views=18000,
        avg_views_30d=19000,
        trend_direction="stable",
    )
    db.add(cluster1)
    db.add(cluster2)
    await db.flush()

    # Create sample videos
    for i in range(10):
        video = Video(
            channel_id=channel1.id,
            youtube_video_id=f"vid{i}_ch1",
            title=f"Tech Review #{i+1}",
            description=f"A review of tech gadget #{i+1}",
            published_at=now,
            view_count=20000 + i * 1000,
            like_count=500 + i * 50,
            comment_count=100 + i * 10,
            duration_seconds=600 + i * 60,
            topic_cluster_id=cluster1.id if i < 5 else cluster2.id,
        )
        db.add(video)

    for i in range(10):
        video = Video(
            channel_id=channel2.id,
            youtube_video_id=f"vid{i}_ch2",
            title=f"Gadget Comparison #{i+1}",
            description=f"Compare gadget #{i+1}",
            published_at=now,
            view_count=22000 + i * 1200,
            like_count=550 + i * 60,
            comment_count=120 + i * 12,
            duration_seconds=650 + i * 70,
            topic_cluster_id=cluster2.id if i < 5 else cluster1.id,
        )
        db.add(video)

    await db.commit()
    logger.info(f"Dev data seeded. User API key: {user.api_key}")
