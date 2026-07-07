"""Stage-A sampling for one city: classify, snap, fill quotas, write points.

Per city: oversample candidate points (many will fail to snap), classify
each into a stratum, then snap candidates until each stratum has its quota
of n/5 accepted points — deduplicating by panorama id. A stratum that can't
reach its quota records a shortfall instead of forcing bad points. The run
(seed, parameters, rejection counts) and the accepted points are written to
the DB. The snap function is injected so tests can use a mock instead of
the real API.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Callable

from .strata import STRATA

DEFAULT_OVERSAMPLE = 8000   # candidate pool per city before snapping; larger so the
                            # thin strata (commercial/historic) have enough candidates
SNAP_RADIUS_M = 50          # codebook street_view_rules.snap_radius_m


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Geodesic distance in metres between two lon/lat points."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def fill_quotas(candidates: list[dict], per_stratum: int,
                snap_fn: Callable[[float, float], dict],
                radius_m: int = SNAP_RADIUS_M) -> tuple[list[dict], dict, dict]:
    """Snap candidates to fill ``per_stratum`` accepted points in each stratum.

    candidates: dicts with lon, lat, stratum (from classify.classify_city_points),
    already in the order they should be tried (reproducible from the sampler).
    Returns (accepted_points, shortfalls, rejection_stats). An accepted point
    adds pano_id, snapped_lon/lat, snap_distance_m, capture_date. Dedupes by
    pano_id across all strata. A snap is usable only if status OK, official,
    within radius.

    rejection_stats is per-stratum: candidates in pool, tried, accepted, and
    rejections by reason (no_pano / unofficial / duplicate_pano / too_far).
    Persisted because the rejection rate IS the coverage confound
    (codebook street_view_rules.rejection_rate_is_confound).
    """
    by_stratum: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        by_stratum[c["stratum"]].append(c)

    used_panos: set[str] = set()
    accepted: list[dict] = []
    shortfalls: dict[str, int] = {}
    stats: dict[str, dict] = {}

    # Iterate ALL 5 strata (not just those with candidates) so a stratum that the
    # city/OSM produced zero candidates for is recorded as a full shortfall.
    for stratum in STRATA:
        cands = by_stratum.get(stratum, [])
        got = 0
        st = {"candidates": len(cands), "tried": 0, "accepted": 0,
              "no_pano": 0, "unofficial": 0, "duplicate_pano": 0, "too_far": 0}
        for c in cands:
            if got >= per_stratum:
                break
            st["tried"] += 1
            r = snap_fn(c["lon"], c["lat"])
            if r.get("status") != "OK":
                st["no_pano"] += 1
                continue
            if not r.get("official"):
                st["unofficial"] += 1
                continue
            pano = r.get("pano_id")
            if not pano or pano in used_panos:
                st["duplicate_pano"] += 1
                continue
            dist = haversine_m(c["lon"], c["lat"], r["lon"], r["lat"])
            if dist > radius_m:
                st["too_far"] += 1
                continue
            used_panos.add(pano)
            accepted.append({
                **c, "pano_id": pano,
                "snapped_lon": r["lon"], "snapped_lat": r["lat"],
                "snap_distance_m": round(dist, 2), "capture_date": r.get("date"),
            })
            got += 1
        st["accepted"] = got
        stats[stratum] = st
        if got < per_stratum:
            shortfalls[stratum] = per_stratum - got
    return accepted, shortfalls, stats


def run_city(conn, city_id: str, pbf_path, n_per_city: int = 200,
             seed: int = 20260622, oversample: int = DEFAULT_OVERSAMPLE,
             built_raster: str | None = None, write: bool = False) -> dict:
    """Sample + snap stage-A points for one city. Writes points if ``write``.

    ``built_raster``: path to the GHS-BUILT-S mosaic; when given, innerness uses
    the full codebook definition mean(centrality, density) instead of
    centrality alone.
    """
    import shapely.wkt
    from .osm import load_city_osm
    from .classify import classify_city_points
    from .streetview import snap

    with conn.cursor() as cur:
        cur.execute("SELECT ST_AsText(frame_geom) FROM cities WHERE city_id = %s", (city_id,))
        row = cur.fetchone()
    if not row or not row[0]:
        raise ValueError(f"{city_id}: no frame_geom in DB")
    frame = shapely.wkt.loads(row[0])

    density_fn = None
    if built_raster:
        from .density import built_density_fn
        density_fn = built_density_fn(built_raster, frame)

    osm = load_city_osm(pbf_path, frame.bounds)
    candidates = classify_city_points(frame, osm, n=oversample, seed=seed,
                                      density_fn=density_fn)
    per_stratum = n_per_city // 5
    accepted, shortfalls, rejection_stats = fill_quotas(candidates, per_stratum, snap)

    if write:
        _write_points(conn, city_id, accepted, seed, n_per_city, oversample,
                      density_used=density_fn is not None,
                      shortfalls=shortfalls, rejection_stats=rejection_stats)

    return {
        "city_id": city_id, "accepted": len(accepted),
        "target": n_per_city, "shortfalls": shortfalls,
        "rejection_stats": rejection_stats,
    }


def _write_points(conn, city_id, accepted, seed, n_per_city, oversample,
                  density_used=False, shortfalls=None, rejection_stats=None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sampling_runs (city_id, seed, params_json) "
            "VALUES (%s, %s, %s) RETURNING run_id",
            (city_id, seed, _json({
                "n_per_city": n_per_city, "oversample": oversample,
                "density_used": density_used,        # innerness = mean(centrality, density)?
                "shortfalls": shortfalls or {},
                "rejection_stats": rejection_stats or {},  # coverage confound (codebook)
            })),
        )
        run_id = cur.fetchone()[0]
        cur.executemany(
            """
            INSERT INTO points (
                city_id, stratum_id, stage, sampling_run_id, sampled_geom,
                snapped_geom, snap_distance_m, pano_id, capture_date, status
            ) VALUES (
                %s, %s, 'A', %s,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                %s, %s, %s, 'accepted'
            )
            ON CONFLICT (city_id, pano_id) DO NOTHING
            """,
            [(city_id, p["stratum"], run_id, p["lon"], p["lat"],
              p["snapped_lon"], p["snapped_lat"], p["snap_distance_m"],
              p["pano_id"], _capture_date(p["capture_date"]))
             for p in accepted],
        )
    conn.commit()


def _json(obj):
    import json
    return json.dumps(obj)


def _capture_date(date_str):
    """Street View date is 'YYYY-MM'; store as the first of that month, or None."""
    if not date_str:
        return None
    return f"{date_str}-01" if len(date_str) == 7 else date_str
