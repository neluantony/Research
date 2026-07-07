"""Measure Mapillary coverage of our sample (the open-licence alternative).

Mapillary images are CC BY-SA (free to store and analyse), so it was the
candidate replacement for Google Street View. This probe checks, for a
subsample of each city's archived pre-snap coordinates, how many have any
Mapillary image / a 360 panorama within 50 m. Metadata only, nothing is
downloaded. Result (mapillary_report.csv): panorama coverage is far too low
to run the study on. Needs MAPILLARY_TOKEN in the environment.
"""
from __future__ import annotations

import json
import math
import os
import urllib.parse
import urllib.request

GRAPH_URL = "https://graph.mapillary.com/images"
RADIUS_M = 50          # same snap radius as the Street View rules
PER_POINT_LIMIT = 10   # images to inspect per point (enough to spot a pano)


def api_token() -> str:
    tok = os.environ.get("MAPILLARY_TOKEN")
    if not tok:
        raise RuntimeError("set the MAPILLARY_TOKEN environment variable "
                           "(free client token from mapillary.com/dashboard/developers)")
    return tok


def bbox_around(lon: float, lat: float, radius_m: float = RADIUS_M) -> tuple:
    """Small geographic bbox approximating a radius_m disc around (lon, lat)."""
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def parse_images_response(data: dict) -> tuple[bool, bool]:
    """(has_any_image, has_panorama) from a Graph API images response."""
    items = data.get("data") or []
    return bool(items), any(i.get("is_pano") for i in items)


def probe_point(lon: float, lat: float, token: str | None = None,
                radius_m: float = RADIUS_M, timeout: int = 30) -> tuple[bool, bool]:
    """Query the Graph API for images in the bbox around one point."""
    params = {
        "access_token": token or api_token(),
        "bbox": ",".join(f"{v:.6f}" for v in bbox_around(lon, lat, radius_m)),
        "fields": "id,is_pano",
        "limit": PER_POINT_LIMIT,
    }
    url = f"{GRAPH_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return parse_images_response(json.loads(resp.read().decode("utf-8")))


def probe_city(conn, city_id: str, n: int = 100, token: str | None = None) -> dict:
    """Coverage rates over a deterministic subsample of stage-A sampled coords."""
    token = token or api_token()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ST_X(sampled_geom), ST_Y(sampled_geom) FROM points "
            "WHERE city_id = %s AND stage = 'A' ORDER BY point_id LIMIT %s",
            (city_id, n))
        pts = cur.fetchall()
    got_any = got_pano = failed = 0
    for lon, lat in pts:
        try:
            has_any, has_pano = probe_point(lon, lat, token)
        except Exception:
            failed += 1
            continue
        got_any += has_any
        got_pano += has_pano
    n_ok = len(pts) - failed
    return {
        "city_id": city_id, "n": n_ok, "failed": failed,
        "any": got_any, "pano": got_pano,
        "coverage_any": round(got_any / n_ok, 3) if n_ok else 0.0,
        "coverage_pano": round(got_pano / n_ok, 3) if n_ok else 0.0,
    }
