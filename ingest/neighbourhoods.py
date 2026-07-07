"""Neighbourhood boundaries from OSM administrative polygons.

OSM admin levels mean different things in every country, so the right level
is chosen per city from the data itself. Rules (all unit-tested):
  * only named polygons count — a neighbourhood the model can't name is
    useless for the task;
  * a level qualifies only if its polygons contain the city centre OR cover
    at least half the frame. This filters out things like Greater London's
    ~30 civil parishes (right count, but scattered at the edge) while still
    accepting Muscat, whose old-town centroid sits just outside its frame;
  * among qualifying levels, prefer a count in the 15-40 band from the
    codebook, then closest to it, then higher coverage.
A level that only covers the core city (like the Paris arrondissements) is
fine — points outside any neighbourhood just stay in the city task only.

select_level is the pure part; load_admin_polygons / city_neighbourhoods do
the .pbf reading and DB rows.
"""
from __future__ import annotations

import re

from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

BAND = (15, 40)      # codebook neighbourhood.target_granularity_units_per_city
MIN_UNITS = 8        # below this a level cannot meaningfully partition a city
CENTRE_TOL_DEG = 0.005   # ~500 m slack for "contains the centre" (boundary gaps)
MIN_COVERAGE = 0.5   # alternative qualification: units tile most of the frame
                     # (muscat case: the Wikidata centroid — old Muscat town —
                     # falls just OUTSIDE the GHSL frame matched by 'nearest',
                     # so centre containment alone would reject a level that
                     # tiles 90% of the city)

_WIKIDATA_RE = re.compile(r'"wikidata"=>"(Q\d+)"')
_NAME_EN_RE = re.compile(r'"name:en"=>"([^"]+)"')


def select_level(levels: dict[str, list[tuple[BaseGeometry, str]]],
                 frame_geom: BaseGeometry, centre: BaseGeometry,
                 band: tuple[int, int] = BAND,
                 min_units: int = MIN_UNITS) -> tuple[str | None, dict]:
    """Choose the admin level that best matches the codebook granularity.

    levels: {admin_level: [(geometry, name), ...]} — named administrative
    polygons intersecting the frame. centre: the city centre point (Wikidata
    centroid — NOT the frame centroid, which sprawl can drag off-centre).
    Returns (chosen_level | None, per-level report dict for logging).
    """
    reports: dict[str, dict] = {}
    candidates = []
    centre_zone = centre.buffer(CENTRE_TOL_DEG)
    for lvl, polys in sorted(levels.items()):
        n = len(polys)
        rep: dict = {"count": n}
        if n < min_units:
            rep["rejected"] = f"fewer than {min_units} units"
            reports[lvl] = rep
            continue
        union = unary_union([g for g, _ in polys])
        contains_centre = union.intersects(centre_zone)
        # ratio of areas in raw degrees is fine: same latitude distortion in
        # numerator and denominator
        coverage = union.intersection(frame_geom).area / frame_geom.area
        in_band = band[0] <= n <= band[1]
        band_dist = 0 if in_band else min(abs(n - band[0]), abs(n - band[1]))
        rep.update({"coverage": round(coverage, 3), "in_band": in_band,
                    "contains_centre": contains_centre})
        reports[lvl] = rep
        if not contains_centre and coverage < MIN_COVERAGE:
            rep["rejected"] = ("does not contain the city centre and covers "
                               f"under {MIN_COVERAGE:.0%} of the frame")
            continue
        candidates.append((not in_band, band_dist, -coverage, lvl))
    if not candidates:
        return None, reports
    candidates.sort()
    chosen = candidates[0][3]
    reports[chosen]["chosen"] = True
    return chosen, reports


# ---------------------------------------------------------------------------
# I/O layer (validated on extracts, not unit-tested)
# ---------------------------------------------------------------------------

