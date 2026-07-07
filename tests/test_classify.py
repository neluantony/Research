"""Regression test for the strata assembler (synthetic geometry; no DB, no .pbf).

Uses a small lon/lat box split into a commercial half and a residential half, so
the test runs without the GeoPackage or OSM extract but still exercises
reprojection, the 150 m buffer, tertile zoning and the strata rule end to end.
"""
from shapely.geometry import Polygon

from ingest.classify import classify_city_points
from ingest.strata import STRATA

# ~5.5 x 5.5 km box near Amman's latitude (so UTM reprojection is realistic).
_X0, _Y0, _D = 35.90, 31.90, 0.05
FRAME = Polygon([(_X0, _Y0), (_X0, _Y0 + _D), (_X0 + _D, _Y0 + _D), (_X0 + _D, _Y0)])
_MIDX = _X0 + _D / 2
COMMERCIAL_HALF = Polygon([(_X0, _Y0), (_X0, _Y0 + _D), (_MIDX, _Y0 + _D), (_MIDX, _Y0)])
RESIDENTIAL_HALF = Polygon([(_MIDX, _Y0), (_MIDX, _Y0 + _D), (_X0 + _D, _Y0 + _D), (_X0 + _D, _Y0)])
OSM = {
    "landuse": [(COMMERCIAL_HALF, "commercial"), (RESIDENTIAL_HALF, "residential")],
    "commercial": [],
    "heritage": [],
}


def test_classifies_all_points_into_valid_strata():
    res = classify_city_points(FRAME, OSM, n=100, seed=1)
    assert len(res) == 100
    assert all(r["stratum"] in STRATA for r in res)


def test_reproducible():
    a = classify_city_points(FRAME, OSM, n=100, seed=1)
    b = classify_city_points(FRAME, OSM, n=100, seed=1)
    assert [r["stratum"] for r in a] == [r["stratum"] for r in b]


def test_both_functions_present_across_the_split():
    res = classify_city_points(FRAME, OSM, n=200, seed=3)
    functions = {r["function"] for r in res}
    assert "commercial" in functions and "residential" in functions


def test_points_lie_inside_the_frame():
    res = classify_city_points(FRAME, OSM, n=100, seed=2)
    assert all(_X0 <= r["lon"] <= _X0 + _D and _Y0 <= r["lat"] <= _Y0 + _D for r in res)


def test_density_fn_receives_lonlat_and_shifts_zones():
    """density_fn is called with lon/lat (not metric coords) and feeds innerness."""
    seen = []

    def density_east_is_dense(lon, lat):
        seen.append((lon, lat))
        return 100.0 if lon > _MIDX else 0.0   # all built-up density in the east half

    res = classify_city_points(FRAME, OSM, n=150, seed=4,
                               density_fn=density_east_is_dense)
    # calls were made in lon/lat (inside the frame box, not UTM metres)
    assert seen and all(_X0 - 1 <= x <= _X0 + _D + 1 and _Y0 - 1 <= y <= _Y0 + _D + 1
                        for x, y in seen)
    # zoning must differ from the centrality-only run: the dense east half
    # pulls innerness (and hence core/mid zones) eastward
    base = classify_city_points(FRAME, OSM, n=150, seed=4)
    assert [r["zone"] for r in res] != [r["zone"] for r in base]


def test_density_fn_reproducible_with_ties():
    def flat(lon, lat):
        return 1.0                              # all-tied density values
    a = classify_city_points(FRAME, OSM, n=100, seed=5, density_fn=flat)
    b = classify_city_points(FRAME, OSM, n=100, seed=5, density_fn=flat)
    assert [r["stratum"] for r in a] == [r["stratum"] for r in b]
