"""Tests for the admin-level selector (pure; synthetic polygons, no OSM/DB).

The two reference cases from the recon:
  * paris-like: an in-band level tiling only the core must beat an
    out-of-band level tiling the whole frame;
  * london-like: an in-band level of scattered fringe units (GB civil
    parishes) must LOSE to a near-band level that contains the centre.
"""
from shapely.geometry import Point, box

from ingest.neighbourhoods import BAND, MIN_UNITS, select_level

FRAME = box(0.0, 0.0, 1.0, 1.0)
CENTRE = Point(0.5, 0.5)


def _grid(minx, miny, maxx, maxy, nx, ny, prefix):
    """nx*ny named tiles filling the given box."""
    dx, dy = (maxx - minx) / nx, (maxy - miny) / ny
    return [(box(minx + i * dx, miny + j * dy, minx + (i + 1) * dx, miny + (j + 1) * dy),
             f"{prefix}_{i}_{j}")
            for i in range(nx) for j in range(ny)]


def test_paris_case_in_band_core_beats_out_of_band_full_tiling():
    levels = {
        "8": _grid(0, 0, 1, 1, 17, 17, "commune"),          # 289 units, full coverage
        "9": _grid(0.3, 0.3, 0.7, 0.7, 5, 4, "arrondissement"),  # 20 units, core only
    }
    chosen, rep = select_level(levels, FRAME, CENTRE)
    assert chosen == "9"
    assert rep["9"]["in_band"] and rep["9"]["chosen"]
    assert not rep["8"]["in_band"]


def test_london_case_fringe_units_rejected_without_centre():
    levels = {
        "8": _grid(0, 0, 1, 1, 7, 7, "borough"),            # 49 units, just over band
        "10": _grid(0.0, 0.0, 0.3, 1.0, 3, 10, "parish"),   # 30 units, fringe strip only
    }
    chosen, rep = select_level(levels, FRAME, CENTRE)
    assert chosen == "8"                     # parishes miss the centre AND the coverage bar
    assert "does not contain the city centre" in rep["10"]["rejected"]


def test_muscat_case_high_coverage_qualifies_without_centre():
    # centre just OUTSIDE the frame (GHSL frame matched by 'nearest'): a level
    # tiling 90% of the frame must still qualify
    offside_centre = Point(1.05, 0.5)
    levels = {"8": _grid(0, 0, 0.9, 1.0, 6, 6, "wilayat")}   # 36 units, 90% coverage
    chosen, rep = select_level(levels, FRAME, offside_centre)
    assert chosen == "8"
    assert not rep["8"]["contains_centre"] and rep["8"]["coverage"] >= 0.5


def test_no_level_in_band_picks_closest_to_band():
    levels = {
        "6": _grid(0, 0, 1, 1, 3, 3, "district"),           # 9 units (6 under band floor)
        "8": _grid(0, 0, 1, 1, 12, 12, "ward"),             # 144 units (104 over band)
    }
    chosen, _rep = select_level(levels, FRAME, CENTRE)
    assert chosen == "6"


def test_too_few_units_is_rejected():
    levels = {"4": _grid(0, 0, 1, 1, 2, 2, "province")}     # 4 < MIN_UNITS
    chosen, rep = select_level(levels, FRAME, CENTRE)
    assert chosen is None
    assert "fewer than" in rep["4"]["rejected"]
    assert MIN_UNITS > 4


def test_empty_levels_returns_none():
    chosen, rep = select_level({}, FRAME, CENTRE)
    assert chosen is None and rep == {}


def test_coverage_breaks_ties_between_in_band_levels():
    levels = {
        "7": _grid(0, 0, 1, 1, 5, 4, "full"),               # 20 units, full coverage
        "9": _grid(0.25, 0.25, 0.75, 0.75, 5, 4, "core"),   # 20 units, quarter coverage
    }
    chosen, _rep = select_level(levels, FRAME, CENTRE)
    assert chosen == "7"

    band_report = select_level(levels, FRAME, CENTRE)[1]
    assert band_report["7"]["coverage"] > band_report["9"]["coverage"]


def test_band_matches_codebook():
    assert BAND == (15, 40)   # codebook neighbourhood.target_granularity_units_per_city
