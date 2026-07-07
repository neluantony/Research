"""Tests for the Mapillary probe's pure parts (no network, no token)."""
import math

from ingest.mapillary import bbox_around, parse_images_response


def test_bbox_is_centred_and_sized():
    lon, lat = 2.35, 48.85
    minx, miny, maxx, maxy = bbox_around(lon, lat, radius_m=50)
    assert minx < lon < maxx and miny < lat < maxy
    # ~50 m half-height in degrees latitude
    assert math.isclose((maxy - miny) / 2 * 111_320, 50, rel_tol=0.01)
    # longitude half-width widens with latitude
    assert (maxx - minx) > (maxy - miny)


def test_bbox_survives_polar_latitudes():
    minx, _, maxx, _ = bbox_around(0.0, 89.9999, radius_m=50)
    assert maxx > minx  # cos(lat) floor prevents a degenerate/inverted box


def test_parse_empty_response():
    assert parse_images_response({"data": []}) == (False, False)
    assert parse_images_response({}) == (False, False)


def test_parse_pano_detection():
    flat = {"data": [{"id": "1", "is_pano": False}, {"id": "2"}]}
    pano = {"data": [{"id": "1", "is_pano": False}, {"id": "2", "is_pano": True}]}
    assert parse_images_response(flat) == (True, False)
    assert parse_images_response(pano) == (True, True)
