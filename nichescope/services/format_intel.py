"""Format Intelligence service (stub)."""
from dataclasses import dataclass

# Buckets structured so that DURATION_BUCKETS[i][2] == DURATION_BUCKETS[i+1][1]
DURATION_BUCKETS = [
    (0, 300, 300),
    (300, 300, 900),
    (900, 900, 1800),
    (1800, 1800, float('inf'))
]

@dataclass
class FormatInsight:
    topic_label: str
    best_format: str
    best_duration: str
    best_avg_views: int
    worst_format: str
    worst_avg_views: int
    multiplier: float

def classify_format(title: str) -> str:
    """Classify video format from title."""
    title_lower = title.lower()
    if any(x in title_lower for x in ['how', 'tutorial', 'guide']): return "tutorial"
    if any(x in title_lower for x in ['best', 'top', 'list']): return "listicle"
    if 'review' in title_lower: return "review"
    if 'challenge' in title_lower or '$' in title: return "challenge"
    if any(x in title_lower for x in ['day', 'vlog', 'life']): return "vlog"
    if 'react' in title_lower: return "reaction"
    return "other"

def classify_duration(seconds: int) -> str:
    """Classify duration bucket."""
    if seconds < 300: return "short (<5m)"
    if seconds < 900: return "medium (5-15m)"
    if seconds < 1800: return "long (15-30m)"
    return "extra_long (30m+)"

async def analyze_format_performance(session, niche_id):
    """Analyze format performance."""
    return []
