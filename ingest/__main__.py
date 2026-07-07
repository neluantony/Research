"""CLI entry point for the ingestion pipeline.

Examples
--------
    python -m ingest validate         # check seed + codebook vs schema vocab (no DB)
    python -m ingest sync-spec        # codebook.yaml -> variables/fabric_strata/metrics
    python -m ingest load-seed        # cities_seed.csv -> regions/cities
    python -m ingest resolve-qids     # dry-run: write qid_proposals.csv only
    python -m ingest resolve-qids --write   # also fill confident QIDs (NULL only)
    python -m ingest fetch-coords --write   # fill cities.centroid from Wikidata
    python -m ingest load-frames --ucdb data/ghsl/UCDB.gpkg --write  # fill frame_geom
    python -m ingest all              # sync-spec + load-seed
"""
from __future__ import annotations

import argparse
import os
import sys

from . import db
from . import load_seed
from . import sync_spec
from . import resolve_qids
from . import frames
from . import streetview
from . import sampling_driver
from . import validate as validate_mod


def _print_counts(title: str, counts: dict[str, int]) -> None:
    print(title)
    for name, n in counts.items():
        print(f"  {name}: {n}")


def cmd_validate(_args) -> int:
    errors = validate_mod.validate_all()
    if errors:
        print(f"FAIL — {len(errors)} problem(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("OK — seed and codebook are consistent with the schema vocabulary.")
    return 0


def cmd_sync_spec(_args) -> int:
    with db.connect() as conn:
        _print_counts("Spec synced from codebook.yaml:", sync_spec.sync_all(conn))
    return 0


def cmd_load_seed(_args) -> int:
    with db.connect() as conn:
        _print_counts("Seed loaded from cities_seed.csv:", load_seed.load_all(conn))
    return 0


def cmd_all(_args) -> int:
    # Guard the load: refuse to write bad data into the DB.
    errors = validate_mod.validate_all()
    if errors:
        print(f"Validation failed ({len(errors)} problem(s)); aborting load:")
        for e in errors:
            print(f"  - {e}")
        return 1
    with db.connect() as conn:
        _print_counts("Spec synced:", sync_spec.sync_all(conn))
        _print_counts("Seed loaded:", load_seed.load_all(conn))
    return 0


def cmd_resolve_qids(args) -> int:
    conn = db.connect() if args.write else None
    try:
        proposals = resolve_qids.resolve_all(conn, write=args.write)
    finally:
        if conn is not None:
            conn.close()
    confident = sum(1 for p in proposals if p.confident)
    print(f"Resolved {len(proposals)} unresolved cities: "
          f"{confident} confident, {len(proposals) - confident} need review.")
    print("Proposals written to qid_proposals.csv"
          + (" (confident QIDs also written to DB)." if args.write else " (dry run)."))
    return 0


def cmd_fetch_coords(args) -> int:
    with db.connect() as conn:
        results = frames.fetch_coords(conn, write=args.write)
    got = sum(1 for *_rest, lat in results if lat is not None)
    print(f"Coordinates: {got}/{len(results)} cities resolved from Wikidata. "
          f"Report: coords_report.csv"
          + (" (centroids written to DB)." if args.write else " (dry run)."))
    return 0


def cmd_load_frames(args) -> int:
    ucdb = frames.ucdb_path_from(args.ucdb)
    with db.connect() as conn:
        reports = frames.load_frames(conn, ucdb, write=args.write, layer=args.layer)
    by_method: dict[str, int] = {}
    for r in reports:
        by_method[r["method"]] = by_method.get(r["method"], 0) + 1
    print(f"Frames matched for {len(reports)} cities: {by_method}. "
          f"Report: frames_report.csv"
          + (" (frame_geom written to DB)." if args.write else " (dry run)."))
    return 0


def cmd_coverage(args) -> int:
    import shapely.wkt
    # Ad-hoc screening of a candidate substitute not yet in the DB: sample a disk
    # around its centre (radius in km, ~111 km/deg) instead of a stored frame.
    if args.probe:
        from shapely.geometry import Point
        lat, lon = (float(v) for v in args.probe.split(","))
        disk = Point(lon, lat).buffer(args.probe_radius_km / 111.0)
        rep = streetview.coverage_report(disk, args.n, seed=20260622)
        print(f"probe {args.probe}  official={rep['coverage_official']:.0%} "
              f"any={rep['coverage_ok']:.0%} (n={rep['n']}, r={args.probe_radius_km}km)")
        return 0

    city_ids = args.cities or ["cairo", "accra"]
    rows = []
    with db.connect() as conn, conn.cursor() as cur:
        for cid in city_ids:
            cur.execute("SELECT ST_AsText(frame_geom) FROM cities WHERE city_id = %s", (cid,))
            row = cur.fetchone()
            if not row or not row[0]:
                print(f"{cid}: no frame_geom in DB — skipping")
                continue
            geom = shapely.wkt.loads(row[0])
            rep = streetview.coverage_report(geom, args.n, seed=20260622)
            flag = "OK" if rep["coverage_official"] >= args.min_coverage else "LOW — consider substitute"
            print(f"{cid:10s} official={rep['coverage_official']:.0%} "
                  f"any={rep['coverage_ok']:.0%} (n={rep['n']})  -> {flag}")
            rows.append((cid, rep["n"], rep["ok"], rep["official"],
                         rep["coverage_ok"], rep["coverage_official"], flag))
    if rows:
        import csv
        from .paths import REPO_ROOT
        with open(REPO_ROOT / "coverage_report.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["city_id", "n", "ok", "official", "coverage_ok", "coverage_official", "flag"])
            w.writerows(rows)
        print("Report: coverage_report.csv")
    return 0


def _built_raster_from(args) -> str | None:
    """GHS-BUILT-S mosaic path: --built-raster flag or GHS_BUILT_S_PATH env var."""
    return getattr(args, "built_raster", None) or os.environ.get("GHS_BUILT_S_PATH")


def cmd_sample(args) -> int:
    with db.connect() as conn:
        res = sampling_driver.run_city(
            conn, args.city, args.pbf, n_per_city=args.n,
            oversample=args.oversample, built_raster=_built_raster_from(args),
            write=args.write)
    print(f"{res['city_id']}: accepted {res['accepted']}/{res['target']} points"
          + (f"  shortfalls={res['shortfalls']}" if res["shortfalls"] else "")
          + ("  (written to DB)" if args.write else "  (dry run, not written)"))
    return 0


def _covering_extract(lon, lat, boxes):
    """Pick the .pbf that actually covers (lon, lat).

    Bounding boxes are a cheap prefilter, but extracts with antimeridian/overseas
    territory (New Zealand, Chile, France, USA…) have globe-spanning bboxes that
    falsely contain far-away cities. When more than one bbox matches, disambiguate
    by reading a small window from each candidate and keeping the one that has road
    features there.
    """
    import geopandas as gpd

    cands = [(p, b) for p, b in boxes.items()
             if b[0] <= lon <= b[2] and b[1] <= lat <= b[3]]
    if not cands:
        return None
    # An extract whose bbox spans the antimeridian / overseas territory (New
    # Zealand, Chile, France, USA…) has an implausibly wide bbox that falsely
    # "contains" far-away cities — even as the SOLE match. Trust a single normal
    # bbox; otherwise (multiple matches, or any oversized bbox) verify by reading
    # road features near the city and keep the extract that actually has them.
    oversized = any((b[2] - b[0]) > 180 or (b[3] - b[1]) > 120 for _p, b in cands)
    if len(cands) == 1 and not oversized:
        return cands[0][0]
    win = (lon - 0.05, lat - 0.05, lon + 0.05, lat + 0.05)
    best, best_n = None, 0
    for p, _b in cands:
        try:
            n = len(gpd.read_file(p, layer="lines", bbox=win, engine="pyogrio"))
        except Exception:
            n = 0
        if n > best_n:
            best, best_n = p, n
    return best  # None if no candidate has road features there


def cmd_sample_all(args) -> int:
    """Sample every city that has a matching .osm.pbf present in the OSM dir.

    Each .pbf is matched to a city by bounding box + a road-feature check, so you
    just drop downloaded extracts in data/osm/ — no URL table to keep in sync.
    Already-sampled cities are skipped unless --resample.
    """
    import pyogrio
    from pathlib import Path

    osm_dir = Path(args.osm_dir)
    pbfs = sorted(osm_dir.glob("*.osm.pbf"))
    if not pbfs:
        print(f"no .osm.pbf files in {osm_dir} — download some first")
        return 1
    boxes = {}
    for p in pbfs:
        try:
            boxes[p] = pyogrio.read_info(str(p), layer="points")["total_bounds"]
        except Exception as exc:  # skip a corrupt/incomplete extract, don't kill the batch
            print(f"  [warn] cannot read {p.name}, skipping it: {exc}")
    if not boxes:
        print(f"no readable .osm.pbf files in {osm_dir}")
        return 1

    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.city_id, ST_X(c.centroid), ST_Y(c.centroid), "
                "EXISTS(SELECT 1 FROM points p WHERE p.city_id = c.city_id) "
                "FROM cities c WHERE c.frame_geom IS NOT NULL "
                # skip cities whose Street View coverage is unconfirmed/failed
                "AND c.sv_coverage_status <> 'verify' ORDER BY c.city_id"
            )
            cities = cur.fetchall()

        built_raster = _built_raster_from(args)
        done = skipped = failed = 0
        for city_id, lon, lat, sampled in cities:
            if sampled and not args.resample:
                continue
            match = _covering_extract(lon, lat, boxes)
            if match is None:
                print(f"  {city_id:14s} no .pbf covers it — download its extract")
                skipped += 1
                continue
            # One city's failure (bad geometry, empty layer, …) must not abort the
            # whole batch; log it and move on so the remaining cities still sample.
            try:
                if sampled and args.resample and args.write:
                    # replace, don't accumulate: drop the city's old points inside
                    # this transaction (committed together with the new run, so a
                    # failure rolls the delete back too). Old sampling_runs rows
                    # stay as provenance.
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM points WHERE city_id = %s", (city_id,))
                res = sampling_driver.run_city(
                    conn, city_id, str(match), n_per_city=args.n,
                    oversample=args.oversample, built_raster=built_raster,
                    write=args.write)
            except Exception as exc:
                conn.rollback()
                print(f"  {city_id:14s} FAILED [{match.name}]: {exc}")
                failed += 1
                continue
            sf = f" shortfalls={res['shortfalls']}" if res["shortfalls"] else ""
            print(f"  {city_id:14s} {res['accepted']:3d}/{res['target']} [{match.name}]{sf}")
            done += 1
    print(f"sampled {done} city(ies); {skipped} awaiting an extract; {failed} failed"
          + ("" if args.write else "  (dry run, not written)"))
    return 0


def cmd_neighbourhoods(args) -> int:
    """Load stage-B neighbourhood boundaries from OSM admin polygons.

    Batches cities per extract (one full-file scan serves all its cities) and
    picks the admin level per city (see ingest.neighbourhoods). Dry-run by
    default; --write replaces each city's rows.
    """
    import pyogrio
    import shapely.wkt
    from pathlib import Path

    from . import neighbourhoods as nbhd

    osm_dir = Path(args.osm_dir)
    pbfs = sorted(osm_dir.glob("*.osm.pbf"))
    boxes = {}
    for p in pbfs:
        try:
            boxes[p] = pyogrio.read_info(str(p), layer="points")["total_bounds"]
        except Exception as exc:
            print(f"  [warn] cannot read {p.name}, skipping it: {exc}")
    if not boxes:
        print(f"no readable .osm.pbf files in {osm_dir}")
        return 1

    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.city_id, ST_X(c.centroid), ST_Y(c.centroid), "
                "ST_AsText(c.frame_geom), "
                "EXISTS(SELECT 1 FROM neighbourhoods n WHERE n.city_id = c.city_id) "
                "FROM cities c WHERE c.frame_geom IS NOT NULL ORDER BY c.city_id"
            )
            cities = cur.fetchall()

        # group cities by covering extract so each .pbf is scanned once
        by_extract: dict = {}
        for city_id, lon, lat, frame_wkt, has_nbhd in cities:
            if args.cities and city_id not in args.cities:
                continue
            if has_nbhd and not args.reload:
                continue
            match = _covering_extract(lon, lat, boxes)
            if match is None:
                print(f"  {city_id:14s} no .pbf covers it")
                continue
            by_extract.setdefault(match, []).append(
                (city_id, lon, lat, shapely.wkt.loads(frame_wkt)))

        done = failed = 0
        for pbf, group in sorted(by_extract.items()):
            # one read covering every city frame in this extract
            minx = min(f.bounds[0] for *_xy, f in group)
            miny = min(f.bounds[1] for *_xy, f in group)
            maxx = max(f.bounds[2] for *_xy, f in group)
            maxy = max(f.bounds[3] for *_xy, f in group)
            try:
                gdf = nbhd.load_admin_polygons(str(pbf), (minx, miny, maxx, maxy))
            except Exception as exc:
                print(f"  [warn] {pbf.name} read failed: {exc}")
                failed += len(group)
                continue
            for city_id, lon, lat, frame in group:
                from shapely.geometry import Point
                try:
                    rows, report = nbhd.city_neighbourhoods(gdf, frame, Point(lon, lat))
                except Exception as exc:
                    conn.rollback()
                    print(f"  {city_id:14s} FAILED: {exc}")
                    failed += 1
                    continue
                lvl = report["chosen_level"]
                if not rows:
                    print(f"  {city_id:14s} NO qualifying admin level:")
                    for lvl, rep in sorted(report["levels"].items(),
                                           key=lambda kv: (len(kv[0]), kv[0])):
                        print(f"      L{lvl}: {rep}")
                    failed += 1
                    continue
                cov = report["levels"][lvl]["coverage"]
                flag = "" if nbhd.BAND[0] <= len(rows) <= nbhd.BAND[1] else "  [out of 15-40 band]"
                if args.write:
                    nbhd.write_city(conn, city_id, rows)
                    conn.commit()
                print(f"  {city_id:14s} L{lvl:>2s} n={len(rows):3d} coverage={cov:.0%}"
                      f" [{pbf.name}]{flag}")
                done += 1
    print(f"neighbourhoods for {done} city(ies); {failed} failed/skipped"
          + ("" if args.write else "  (dry run, not written)"))
    return 0


