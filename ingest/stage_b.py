"""Stage-B sampling: top up selected neighbourhoods to the 20-image floor.

Per city: pick 12 neighbourhoods at random (seeded, so the pick is
reproducible), count the stage-A points already inside each, and sample
extra points inside the neighbourhood until it has 20. New points get the
same city-wide strata zoning as stage A (CityClassifier with the stage-A
seed) and the same snapping rules, deduplicated against every panorama the
city already uses. Neighbourhoods that can't reach 20 record a shortfall
and stay ineligible for the task. Selection and quota-fill are pure
functions so they can be unit-tested.
"""
from __future__ import annotations

import random
from typing import Callable

from .sampling_driver import SNAP_RADIUS_M, haversine_m

DEFAULT_K = 12        # codebook sampling.stage_B.neighbourhoods_per_city
DEFAULT_FLOOR = 20    # codebook sampling.stage_B.min_images_per_neighbourhood
OVERSAMPLE_PER_NEEDED = 60   # candidate pool per missing point: neighbourhoods
                             # are small and coverage varies wildly


def pick_neighbourhoods(ids: list[int], k: int, seed: int, city_id: str) -> list[int]:
    """Seeded uniform random selection of k neighbourhood ids (deterministic:
    the rng is seeded from the global seed + city_id, and ids are pre-sorted
    so DB row order cannot leak in)."""
    rng = random.Random(f"{seed}:{city_id}:stage_b")
    ids = sorted(ids)
    if len(ids) <= k:
        return ids
    return sorted(rng.sample(ids, k))


def fill_neighbourhood(candidates: list[dict], need: int,
                       snap_fn: Callable[[float, float], dict],
                       used_panos: set[str],
                       radius_m: int = SNAP_RADIUS_M) -> tuple[list[dict], dict]:
    """Snap candidates until ``need`` accepted points (no stratum quota in
    stage B — the stratum is recorded, not balanced). Mutates ``used_panos``
    so dedup spans neighbourhoods and the whole city. Returns (accepted,
    stats) with the same rejection buckets as stage A (the coverage confound).
    """
    accepted: list[dict] = []
    stats = {"candidates": len(candidates), "tried": 0, "accepted": 0,
             "no_pano": 0, "unofficial": 0, "duplicate_pano": 0, "too_far": 0}
    for c in candidates:
        if len(accepted) >= need:
            break
        stats["tried"] += 1
        r = snap_fn(c["lon"], c["lat"])
        if r.get("status") != "OK":
            stats["no_pano"] += 1
            continue
        if not r.get("official"):
            stats["unofficial"] += 1
            continue
        pano = r.get("pano_id")
        if not pano or pano in used_panos:
            stats["duplicate_pano"] += 1
            continue
        dist = haversine_m(c["lon"], c["lat"], r["lon"], r["lat"])
        if dist > radius_m:
            stats["too_far"] += 1
            continue
        used_panos.add(pano)
        accepted.append({
            **c, "pano_id": pano,
            "snapped_lon": r["lon"], "snapped_lat": r["lat"],
            "snap_distance_m": round(dist, 2), "capture_date": r.get("date"),
        })
    stats["accepted"] = len(accepted)
    return accepted, stats


