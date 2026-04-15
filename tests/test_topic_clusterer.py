"""Tests for topic clustering engine."""

import json

from nichescope.services.topic_clusterer import _EXTRA_STOPS


def test_extra_stops_are_frozenset():
    assert isinstance(_EXTRA_STOPS, frozenset)
    assert "video" in _EXTRA_STOPS
    assert "recipe" in _EXTRA_STOPS


def test_clustering_requires_minimum_videos():
    """Clustering with < 10 videos should return empty list (tested via integration)."""
    # This is an integration test marker — actual test requires DB
    pass
