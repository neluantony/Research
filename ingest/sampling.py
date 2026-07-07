"""Draw random points inside a polygon, reproducibly.

Rejection sampling with a fixed seed: the same (polygon, n, seed) always
returns the same points, so every draw can be repeated exactly. The
stratified part of the design (quotas per fabric stratum) is layered on
top of this elsewhere. Coordinates are WGS84 lon/lat like the city frames.
"""
from __future__ import annotations

import numpy as np
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.prepared import prep

# Draw candidates in the bounding box, keep the ones inside the polygon.
# Depends only on (n, seed, geometry), so results stay deterministic.
_MAX_BATCHES = 100_000


def sample_points_in_polygon(geom: BaseGeometry, n: int, seed: int) -> list[tuple[float, float]]:
    """Draw ``n`` uniform-random (lon, lat) points strictly inside ``geom``.

    Reproducible: same (geom, n, seed) always yields the same ordered points.
    Works for Polygon and MultiPolygon. Raises if ``geom`` is empty/zero-area.
    """
    if geom is None or geom.is_empty or geom.area == 0:
        raise ValueError("geometry is empty or has zero area")
    if n <= 0:
        return []

    rng = np.random.default_rng(seed)
    minx, miny, maxx, maxy = geom.bounds
    contains = prep(geom).contains  # prepared geometry -> fast repeated contains

    out: list[tuple[float, float]] = []
    batch = max(n, 256)
    for _ in range(_MAX_BATCHES):
        xs = rng.uniform(minx, maxx, batch)
        ys = rng.uniform(miny, maxy, batch)
        for x, y in zip(xs, ys):
            if contains(Point(x, y)):
                out.append((float(x), float(y)))
                if len(out) >= n:
                    return out
    raise RuntimeError(
        f"could not collect {n} points after {_MAX_BATCHES} batches "
        "(degenerate or extremely sparse geometry?)"
    )
