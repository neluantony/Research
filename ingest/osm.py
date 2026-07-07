"""Land use and heritage signals from OpenStreetMap, for the strata classifier.

Two parts: the pure functions decide the dominant land-use function
(commercial / residential / industrial_other) and whether heritage features
are present in a buffer around a point; load_city_osm reads a .osm.pbf
extract through GDAL (pyrosm has no Python 3.14 wheels). Geometry passed to
the pure functions must be in a metric CRS so areas are in m².
"""
from __future__ import annotations

import shapely
from shapely.errors import GEOSException
from shapely.geometry.base import BaseGeometry


def _safe_intersection_area(geom: BaseGeometry, other: BaseGeometry) -> float:
    """Intersection area that tolerates invalid OSM polygons.

    Raw OSM extracts contain self-intersecting / non-closed rings that make GEOS
    raise TopologyException. On failure we repair the geometry with make_valid
    and retry once; if it still fails the feature contributes zero area rather
    than killing the whole city's sampling run.
    """
    try:
        return geom.intersection(other).area
    except GEOSException:
        try:
            return shapely.make_valid(geom).intersection(other).area
        except GEOSException:
            return 0.0


def _safe_intersects(geom: BaseGeometry, other: BaseGeometry) -> bool:
    """intersects() that repairs invalid geometries before giving up (see above)."""
    try:
        return geom.intersects(other)
    except GEOSException:
        try:
            return shapely.make_valid(geom).intersects(other)
        except GEOSException:
            return False

# OSM landuse tag -> our function bucket.
LANDUSE_BUCKET = {
    "commercial": "commercial", "retail": "commercial",
    "residential": "residential",
    "industrial": "industrial", "railway": "industrial", "port": "industrial",
}
# OSM tags that flag a heritage/iconic character.
HERITAGE_TOURISM = {"attraction", "museum", "gallery", "artwork", "viewpoint"}

COMMERCIAL_POI_MIN = 5   # shop/office POIs in-buffer to call it commercial absent landuse
                         # DEFAULT — calibrate on the pilot (codebook thresholds_status)


def point_function(buffer_geom: BaseGeometry,
                   landuse: list[tuple[BaseGeometry, str]],
                   commercial_poi_count: int = 0,
                   commercial_poi_min: int = COMMERCIAL_POI_MIN) -> str:
    """Dominant land-use function within the buffer: by intersected area, with a
    shop/office-POI fallback when no commercial/residential landuse is mapped.

    landuse: (geometry, bucket) pairs; bucket is a value of LANDUSE_BUCKET.
    Returns one of 'commercial' | 'residential' | 'industrial_other'.
    """
    areas: dict[str, float] = {}
    for geom, bucket in landuse:
        a = _safe_intersection_area(geom, buffer_geom)
        if a > 0:
            areas[bucket] = areas.get(bucket, 0.0) + a

    com = areas.get("commercial", 0.0)
    res = areas.get("residential", 0.0)

    # 'shop density high' -> commercial (codebook land_use_function.commercial):
    # a cluster of shops/offices marks commercial activity even on residential
    # landuse (high streets), so POI density is decisive, not just landuse area.
    if commercial_poi_count >= commercial_poi_min:
        return "commercial"
    if com == 0.0 and res == 0.0:
        return "industrial_other"
    return "commercial" if com >= res else "residential"


def point_heritage(buffer_geom: BaseGeometry,
                   heritage_features: list[BaseGeometry]) -> bool:
    """True if any heritage feature (historic=*/heritage=*/tourism attraction…)
    lies within the buffer around the point."""
    return any(_safe_intersects(g, buffer_geom) for g in heritage_features)


def _present(v) -> bool:
    """OSM tag column value is meaningfully set."""
    return isinstance(v, str) and v != ""


def _other_tag_has(other_tags, keys) -> bool:
    """True if the GDAL HSTORE-style ``other_tags`` string carries any of ``keys``."""
    return isinstance(other_tags, str) and any(f'"{k}"=>' in other_tags for k in keys)


def _other_tag_tourism_heritage(other_tags) -> bool:
    if not isinstance(other_tags, str):
        return False
    return any(f'"tourism"=>"{v}"' in other_tags for v in HERITAGE_TOURISM)


def load_city_osm(pbf_path, bbox) -> dict:
    """Read an .osm.pbf extract within ``bbox`` and bucket its features.

    Uses geopandas + GDAL's OSM driver (no pyrosm). Returns geometries in EPSG:4326
    (OSM's native CRS); the caller reprojects to a metric CRS before buffering.

    Returns dict:
      'landuse'    -> list of (geometry, bucket) for residential/commercial/industrial
      'commercial' -> list of geometries for shop/office features (POI density signal)
      'heritage'   -> list of geometries for historic/heritage/tourism-attraction features
    """
    import geopandas as gpd  # lazy: only the strata step needs the geo stack

    bbox = tuple(bbox)
    mp = gpd.read_file(pbf_path, layer="multipolygons", bbox=bbox, engine="pyogrio")
    pts = gpd.read_file(pbf_path, layer="points", bbox=bbox, engine="pyogrio")

    landuse: list[tuple] = []
    commercial: list = []
    heritage: list = []

    for geom, lu, shop, office, hist, tour in zip(
            mp.geometry, mp["landuse"], mp["shop"], mp["office"],
            mp["historic"], mp["tourism"]):
        if geom is None or geom.is_empty:
            continue
        bucket = LANDUSE_BUCKET.get(lu) if isinstance(lu, str) else None
        if bucket:
            landuse.append((geom, bucket))
        if _present(shop) or _present(office):
            commercial.append(geom)
        if _present(hist) or (isinstance(tour, str) and tour in HERITAGE_TOURISM):
            heritage.append(geom)

    # Point nodes expose only a few columns; the rest live in other_tags (HSTORE).
    for geom, other in zip(pts.geometry, pts["other_tags"]):
        if geom is None or geom.is_empty:
            continue
        if _other_tag_has(other, ("shop", "office")):
            commercial.append(geom)
        if _other_tag_has(other, ("historic", "heritage")) or _other_tag_tourism_heritage(other):
            heritage.append(geom)

    return {"landuse": landuse, "commercial": commercial, "heritage": heritage}