def run_city_stage_b(conn, city_id: str, pbf_path, built_raster: str | None = None,
                     k: int = DEFAULT_K, floor: int = DEFAULT_FLOOR,
                     seed: int = 20260622, stage_a_oversample: int = 8000,
                     write: bool = False) -> dict:
    """Top up ``k`` selected neighbourhoods of one city to the stage-B floor."""
    import shapely
    import shapely.wkt
    from shapely.geometry import Point  # noqa: F401  (re-export convenience)

    from .classify import CityClassifier
    from .osm import load_city_osm
    from .sampling import sample_points_in_polygon
    from .streetview import snap

    with conn.cursor() as cur:
        cur.execute("SELECT ST_AsText(frame_geom) FROM cities WHERE city_id = %s", (city_id,))
        row = cur.fetchone()
        if not row or not row[0]:
            raise ValueError(f"{city_id}: no frame_geom in DB")
        frame = shapely.wkt.loads(row[0])

        cur.execute("SELECT neighbourhood_id FROM neighbourhoods WHERE city_id = %s", (city_id,))
        all_ids = [r[0] for r in cur.fetchall()]
        if not all_ids:
            return {"city_id": city_id, "selected": 0, "topped_up": 0,
                    "eligible": 0, "shortfalls": {}, "skipped": "no neighbourhoods"}
        selected = pick_neighbourhoods(all_ids, k, seed, city_id)

        cur.execute(
            "SELECT n.neighbourhood_id, n.name, ST_AsText(n.boundary_geom), "
            "(SELECT count(*) FROM points p WHERE p.neighbourhood_id = n.neighbourhood_id) "
            "FROM neighbourhoods n WHERE n.neighbourhood_id = ANY(%s)", (selected,))
        nbhds = cur.fetchall()

        cur.execute("SELECT pano_id FROM points WHERE city_id = %s AND pano_id IS NOT NULL",
                    (city_id,))
        used_panos = {r[0] for r in cur.fetchall()}

    needs = {nid: max(floor - cnt, 0) for nid, _nm, _wkt, cnt in nbhds}
    if sum(needs.values()) == 0:
        eligible = [nid for nid, _nm, _wkt, cnt in nbhds if cnt >= floor]
        if write:
            _mark_eligible(conn, city_id, eligible)
            conn.commit()
        return {"city_id": city_id, "selected": len(selected), "topped_up": 0,
                "eligible": len(eligible), "shortfalls": {}}

    density_fn = None
    if built_raster:
        from .density import built_density_fn
        density_fn = built_density_fn(built_raster, frame)
    osm = load_city_osm(pbf_path, frame.bounds)
    # stage-A seed + n_ref -> identical tertile thresholds to the stage-A run
    clf = CityClassifier(frame, osm, n_ref=stage_a_oversample, seed=seed,
                         density_fn=density_fn)

    accepted_by_nbhd: dict[int, list[dict]] = {}
    stats_by_nbhd: dict[int, dict] = {}
    shortfalls: dict[str, int] = {}
    for nid, name, wkt_geom, cnt in nbhds:
        need = needs[nid]
        if need == 0:
            continue
        area = shapely.make_valid(shapely.wkt.loads(wkt_geom)).intersection(frame)
        if area.is_empty:
            shortfalls[name] = need
            continue
        # metric draw inside neighbourhood ∩ frame, deterministic per nbhd
        area_m = clf._gpd.GeoSeries([area], crs="EPSG:4326").to_crs(clf.metric).iloc[0]
        cand_m = sample_points_in_polygon(area_m, need * OVERSAMPLE_PER_NEEDED,
                                          seed + nid)
        lonlat = clf._gpd.GeoSeries(
            [shapely.geometry.Point(x, y) for x, y in cand_m],
            crs=clf.metric).to_crs("EPSG:4326")
        cands = clf.classify_lonlat([(p.x, p.y) for p in lonlat])
        got, st = fill_neighbourhood(cands, need, snap, used_panos)
        accepted_by_nbhd[nid] = got
        stats_by_nbhd[nid] = st
        if len(got) < need:
            shortfalls[name] = need - len(got)

    eligible = [nid for nid, _nm, _wkt, cnt in nbhds
                if cnt + len(accepted_by_nbhd.get(nid, [])) >= floor]
    if write:
        _write_stage_b(conn, city_id, accepted_by_nbhd, stats_by_nbhd,
                       seed, k, floor, shortfalls)
        _mark_eligible(conn, city_id, eligible)
        conn.commit()

    return {"city_id": city_id, "selected": len(selected),
            "topped_up": sum(len(v) for v in accepted_by_nbhd.values()),
            "eligible": len(eligible), "shortfalls": shortfalls}


def _write_stage_b(conn, city_id, accepted_by_nbhd, stats_by_nbhd,
                   seed, k, floor, shortfalls) -> None:
    import json

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sampling_runs (city_id, seed, params_json) "
            "VALUES (%s, %s, %s) RETURNING run_id",
            (city_id, seed, json.dumps({
                "stage": "B", "neighbourhoods_per_city": k, "floor": floor,
                "shortfalls": shortfalls,
                "rejection_stats": {str(nid): st for nid, st in stats_by_nbhd.items()},
            })),
        )
        run_id = cur.fetchone()[0]
        rows = [(city_id, nid, p["stratum"], run_id, p["lon"], p["lat"],
                 p["snapped_lon"], p["snapped_lat"], p["snap_distance_m"],
                 p["pano_id"], _capture_date(p["capture_date"]))
                for nid, pts in accepted_by_nbhd.items() for p in pts]
        cur.executemany(
            """
            INSERT INTO points (
                city_id, neighbourhood_id, stratum_id, stage, sampling_run_id,
                sampled_geom, snapped_geom, snap_distance_m, pano_id,
                capture_date, status
            ) VALUES (
                %s, %s, %s, 'B', %s,
                ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                %s, %s, %s, 'accepted'
            )
            ON CONFLICT (city_id, pano_id) DO NOTHING
            """,
            rows,
        )


def _mark_eligible(conn, city_id: str, eligible_ids: list[int]) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE neighbourhoods SET eligible_for_nbhd_task = false "
                    "WHERE city_id = %s", (city_id,))
        if eligible_ids:
            cur.execute("UPDATE neighbourhoods SET eligible_for_nbhd_task = true "
                        "WHERE neighbourhood_id = ANY(%s)", (eligible_ids,))


def _capture_date(date_str):
    """Street View date is 'YYYY-MM'; store as the first of that month, or None."""
    if not date_str:
        return None
    return f"{date_str}-01" if len(date_str) == 7 else date_str
