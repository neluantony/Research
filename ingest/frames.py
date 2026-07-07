"""Fill in each city's geometry: centre coordinates and boundary polygon.

Two steps: fetch-coords takes the centre point from Wikidata; load-frames
matches each city to its GHSL Urban Centre polygon (built-up extent — the
same definition of "the city" everywhere, instead of administrative limits
which are not comparable across countries). Both are dry-run by default
and write a report CSV.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

import psycopg

from .paths import REPO_ROOT
from .wikidata import get_coordinates

# GHS-UCDB attribute columns. Defaults match R2019A; override via env if your
# download uses a different release schema. The loader auto-detects among the
# listed alternatives and reports the available columns if none are found.
UCDB_NAME_COLS = ["UC_NM_MN", "GC_UCN_MAI_2025", "UC_NM_LST"]
UCDB_COUNTRY_COLS = ["CTR_MN_NM", "GC_CNT_GAD_2025", "CTR_MN_ISO"]
UCDB_ID_COLS = ["ID_HDC_G0", "ID_UC_G0"]
# R2024A ships a multi-layer GeoPackage (one polygon layer per thematic domain).
# The boundary polygons + names + country live in the general-characteristics layer.
UCDB_LAYER_KEYWORD = "GENERAL_CHARACTERISTICS"
NEAREST_MAX_M = 25_000  # if a city point falls outside every polygon, accept the
                        # nearest urban centre within this distance, else flag it.


# --------------------------------------------------------------------------- #
# Step 1: centroids from Wikidata coordinates
# --------------------------------------------------------------------------- #
def fetch_coords(conn: psycopg.Connection, write: bool) -> list[tuple]:
    """Fill cities.centroid from Wikidata P625. Returns (city_id, qid, lon, lat)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT city_id, entity_qid FROM cities "
            "WHERE entity_qid IS NOT NULL ORDER BY city_id"
        )
        rows = cur.fetchall()

    qid_to_city = {qid: cid for cid, qid in rows}
    coords = get_coordinates([qid for _, qid in rows])

    results: list[tuple] = []
    for city_id, qid in rows:
        lonlat = coords.get(qid)
        results.append((city_id, qid,
                        lonlat[0] if lonlat else None,
                        lonlat[1] if lonlat else None))

    _write_report(REPO_ROOT / "coords_report.csv",
                  ["city_id", "entity_qid", "lon", "lat"], results)

    if write:
        updates = [(lon, lat, cid) for cid, _q, lon, lat in results if lon is not None]
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE cities SET centroid = ST_SetSRID(ST_MakePoint(%s, %s), 4326) "
                "WHERE city_id = %s",
                updates,
            )
        conn.commit()
    return results


# --------------------------------------------------------------------------- #
# Step 2: GHSL Urban Centre frames
# --------------------------------------------------------------------------- #
def _pick_column(available: list[str], candidates: list[str]) -> str | None:
    for c in candidates:
        if c in available:
            return c
    return None


