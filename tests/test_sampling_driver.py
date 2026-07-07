"""Tests for the quota-fill logic (pure; mock snap, no network, no DB)."""
from ingest.sampling_driver import fill_quotas, haversine_m
from ingest.strata import STRATA


def _candidates(strata, per_pool=50):
    out = []
    for s in strata:
        for i in range(per_pool):
            out.append({"lon": 35.9 + i * 1e-4, "lat": 31.9, "stratum": s})
    return out


def _snap_every_nth(n):
    """Mock snap: succeeds for ~1/n of points, each with a unique pano nearby."""
    counter = {"i": 0}

    def snap(lon, lat):
        counter["i"] += 1
        if counter["i"] % n == 0:
            return {"status": "OK", "official": True,
                    "pano_id": f"p{counter['i']}", "lon": lon, "lat": lat, "date": "2022-05"}
        return {"status": "ZERO_RESULTS", "official": False, "pano_id": None}

    return snap


def test_fills_quota_all_strata():
    acc, short, _stats = fill_quotas(_candidates(STRATA), per_stratum=10, snap_fn=_snap_every_nth(2))
    assert len(acc) == 50            # 10 per stratum x 5 strata
    assert short == {}
    assert all("pano_id" in p and "snap_distance_m" in p for p in acc)


def test_absent_stratum_is_full_shortfall():
    # only 2 strata have candidates -> the other 3 are recorded as full shortfalls
    acc, short, stats = fill_quotas(
        _candidates(["dense_residential", "commercial_business"]),
        per_stratum=10, snap_fn=_snap_every_nth(2))
    assert len(acc) == 20
    for s in ("historic_iconic_core", "low_density_suburban_residential", "peripheral_edge"):
        assert short[s] == 10
        assert stats[s]["candidates"] == 0   # absent stratum still gets a stats row


def test_records_shortfall_when_coverage_too_sparse():
    acc, short, _stats = fill_quotas(_candidates(["dense_residential"], 50),
                                     per_stratum=10, snap_fn=_snap_every_nth(100))
    assert short.get("dense_residential", 0) > 0


def test_dedupes_by_pano_id():
    def same_pano(lon, lat):
        return {"status": "OK", "official": True, "pano_id": "DUP",
                "lon": lon, "lat": lat, "date": "2020-01"}
    acc, short, stats = fill_quotas(_candidates(STRATA), per_stratum=10, snap_fn=same_pano)
    assert len(acc) == 1                    # one pano can back only one point
    assert sum(short.values()) == 49        # 5x10 quota minus the 1 accepted
    assert sum(s["duplicate_pano"] for s in stats.values()) > 0


def test_rejects_unofficial_and_far_snaps():
    def user_far(lon, lat):
        return {"status": "OK", "official": False, "pano_id": "x",
                "lon": lon + 1.0, "lat": lat, "date": "2020-01"}
    acc, _short, stats = fill_quotas(_candidates(STRATA), per_stratum=5, snap_fn=user_far)
    assert acc == []
    assert all(s["unofficial"] == s["tried"] for s in stats.values() if s["tried"])


def test_rejection_stats_reasons_partition_the_tried():
    # every tried candidate lands in exactly one bucket (accepted or a rejection)
    acc, _short, stats = fill_quotas(_candidates(STRATA), per_stratum=10,
                                     snap_fn=_snap_every_nth(3))
    for s in stats.values():
        buckets = s["accepted"] + s["no_pano"] + s["unofficial"] \
                  + s["duplicate_pano"] + s["too_far"]
        assert buckets == s["tried"]


def test_haversine_known_distance():
    d = haversine_m(0, 0, 0, 1)
    assert 110_000 < d < 112_000
