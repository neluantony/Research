"""Snap points to Street View panoramas using the free metadata endpoint.

The metadata endpoint returns the nearest panorama's id, exact position and
capture date at no cost, so snapping and coverage checks are free — only
actual images are billed. Rules from the codebook: nearest official outdoor
panorama within 50 m, no indoor or user-contributed panoramas, log the snap
distance and capture date, one panorama per point. Needs the API key in the
GOOGLE_MAPS_API_KEY environment variable.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"


def api_key() -> str:
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise RuntimeError("set the GOOGLE_MAPS_API_KEY environment variable")
    return key


def is_official(copyright_str) -> bool:
    """Official Google imagery vs a user photo-sphere contribution.

    Official panoramas are attributed '© Google'; user contributions carry the
    contributor's name. The codebook keeps official road panoramas only.
    """
    return isinstance(copyright_str, str) and "google" in copyright_str.lower()


def parse_metadata(data: dict) -> dict:
    """Normalise a metadata API response into a flat record (pure; no network).

    status != 'OK' (e.g. ZERO_RESULTS) -> a record with status set and pano_id None.
    """
    status = data.get("status")
    if status != "OK":
        return {"status": status, "pano_id": None, "official": False}
    loc = data.get("location", {})
    return {
        "status": "OK",
        "pano_id": data.get("pano_id"),
        "lat": loc.get("lat"),
        "lon": loc.get("lng"),
        "date": data.get("date"),            # 'YYYY-MM'
        "copyright": data.get("copyright"),
        "official": is_official(data.get("copyright")),
    }


def fetch_metadata(lon: float, lat: float, key: str | None = None,
                   radius_m: int = 50, source: str = "outdoor") -> dict:
    """Call the (free) metadata endpoint for the nearest panorama to (lon, lat)."""
    params = {
        "location": f"{lat},{lon}",          # API wants lat,lng
        "radius": radius_m,
        "source": source,                    # 'outdoor' excludes indoor collections
        "key": key or api_key(),
    }
    url = f"{METADATA_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def snap(lon: float, lat: float, key: str | None = None,
         radius_m: int = 50) -> dict:
    """Snap a sampled point to the nearest official outdoor panorama within radius.

    Returns the parsed metadata record. The caller decides acceptance: a usable
    snap has status 'OK' and official True; otherwise it is a snap failure and the
    point is resampled within its stratum (codebook on_snap_failure).
    """
    return parse_metadata(fetch_metadata(lon, lat, key, radius_m))


def coverage_report(frame_geom, n: int, seed: int, key: str | None = None,
                    radius_m: int = 50) -> dict:
    """Estimate Street View coverage of a city by snapping n random frame points.

    Free (metadata only). Feeds the cairo/accra keep-or-substitute decision and
    the conf_sv_coverage confound. ``frame_geom`` is a shapely geometry in 4326.
    Returns fractions: coverage_ok (any panorama) and coverage_official (official
    outdoor, the codebook-eligible kind).
    """
    from .sampling import sample_points_in_polygon

    key = key or api_key()
    pts = sample_points_in_polygon(frame_geom, n, seed)
    ok = official = 0
    for lon, lat in pts:
        r = snap(lon, lat, key, radius_m)
        if r.get("status") == "OK":
            ok += 1
        if r.get("official"):
            official += 1
    return {
        "n": n, "ok": ok, "official": official,
        "coverage_ok": round(ok / n, 3),
        "coverage_official": round(official / n, 3),
    }