def _select_ucdb_layer(ucdb_path: Path) -> str | None:
    """For a multi-layer GeoPackage, pick the general-characteristics polygon layer.

    A GeoPackage is a SQLite DB, so the layer list is read with stdlib sqlite3 (no
    geo deps). Returns None for non-GeoPackage inputs (e.g. a single-layer
    shapefile), letting geopandas read the only layer.
    """
    if ucdb_path.suffix.lower() != ".gpkg":
        return None
    import sqlite3
    con = sqlite3.connect(ucdb_path)
    try:
        layers = [r[0] for r in con.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type = 'features'")]
    finally:
        con.close()
    for layer in layers:
        if UCDB_LAYER_KEYWORD in layer.upper():
            return layer
    return layers[0] if layers else None


def load_frames(conn: psycopg.Connection, ucdb_path: Path, write: bool,
                layer: str | None = None) -> list[dict]:
    """Match each city point to its GHS Urban Centre polygon; fill frame_geom.

    Requires geopandas (imported lazily so fetch-coords works without it).
    """
    import geopandas as gpd  # lazy: only load-frames needs the geo stack
    import pandas as pd

    if not ucdb_path or not Path(ucdb_path).exists():
        raise FileNotFoundError(
            f"GHS-UCDB file not found: {ucdb_path!r}. Download it and pass "
            "--ucdb PATH or set GHSL_UCDB_PATH. See ingest/README.md."
        )

    # City points: prefer the centroid already in the DB, else fetch from Wikidata.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT city_id, entity_qid, ST_X(centroid), ST_Y(centroid) "
            "FROM cities WHERE entity_qid IS NOT NULL ORDER BY city_id"
        )
        rows = cur.fetchall()
    missing = [qid for _c, qid, x, _y in rows if x is None]
    fetched = get_coordinates(missing) if missing else {}
    cities = []
    for city_id, qid, x, y in rows:
        if x is None:
            ll = fetched.get(qid)
            if not ll:
                continue
            x, y = ll
        cities.append({"city_id": city_id, "lon": x, "lat": y})

    pts = gpd.GeoDataFrame(
        cities, geometry=gpd.points_from_xy([c["lon"] for c in cities],
                                            [c["lat"] for c in cities]),
        crs="EPSG:4326",
    )

    layer = layer or _select_ucdb_layer(Path(ucdb_path))
    ucdb = gpd.read_file(ucdb_path, layer=layer).to_crs("EPSG:4326")
    cols = list(ucdb.columns)
    name_col = _pick_column(cols, UCDB_NAME_COLS)
    country_col = _pick_column(cols, UCDB_COUNTRY_COLS)
    id_col = _pick_column(cols, UCDB_ID_COLS)
    if name_col is None or id_col is None:
        raise KeyError(
            "Could not find expected GHS-UCDB columns. Available columns: "
            f"{cols}. Set UCDB_*_COLS in ingest/frames.py to match your release."
        )

    keep = [id_col, name_col, "geometry"] + ([country_col] if country_col else [])
    ucdb = ucdb[keep].reset_index(drop=True)  # positional index aligns with .iloc

    # Containment first; nearest urban centre as a fallback for points that fall
    # just outside the built-up polygon (logged with distance). sjoin keeps the
    # left (point) geometry, so the matched polygon is fetched via index_right.
    within = gpd.sjoin(pts, ucdb, how="left", predicate="within")
    within = within[~within.index.duplicated(keep="first")].set_index("city_id")

    metric = ucdb.to_crs("EPSG:3857")
    metric_centroids = metric.geometry.centroid
    pts_m = pts.to_crs("EPSG:3857")

    reports: list[dict] = []
    updates: list[tuple] = []
    for i, city in enumerate(cities):
        r = within.loc[city["city_id"]]
        if pd.notna(r.get("index_right")):
            j, method, dist_m = int(r["index_right"]), "within", 0.0
        else:  # no containing polygon -> nearest urban-centre centroid
            dists = metric_centroids.distance(pts_m.geometry.iloc[i])
            j = int(dists.idxmin())
            dist_m = float(dists.loc[j])
            method = "nearest" if dist_m <= NEAREST_MAX_M else "unmatched"

        poly = ucdb.geometry.iloc[j]
        reports.append({
            "city_id": city["city_id"],
            "ucdb_id": ucdb.iloc[j][id_col],
            "ucdb_name": ucdb.iloc[j][name_col],
            "ucdb_country": ucdb.iloc[j][country_col] if country_col else "",
            "method": method,
            "distance_m": round(dist_m, 1),
        })
        if method != "unmatched":
            updates.append((poly.wkt, city["city_id"]))

    _write_report(
        REPO_ROOT / "frames_report.csv",
        ["city_id", "ucdb_id", "ucdb_name", "ucdb_country", "method", "distance_m"],
        [tuple(r.values()) for r in reports],
    )

    if write:
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE cities SET "
                "frame_geom = ST_Multi(ST_GeomFromText(%s, 4326)), "
                "ghsl_version = 'GHS-UCDB', frame_source = 'GHSL Urban Centre Database' "
                "WHERE city_id = %s",
                updates,
            )
        conn.commit()
    return reports


def _write_report(path: Path, header: list[str], rows) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def ucdb_path_from(args_path: str | None) -> Path | None:
    p = args_path or os.environ.get("GHSL_UCDB_PATH")
    return Path(p) if p else None
