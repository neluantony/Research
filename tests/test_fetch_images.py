"""Tests for the imagery fetcher's pure parts (no network, no DB, no key)."""
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ingest.fetch_images import (FOV, HEADINGS, PRESENTATION_SCHEME, SIZE,
                                 view_path, view_url)


def test_headings_tile_the_full_circle():
    assert HEADINGS == (0, 90, 180, 270)
    assert FOV == 90                      # 4 x 90 = 360, no gaps, no overlap


def test_view_url_pins_pano_and_requests_error_codes():
    q = parse_qs(urlparse(view_url("PANO123", 90, key="K")).query)
    assert q["pano"] == ["PANO123"]       # addressed by pano_id, not lat/lng
    assert q["heading"] == ["90"]
    assert q["pitch"] == ["0"]
    assert q["fov"] == [str(FOV)]
    assert q["size"] == [SIZE]
    assert q["return_error_code"] == ["true"]   # dead pano -> 404, not grey JPEG
    assert q["key"] == ["K"]


def test_view_path_layout():
    p = view_path(Path("data/images"), "paris", "PANOX", 0)
    assert p == Path("data/images/paris/PANOX/h000.jpg")
    assert view_path(Path("x"), "rome", "P", 270).name == "h270.jpg"


def test_presentation_scheme_label_is_versioned():
    # the label is stored on every views row; changing the scheme must change it
    assert PRESENTATION_SCHEME == "cardinal4_fov90_640_v1"
