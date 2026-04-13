"""Comment demand mining service (stub)."""
import re
from dataclasses import dataclass, field

REQUEST_PATTERNS = [re.compile(r'can you|please|would you|could you|video idea|you should', re.I)]
NOISE_PATTERNS = [re.compile(r'subscribe|like|pin|first', re.I)]

@dataclass
class DemandSignal:
    raw_text: str
    extracted_topic: str
    video_title: str
    video_id: str
    channel_title: str
    like_count: int

@dataclass
class DemandCluster:
    topic: str
    request_count: int = 0
    total_likes: int = 0
    strength_score: float = 0.0
    source_channels: list = field(default_factory=list)
    example_requests: list = field(default_factory=list)

async def mine_comment_demands(session, niche_id, max_videos=15):
    """Mine demand signals from comments."""
    return []

def _cluster_demands(signals):
    """Cluster demand signals by topic."""
    if not signals:
        return []
    
    clusters = {}
    for sig in signals:
        topic = sig.extracted_topic
        if topic not in clusters:
            clusters[topic] = DemandCluster(
                topic=topic,
                request_count=0,
                total_likes=0,
                strength_score=0.0,
                source_channels=[],
                example_requests=[]
            )
        c = clusters[topic]
        c.request_count += 1
        c.total_likes += sig.like_count
        if sig.channel_title not in c.source_channels:
            c.source_channels.append(sig.channel_title)
        if len(c.example_requests) < 2:
            c.example_requests.append(sig.raw_text)
        c.strength_score = min(100, c.request_count * 10)
    
    return list(clusters.values())