def load_admin_polygons(pbf_path: str, bbox: tuple):
    """Read named administrative polygons from an extract within ``bbox``.

    Returns a GeoDataFrame with name, admin_level, other_tags, geometry.
    One call per EXTRACT (the .pbf has no spatial index, so every read scans
    the whole file — batch all of an extract's cities onto one read).
    """
    import geopandas as gpd

    kwargs = dict(layer="multipolygons", engine="pyogrio", bbox=bbox,
                  columns=["osm_id", "name", "boundary", "admin_level", "other_tags"])
    try:  # attribute pushdown when the driver supports it
        gdf = gpd.read_file(pbf_path, where="boundary = 'administrative'", **kwargs)
    except Exception:
        gdf = gpd.read_file(pbf_path, **kwargs)
        gdf = gdf[gdf["boundary"] == "administrative"]
    gdf = gdf[gdf["name"].notna() & gdf["admin_level"].notna()]
    return _repair_geometry(gdf)


def _repair_geometry(gdf):
    """Repair invalid OSM polygons once, at the load boundary.

    Raw OSM has self-intersecting rings that make any later intersection /
    union raise GEOSException (bengaluru, jakarta, tokyo all did). make_valid
    can return a GeometryCollection; keep its polygonal part and drop features
    with none (a boundary that isn't an area cannot be a neighbourhood).
    """
    import shapely

    invalid = ~gdf.geometry.is_valid
    if not invalid.any():
        return gdf
    repaired = shapely.make_valid(gdf.geometry.values[invalid.to_numpy()])
    keep_polys = []
    for g in repaired:
        if g.geom_type in ("Polygon", "MultiPolygon"):
            keep_polys.append(g)
        elif g.geom_type == "GeometryCollection":
            parts = [p for p in g.geoms if p.geom_type in ("Polygon", "MultiPolygon")]
            keep_polys.append(unary_union(parts) if parts else None)
        else:
            keep_polys.append(None)
    gdf = gdf.copy()
    gdf.loc[invalid, "geometry"] = keep_polys
    return gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]


def city_neighbourhoods(gdf, frame_geom: BaseGeometry, centre: BaseGeometry,
                        band: tuple[int, int] = BAND) -> tuple[list[dict], dict]:
    """Pick this city's neighbourhood set from pre-loaded admin polygons.

    Returns (rows, report): rows are dicts (name, entity_qid, geom, source)
    ready for the neighbourhoods table; report is select_level's per-level log
    plus the chosen level. Empty rows if no level qualifies.
    """
    sub = gdf[gdf.intersects(frame_geom)]
    levels: dict[str, list] = {}
    rows_by_level: dict[str, list[dict]] = {}
    for _, r in sub.iterrows():
        lvl = str(r["admin_level"])
        tags = r["other_tags"] if isinstance(r["other_tags"], str) else ""  # NaN-safe
        m_en = _NAME_EN_RE.search(tags)
        m_qid = _WIKIDATA_RE.search(tags)
        levels.setdefault(lvl, []).append((r.geometry, r["name"]))
        rows_by_level.setdefault(lvl, []).append({
            # prefer the English name for the prompt task; keep local otherwise
            "name": m_en.group(1) if m_en else r["name"],
            "entity_qid": m_qid.group(1) if m_qid else None,  # from OSM tag, never fabricated
            "geom": r.geometry,
        })
    chosen, reports = select_level(levels, frame_geom, centre, band=band)
    if chosen is None:
        return [], {"chosen_level": None, "levels": reports}
    rows = rows_by_level[chosen]
    for row in rows:
        row["source"] = f"osm_admin_level_{chosen}"
    return rows, {"chosen_level": chosen, "levels": reports}


def write_city(conn, city_id: str, rows: list[dict]) -> int:
    """Replace ``city_id``'s neighbourhoods. Refuses (FK) if points reference
    them — reassign points after any reload. Commit is the caller's."""
    from shapely import to_wkb
    from shapely.geometry import MultiPolygon, Polygon

    with conn.cursor() as cur:
        cur.execute("DELETE FROM neighbourhoods WHERE city_id = %s", (city_id,))
        for r in rows:
            g = r["geom"]
            if isinstance(g, Polygon):
                g = MultiPolygon([g])
            cur.execute(
                """
                INSERT INTO neighbourhoods
                    (city_id, name, entity_qid, boundary_geom, neighbourhood_source)
                VALUES (%s, %s, %s, ST_SetSRID(%s::geometry, 4326), %s)
                """,
                (city_id, r["name"], r["entity_qid"], to_wkb(g, hex=True), r["source"]),
            )
    return len(rows)
