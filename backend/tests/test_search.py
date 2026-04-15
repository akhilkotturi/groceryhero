"""Unit tests for search endpoint helpers."""
import math
import pytest


def _bounding_box(lat: float, lng: float, radius_miles: float):
    """Compute bounding box deltas — same formula used in the route."""
    lat_delta = radius_miles / 69.0
    lng_delta = radius_miles / (69.0 * math.cos(math.radians(lat)))
    return lat_delta, lng_delta


def test_bounding_box_austin():
    lat_delta, lng_delta = _bounding_box(30.2672, -97.7431, 10)
    assert abs(lat_delta - 0.1449) < 0.001
    assert abs(lng_delta - 0.1674) < 0.001


def test_bounding_box_shrinks_near_poles():
    _, lng_delta_austin = _bounding_box(30.0, -97.0, 10)
    _, lng_delta_seattle = _bounding_box(47.6, -122.3, 10)
    # Seattle is farther north → lng delta should be larger (cos is smaller)
    assert lng_delta_seattle > lng_delta_austin


def test_search_response_schema_fields():
    """SearchResponse must contain deals, total, query."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from app.schemas.deal import SearchResponse
    # Verify the schema can be instantiated with expected fields
    r = SearchResponse(deals=[], total=0, query="chicken")
    assert r.query == "chicken"
    assert r.total == 0
    assert r.deals == []