def cmd_assign_neighbourhoods(args) -> int:
    """Assign points.neighbourhood_id by point-in-polygon (snapped location).

    Idempotent: clears all assignments then re-derives them, so it can re-run
    after any boundary reload. The snapped location is used (where the panorama
    actually is), not the drawn coordinate. Points in no neighbourhood keep
    NULL and stay city-task-only (codebook stage_B).
    """
    with db.connect() as conn, conn.cursor() as cur:
        if args.write:
            cur.execute("UPDATE points SET neighbourhood_id = NULL "
                        "WHERE neighbourhood_id IS NOT NULL")
            cur.execute(
                "UPDATE points p SET neighbourhood_id = n.neighbourhood_id "
                "FROM neighbourhoods n WHERE p.city_id = n.city_id "
                "AND ST_Contains(n.boundary_geom, p.snapped_geom)")
            assigned = cur.rowcount
            conn.commit()
        else:
            cur.execute(
                "SELECT count(DISTINCT p.point_id) FROM points p "
                "JOIN neighbourhoods n ON p.city_id = n.city_id "
                "AND ST_Contains(n.boundary_geom, p.snapped_geom)")
            assigned = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM points")
        total = cur.fetchone()[0]

        # eligibility preview for the stage-B floor (points already >= floor now,
        # before any top-up)
        cur.execute(
            "SELECT n.city_id, count(DISTINCT n.neighbourhood_id) AS nbhds, "
            "count(DISTINCT p.point_id) AS pts_in, "
            "count(DISTINCT n.neighbourhood_id) FILTER (WHERE cnt.c >= %s) AS at_floor "
            "FROM neighbourhoods n "
            "LEFT JOIN points p ON p.city_id = n.city_id "
            "  AND ST_Contains(n.boundary_geom, p.snapped_geom) "
            "LEFT JOIN LATERAL (SELECT count(*) AS c FROM points p2 "
            "  WHERE p2.city_id = n.city_id "
            "  AND ST_Contains(n.boundary_geom, p2.snapped_geom)) cnt ON true "
            "GROUP BY n.city_id ORDER BY n.city_id", (args.floor,))
        print(f"{'city':15s} {'nbhds':>5s} {'pts_in':>6s} {'>=floor':>7s}")
        for city, nbhds, pts_in, at_floor in cur.fetchall():
            print(f"{city:15s} {nbhds:5d} {pts_in:6d} {at_floor:7d}")
    print(f"\nassigned {assigned}/{total} points"
          + ("" if args.write else "  (dry run, not written)"))
    return 0


