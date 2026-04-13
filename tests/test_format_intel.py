"""Tests for Format Intelligence service."""
from nichescope.services.format_intel import classify_format, classify_duration, DURATION_BUCKETS

def test_tutorial(): assert classify_format("How to Make Sourdough Bread") == "tutorial"
def test_listicle(): assert classify_format("10 Best Kitchen Gadgets") == "listicle"
def test_review(): assert classify_format("iPhone 16 Honest Review") == "review"
def test_challenge(): assert classify_format("$1 vs $100 Steak Challenge") == "challenge"
def test_vlog(): assert classify_format("A Day in My Life as a Chef") == "vlog"
def test_reaction(): assert classify_format("Reacting to TikTok Recipes") == "reaction"
def test_other(): assert classify_format("Random Things Happening") == "other"
def test_short(): assert classify_duration(120) == "short (<5m)"
def test_medium(): assert classify_duration(600) == "medium (5-15m)"
def test_long(): assert classify_duration(1500) == "long (15-30m)"
def test_extra_long(): assert classify_duration(3600) == "extra_long (30m+)"
def test_buckets_contiguous():
    for i in range(len(DURATION_BUCKETS) - 1):
        assert DURATION_BUCKETS[i][2] == DURATION_BUCKETS[i+1][1]
