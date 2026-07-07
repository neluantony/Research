"""Tests for the OSM function/heritage core (pure; no pyrosm, no network).

Geometry here is an abstract metric plane (unit = metre); the 'buffer' is a
square standing in for the 150 m window around a point.
"""
from shapely.geometry import Polygon, Point

from ingest.osm import point_function, point_heritage

# A 300 m square 'buffer' centred near the origin.
BUFFER = Polygon([(-150, -150), (-150, 150), (150, 150), (150, -150)])


def _sq(x0, y0, s):
    return Polygon([(x0, y0), (x0, y0 + s), (x0 + s, y0 + s), (x0 + s, y0)])


def test_residential_only():
    landuse = [(_sq(-100, -100, 200), "residential")]
    assert point_function(BUFFER, landuse) == "residential"


def test_commercial_only():
    landuse = [(_sq(-100, -100, 200), "commercial")]
    assert point_function(BUFFER, landuse) == "commercial"


def test_commercial_beats_residential_by_area():
    landuse = [(_sq(-150, -150, 300), "commercial"),   # fills buffer
               (_sq(-150, -150, 80), "residential")]   # small corner
    assert point_function(BUFFER, landuse) == "commercial"


def test_poi_fallback_when_no_landuse():
    assert point_function(BUFFER, [], commercial_poi_count=6) == "commercial"
    assert point_function(BUFFER, [], commercial_poi_count=2) == "industrial_other"


def test_shop_density_upgrades_residential_to_commercial():
    # a high-street: residential landuse but a dense shop/office cluster -> commercial
    landuse = [(_sq(-100, -100, 200), "residential")]
    assert point_function(BUFFER, landuse, commercial_poi_count=6) == "commercial"
    # below the threshold it stays residential
    assert point_function(BUFFER, landuse, commercial_poi_count=2) == "residential"


def test_industrial_or_empty_is_other():
    landuse = [(_sq(-100, -100, 200), "industrial")]
    assert point_function(BUFFER, landuse) == "industrial_other"
    assert point_function(BUFFER, []) == "industrial_other"


def test_heritage_detection():
    near = [Point(10, 10).buffer(5)]
    far = [Point(1000, 1000).buffer(5)]
    assert point_heritage(BUFFER, near) is True
    assert point_heritage(BUFFER, far) is False
    assert point_heritage(BUFFER, []) is False
