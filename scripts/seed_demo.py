"""Seed script — populate database with demo data for testing."""

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from random import choice, gauss, randint

from nichescope.models import (
    Base,
    Channel,
    GapScore,
    Niche,
    TopicCluster,
    User,
    Video,
    async_session,
    engine,
)


# Demo data
DEMO_CHANNELS = [
    {"youtube_channel_id": "UCVHFbqXqoYvEWM1Ddxl0QDg", "title": "Adam Ragusea", "handle": "@aragusea", "subscriber_count": 2_100_000},
    {"youtube_channel_id": "UCbpMy0Fg74eXXkvxJrtEn3w", "title": "Joshua Weissman", "handle": "@joshuaweissman", "subscriber_count": 9_400_000},
    {"youtube_channel_id": "UCJHA_jMfCvEnv-3kRjTCQXw", "title": "Binging with Babish", "handle": "@babishculinaryuniverse", "subscriber_count": 10_000_000},
    {"youtube_channel_id": "UCRIZtPl9nb9RiXc9btSTQNw", "title": "Food Wishes", "handle": "@foodwishes", "subscriber_count": 4_300_000},
    {"youtube_channel_id": "UCsQoLyqf91XWLA5EyhPyUDg", "title": "Ethan Chlebowski", "handle": "@ethanchlebowski", "subscriber_count": 1_800_000},
]

TOPICS = ["meal prep", "air fryer", "budget meals", "one pot pasta", "bread baking",
           "knife skills", "grilling", "fermentation", "ramen", "desserts", "steak",
           "sous vide", "pizza dough", "kitchen tools review", "5 minute meals"]


async def seed():
    """Create demo user, niche, channels, videos, and gap scores."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        # Create demo user
        user = User(
            telegram_chat_id=123456789,
            youtube_channel_id="UC_demo_channel",
            api_key="demo-api-key-for-testing",
            tier="pro",
        )
        session.add(user)
        await session.flush()

        # Create niche
        niche = Niche(
            user_id=user.id,
            name="Home Cooking",
            seed_keywords=json.dumps(["cooking", "recipes", "home chef"]),
        )
        session.add(niche)
        await session.flush()

        # Create channels + link to niche
        channels = []
        for ch_data in DEMO_CHANNELS:
            ch = Channel(
                uploads_playlist_id=f"UU{ch_data['youtube_channel_id'][2:]}",
                video_count=randint(100, 500),
                **ch_data,
            )
            session.add(ch)
            await session.flush()
            niche.competitor_channels.append(ch)
            channels.append(ch)

        # Create topic clusters
        now = datetime.now(timezone.utc)
        clusters = []
        for topic in TOPICS:
            tc = TopicCluster(
                niche_id=niche.id,
                label=topic,
                keywords=json.dumps(topic.split()),
                video_count=randint(5, 30),
                avg_views=randint(50_000, 500_000),
                avg_views_30d=randint(40_000, 600_000),
                trend_direction=choice(["up", "stable", "down"]),
                last_computed=now,
            )
            session.add(tc)
            await session.flush()
            clusters.append(tc)

        # Create videos for each channel
        for ch in channels:
            for i in range(randint(30, 60)):
                days_ago = randint(1, 365)
                views = max(1000, int(gauss(200_000, 150_000)))
                v = Video(
                    youtube_video_id=f"demo_{ch.id}_{i}",
                    channel_id=ch.id,
                    title=f"{choice(TOPICS).title()} — {ch.title} #{i}",
                    description=f"Demo video about {choice(TOPICS)} by {ch.title}",
                    tags=json.dumps([choice(TOPICS) for _ in range(3)]),
                    published_at=now - timedelta(days=days_ago),
                    view_count=views,
                    like_count=views // 20,
                    comment_count=views // 100,
                    duration_seconds=randint(300, 1800),
                    topic_cluster_id=choice(clusters).id,
                    views_per_day=views / max(days_ago, 1),
                    last_stats_update=now,
                )
                session.add(v)

        # Create gap scores
        for tc in clusters:
            supply = tc.video_count / 100
            user_coverage = randint(0, 2)
            recency = 1.5 if tc.trend_direction == "up" else 1.0
            score = (tc.avg_views * recency) / (supply * (user_coverage + 1)) if supply > 0 else 0

            gap = GapScore(
                user_id=user.id,
                topic_cluster_id=tc.id,
                niche_id=niche.id,
                score=score,
                demand_score=tc.avg_views,
                supply_score=supply,
                user_coverage=user_coverage,
                recency_boost=recency,
            )
            session.add(gap)

        await session.commit()
        print(f"Seeded: 1 user, 1 niche, {len(channels)} channels, {len(clusters)} topics")
        print(f"API Key: demo-api-key-for-testing")


if __name__ == "__main__":
    asyncio.run(seed())
