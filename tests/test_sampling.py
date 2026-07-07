"""Tests for the reproducible point-sampling engine (no DB, no network)."""
import pytest
from shapely.geometry import Polygon, MultiPolygon

from ingest.sampling import sample_points_in_polygon

UNIT_SQUARE = Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])


def _p(xy):
    from shapely.geometry import Point
    return Point(xy)


def test_count_and_containment():
    pts = sample_points_in_polygon(UNIT_SQUARE, 200, seed=42)
    assert len(pts) == 200
    assert all(UNIT_SQUARE.contains(_p(xy)) for xy in pts)


def test_reproducible_same_seed():
    a = sample_points_in_polygon(UNIT_SQUARE, 50, seed=7)
    b = sample_points_in_polygon(UNIT_SQUARE, 50, seed=7)
    assert a == b  # exact reproducibility


def test_different_seed_differs():
    a = sample_points_in_polygon(UNIT_SQUARE, 50, seed=7)
    b = sample_points_in_polygon(UNIT_SQUARE, 50, seed=8)
    assert a != b


def test_respects_holes_and_multipolygon():
    # Two disjoint unit squares; every point must fall in one of them.
    left = Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])
    right = Polygon([(2, 0), (2, 1), (3, 1), (3, 0)])
    mp = MultiPolygon([left, right])
    pts = sample_points_in_polygon(mp, 100, seed=1)
    assert len(pts) == 100
    assert all(left.contains(_p(xy)) or right.contains(_p(xy)) for xy in pts)
    # the empty gap (1<x<2) must never be sampled
    assert all(not (1 < xy[0] < 2) for xy in pts)


def test_empty_geometry_raises():
    with pytest.raises(ValueError):
        sample_points_in_polygon(Polygon(), 10, seed=0)