def cmd_sample_stage_b(args) -> int:
    """Stage-B top-up over every city with neighbourhoods (skips cities that
    already have stage-B points). Same extract matching as sample-all."""
    import pyogrio
    from pathlib import Path

    from . import stage_b

    osm_dir = Path(args.osm_dir)
    boxes = {}
    for p in sorted(osm_dir.glob("*.osm.pbf")):
        try:
            boxes[p] = pyogrio.read_info(str(p), layer="points")["total_bounds"]
        except Exception as exc:
            print(f"  [warn] cannot read {p.name}, skipping it: {exc}")
    if not boxes:
        print(f"no readable .osm.pbf files in {osm_dir}")
        return 1

    built_raster = _built_raster_from(args)
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.city_id, ST_X(c.centroid), ST_Y(c.centroid), "
                "EXISTS(SELECT 1 FROM points p WHERE p.city_id = c.city_id AND p.stage = 'B') "
                "FROM cities c "
                "WHERE EXISTS(SELECT 1 FROM neighbourhoods n WHERE n.city_id = c.city_id) "
                "ORDER BY c.city_id")
            cities = cur.fetchall()

        done = failed = 0
        for city_id, lon, lat, has_b in cities:
            if args.cities and city_id not in args.cities:
                continue
            if has_b and not args.resume:
                continue
            match = _covering_extract(lon, lat, boxes)
            if match is None:
                print(f"  {city_id:14s} no .pbf covers it")
                failed += 1
                continue
            try:
                res = stage_b.run_city_stage_b(
                    conn, city_id, str(match), built_raster=built_raster,
                    k=args.k, floor=args.floor, write=args.write)
            except Exception as exc:
                conn.rollback()
                print(f"  {city_id:14s} FAILED [{match.name}]: {exc}")
                failed += 1
                continue
            sf = f" shortfalls={res['shortfalls']}" if res["shortfalls"] else ""
            print(f"  {city_id:14s} +{res['topped_up']:4d} pts, "
                  f"{res['eligible']:2d}/{res['selected']} eligible [{match.name}]{sf}")
            done += 1
    print(f"stage-B for {done} city(ies); {failed} failed/skipped"
          + ("" if args.write else "  (dry run, not written)"))
    return 0


