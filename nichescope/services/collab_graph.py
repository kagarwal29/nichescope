"""Collaboration graph service (stub)."""
import re
from dataclasses import dataclass, field

COLLAB_PATTERNS = [re.compile(r'feat\.|ft\.|x ', re.I)]

@dataclass
class CollabOpportunity:
    channel_title: str
    handle: str
    subscriber_count: int
    topic_overlap_score: float
    audience_overlap_estimate: str
    existing_collabs: int
    potential_reach: int
    shared_topics: list = field(default_factory=list)
    reason: str = ""

async def find_collab_opportunities(session, niche_id, user_channel_id=None):
    """Find collab opportunities."""
    return []
