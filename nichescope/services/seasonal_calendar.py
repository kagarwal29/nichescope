"""Seasonal content calendar service (stub)."""
from dataclasses import dataclass

MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June", 
               "July", "August", "September", "October", "November", "December"]

@dataclass
class SeasonalPattern:
    topic_label: str
    topic_id: int
    monthly_index: dict
    peak_month: int
    peak_multiplier: float
    trough_month: int
    is_seasonal: bool
    confidence: float

@dataclass
class CalendarEntry:
    topic_label: str
    recommended_publish_window: str
    peak_month: str
    peak_multiplier: float
    reason: str
    urgency: str

async def generate_content_calendar(session, niche_id, lookahead_weeks=8):
    """Generate seasonal content calendar."""
    return []