def cmd_mapillary_coverage(args) -> int:
    """Mapillary coverage over the archived stage-A sample; report CSV.

    Compares directly against Google official coverage because it probes the
    SAME pre-snap coordinates. coverage_pano is the codebook-relevant number
    (360 capture format)."""
    import csv

    from . import mapillary
    from .paths import REPO_ROOT

    token = mapillary.api_token()   # fail fast if the env var is missing
    rows = []
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT city_id FROM cities ORDER BY city_id")
            city_ids = [r[0] for r in cur.fetchall()]
        for cid in city_ids:
            if args.cities and cid not in args.cities:
                continue
            rep = mapillary.probe_city(conn, cid, n=args.n, token=token)
            print(f"  {cid:15s} any={rep['coverage_any']:5.0%}  "
                  f"pano={rep['coverage_pano']:5.0%}  (n={rep['n']}"
                  + (f", {rep['failed']} failed" if rep["failed"] else "") + ")",
                  flush=True)
            rows.append(rep)
    if rows:
        with open(REPO_ROOT / "mapillary_report.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print("Report: mapillary_report.csv")
    return 0


def cmd_fetch_images(args) -> int:
    """Fetch imagery. Dry-run prints the plan and cost; --write downloads."""
    from . import fetch_images
    from . import streetview

    key = streetview.api_key()
    with db.connect() as conn:
        rep = fetch_images.run(conn, key, out_dir=args.out_dir,
                               limit=args.limit, write=args.write)
    if args.write:
        print(f"fetched {rep['fetched']}/{rep['pending']} points "
              f"({rep['dead_panos']} dead panos, {rep.get('errors', 0)} errors)")
    else:
        print(f"DRY RUN: {rep['pending']} points pending -> {rep['requests']} requests "
              f"(~£{rep['est_cost_gbp']}). Add --write to fetch.")
    return 0


def cmd_blur_views(args) -> int:
    """Create text-blurred copies of the fetched views (codebook v0.3.8).

    Local processing only — no API calls, no cost. Dry-run reports how many
    images still need blurring."""
    from . import blur_text

    with db.connect() as conn:
        rep = blur_text.run(conn, out_root=args.out_root,
                            limit=args.limit, write=args.write)
    if args.write:
        print(f"blurred {rep['processed']}/{rep['pending_images']} images "
              f"({rep['failed']} failed)")
    else:
        print(f"DRY RUN: {rep['pending_images']} images pending blurring. "
              "Add --write to process.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ingest", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="check seed + codebook against schema vocab (no DB)").set_defaults(func=cmd_validate)
    sub.add_parser("sync-spec", help="sync spec tables from codebook.yaml").set_defaults(func=cmd_sync_spec)
    sub.add_parser("load-seed", help="load cities from cities_seed.csv").set_defaults(func=cmd_load_seed)
    sub.add_parser("all", help="sync-spec then load-seed").set_defaults(func=cmd_all)
    rq = sub.add_parser("resolve-qids", help="resolve Wikidata QIDs (dry-run by default)")
    rq.add_argument("--write", action="store_true",
                    help="write confident QIDs to cities.entity_qid (NULL rows only)")
    rq.set_defaults(func=cmd_resolve_qids)

    fc = sub.add_parser("fetch-coords", help="fill cities.centroid from Wikidata P625")
    fc.add_argument("--write", action="store_true", help="write centroids to the DB")
    fc.set_defaults(func=cmd_fetch_coords)

    lf = sub.add_parser("load-frames", help="match cities to GHS Urban Centre polygons")
    lf.add_argument("--ucdb", help="path to the GHS-UCDB file (or set GHSL_UCDB_PATH)")
    lf.add_argument("--layer", help="GeoPackage layer (auto-detected if omitted)")
    lf.add_argument("--write", action="store_true", help="write frame_geom to the DB")
    lf.set_defaults(func=cmd_load_frames)

    cv = sub.add_parser("coverage", help="Street View coverage check (free metadata)")
    cv.add_argument("--cities", nargs="*", help="city_ids (default: cairo accra)")
    cv.add_argument("--n", type=int, default=100, help="sample points per city")
    cv.add_argument("--min-coverage", type=float, default=0.5,
                    help="official-coverage fraction below which to flag a substitute")
    cv.add_argument("--probe", help="screen a candidate city by 'lat,lon' (not in DB)")
    cv.add_argument("--probe-radius-km", type=float, default=8.0,
                    help="disk radius for --probe")
    cv.set_defaults(func=cmd_coverage)

    sm = sub.add_parser("sample", help="stage-A: classify + snap points into the points table")
    sm.add_argument("--city", required=True, help="city_id (e.g. amman)")
    sm.add_argument("--pbf", required=True, help="path to the city's .osm.pbf extract")
    sm.add_argument("--n", type=int, default=200, help="points per city (5 strata)")
    sm.add_argument("--oversample", type=int, default=sampling_driver.DEFAULT_OVERSAMPLE,
                    help="candidate pool size before snapping")
    sm.add_argument("--built-raster",
                    help="GHS-BUILT-S mosaic path (or set GHS_BUILT_S_PATH); enables the density half of innerness")
    sm.add_argument("--write", action="store_true", help="write points to the DB")
    sm.set_defaults(func=cmd_sample)

    sa = sub.add_parser("sample-all", help="sample every city with a matching .osm.pbf in data/osm")
    sa.add_argument("--osm-dir", default="data/osm", help="folder of .osm.pbf extracts")
    sa.add_argument("--n", type=int, default=200, help="points per city")
    sa.add_argument("--oversample", type=int, default=sampling_driver.DEFAULT_OVERSAMPLE)
    sa.add_argument("--built-raster",
                    help="GHS-BUILT-S mosaic path (or set GHS_BUILT_S_PATH); enables the density half of innerness")
    sa.add_argument("--resample", action="store_true",
                    help="re-sample cities already in points (replaces their old points)")
    sa.add_argument("--write", action="store_true", help="write points to the DB")
    sa.set_defaults(func=cmd_sample_all)

    nb = sub.add_parser("neighbourhoods",
                        help="stage-B: load neighbourhood boundaries from OSM admin polygons")
    nb.add_argument("--osm-dir", default="data/osm", help="folder of .osm.pbf extracts")
    nb.add_argument("--cities", nargs="*", help="restrict to these city_ids")
    nb.add_argument("--reload", action="store_true",
                    help="replace cities that already have neighbourhoods")
    nb.add_argument("--write", action="store_true", help="write to the DB")
    nb.set_defaults(func=cmd_neighbourhoods)

    an = sub.add_parser("assign-neighbourhoods",
                        help="fill points.neighbourhood_id by point-in-polygon")
    an.add_argument("--floor", type=int, default=20,
                    help="stage-B min images per neighbourhood (eligibility preview)")
    an.add_argument("--write", action="store_true", help="write assignments to the DB")
    an.set_defaults(func=cmd_assign_neighbourhoods)

    sb = sub.add_parser("sample-stage-b",
                        help="stage-B: top up selected neighbourhoods to the image floor")
    sb.add_argument("--osm-dir", default="data/osm", help="folder of .osm.pbf extracts")
    sb.add_argument("--cities", nargs="*", help="restrict to these city_ids")
    sb.add_argument("--k", type=int, default=12,
                    help="neighbourhoods per city (codebook stage_B)")
    sb.add_argument("--floor", type=int, default=20,
                    help="min images per neighbourhood (codebook stage_B)")
    sb.add_argument("--built-raster",
                    help="GHS-BUILT-S mosaic path (or set GHS_BUILT_S_PATH)")
    sb.add_argument("--resume", action="store_true",
                    help="also process cities that already have stage-B points")
    sb.add_argument("--write", action="store_true", help="write points to the DB")
    sb.set_defaults(func=cmd_sample_stage_b)

    mp = sub.add_parser("mapillary-coverage",
                        help="probe Mapillary coverage of the stage-A sample (metadata only)")
    mp.add_argument("--cities", nargs="*", help="restrict to these city_ids")
    mp.add_argument("--n", type=int, default=100, help="points probed per city")
    mp.set_defaults(func=cmd_mapillary_coverage)

    fi = sub.add_parser("fetch-images",
                        help="fetch the 4 cardinal views per point (PAID; permission-gated)")
    fi.add_argument("--out-dir", default="data/images", help="root folder for view files")
    fi.add_argument("--limit", type=int, help="max points this run (requests = points x 4)")
    fi.add_argument("--write", action="store_true", help="actually fetch (else dry-run plan)")
    fi.set_defaults(func=cmd_fetch_images)

    bv = sub.add_parser("blur-views",
                        help="text-blur the fetched views (local, free; models see these)")
    bv.add_argument("--out-root", default="data/images_blurred",
                    help="root folder for blurred copies")
    bv.add_argument("--limit", type=int, help="max images this run")
    bv.add_argument("--write", action="store_true", help="process and register in DB")
    bv.set_defaults(func=cmd_blur_views)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
