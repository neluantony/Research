"""Tests for the stage-B pure logic (selection + neighbourhood quota fill)."""
from ingest.stage_b import fill_neighbourhood, pick_neighbourhoods


def _cands(n, lon0=35.9):
    return [{"lon": lon0 + i * 1e-4, "lat": 31.9, "stratum": "dense_residential"}
            for i in range(n)]


def _snap_ok(prefix="p"):
    counter = {"i": 0}

    def snap(lon, lat):
        counter["i"] += 1
        return {"status": "OK", "official": True, "pano_id": f"{prefix}{counter['i']}",
                "lon": lon, "lat": lat, "date": "2023-06"}
    return snap


# --- selection ---------------------------------------------------------------

def test_selection_deterministic_and_sorted():
    ids = list(range(100, 140))
    a = pick_neighbourhoods(ids, 12, seed=20260622, city_id="paris")
    b = pick_neighbourhoods(list(reversed(ids)), 12, seed=20260622, city_id="paris")
    assert a == b == sorted(a)          # row order cannot leak in
    assert len(a) == 12 and set(a) <= set(ids)


def test_selection_differs_by_city_and_seed():
    ids = list(range(40))
    assert pick_neighbourhoods(ids, 12, 20260622, "paris") \
        != pick_neighbourhoods(ids, 12, 20260622, "rome")
    assert pick_neighbourhoods(ids, 12, 20260622, "paris") \
        != pick_neighbourhoods(ids, 12, 1, "paris")


def test_selection_takes_all_when_fewer_than_k():
    ids = [5, 3, 9]
    assert pick_neighbourhoods(ids, 12, 20260622, "bengaluru") == [3, 5, 9]


# --- quota fill ----------------------------------------------------------------

def test_fill_stops_at_need():
    acc, stats = fill_neighbourhood(_cands(50), need=7, snap_fn=_snap_ok(),
                                    used_panos=set())
    assert len(acc) == 7 and stats["accepted"] == 7
    assert stats["tried"] == 7          # stops as soon as the need is met


def test_fill_dedupes_against_city_panos():
    used = {"p1", "p2", "p3"}           # already taken by stage A
    acc, stats = fill_neighbourhood(_cands(10), need=5, snap_fn=_snap_ok(),
                                    used_panos=used)
    assert len(acc) == 5
    assert stats["duplicate_pano"] == 3
    assert {p["pano_id"] for p in acc}.isdisjoint({"p1", "p2", "p3"})
    assert len(used) == 8               # mutated: city-wide dedup carries over


def test_fill_records_shortfall_via_stats():
    def never(lon, lat):
        return {"status": "ZERO_RESULTS", "official": False, "pano_id": None}
    acc, stats = fill_neighbourhood(_cands(30), need=5, snap_fn=never,
                                    used_panos=set())
    assert acc == []
    assert stats["no_pano"] == 30 and stats["tried"] == 30


def test_fill_rejection_buckets_partition_tried():
    counter = {"i": 0}

    def mixed(lon, lat):
        counter["i"] += 1
        i = counter["i"]
        if i % 4 == 0:
            return {"status": "ZERO_RESULTS", "official": False, "pano_id": None}
        if i % 4 == 1:
            return {"status": "OK", "official": False, "pano_id": f"u{i}",
                    "lon": lon, "lat": lat, "date": None}
        if i % 4 == 2:
            return {"status": "OK", "official": True, "pano_id": "DUP",
                    "lon": lon, "lat": lat, "date": None}
        return {"status": "OK", "official": True, "pano_id": f"far{i}",
                "lon": lon + 1.0, "lat": lat, "date": None}

    acc, st = fill_neighbourhood(_cands(40), need=99, snap_fn=mixed,
                                 used_panos=set())
    assert st["accepted"] + st["no_pano"] + st["unofficial"] \
        + st["duplicate_pano"] + st["too_far"] == st["tried"] == 40
    assert len(acc) == 1                # the first DUP is accepted, the rest collide
