"""APScheduler setup — all background jobs registered here."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from nichescope.jobs.compute_gaps import compute_all_gaps
from nichescope.jobs.detect_anomalies import detect_anomalies
from nichescope.jobs.enrich_videos import enrich_new_videos
from nichescope.jobs.poll_rss import poll_all_rss
from nichescope.jobs.send_briefs import send_all_briefs

logger = logging.getLogger(__name__)


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the background job scheduler."""
    scheduler = AsyncIOScheduler()

    # RSS polling — every 15 minutes (zero API quota)
    scheduler.add_job(poll_all_rss, "interval", minutes=15, id="poll_rss", name="RSS Poller")

    # Video enrichment — every hour (uses API quota sparingly)
    scheduler.add_job(enrich_new_videos, "interval", hours=1, id="enrich_videos", name="Video Enricher")

    # Gap computation — daily at 3 AM UTC
    scheduler.add_job(compute_all_gaps, "cron", hour=3, id="compute_gaps", name="Gap Computer")

    # Daily briefs — every hour (sends to users whose brief_time matches)
    scheduler.add_job(send_all_briefs, "interval", hours=1, id="send_briefs", name="Brief Sender")

    # Anomaly detection — every hour
    scheduler.add_job(detect_anomalies, "interval", hours=1, id="detect_anomalies", name="Anomaly Detector")

    logger.info("Scheduler configured with %d jobs", len(scheduler.get_jobs()))
    return scheduler
