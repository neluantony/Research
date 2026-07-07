"""Built-up density at a point, from the GHS-BUILT-S satellite raster.

This is the density half of the innerness score. The global raster is one
2 GB GeoTIFF in Mollweide at 100 m, so reading it point by point would be
slow — instead the window covering the city is read into memory once and
lookups are served from the array. Lookups take lon/lat. Cell values are
built-up m² per cell; nodata (negative) becomes 0. Only the within-city
ranking of values matters, not the unit.
"""
from __future__ import annotations

from typing import Callable

from shapely.geometry.base import BaseGeometry

FRAME_PAD_M = 1000.0  # window padding so edge points never fall outside


def built_density_fn(raster_path: str, frame_geom: BaseGeometry,
                     pad_m: float = FRAME_PAD_M) -> Callable[[float, float], float]:
    """Return fn(lon, lat) -> built-up surface for points within ``frame_geom``.

    ``frame_geom`` is the city frame in EPSG:4326. Points outside the padded
    window (should not happen for frame-sampled points) return 0.0.
    """
    import rasterio
    from pyproj import Transformer
    from rasterio.windows import from_bounds

    with rasterio.open(raster_path) as src:
        to_raster = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
        minx, miny, maxx, maxy = frame_geom.bounds
        # Transform the 4 bbox corners (Mollweide curves parallels; padding
        # absorbs the bow) and window the union.
        xs, ys = to_raster.transform([minx, minx, maxx, maxx],
                                     [miny, maxy, miny, maxy])
        win = from_bounds(min(xs) - pad_m, min(ys) - pad_m,
                          max(xs) + pad_m, max(ys) + pad_m,
                          src.transform).round_offsets().round_lengths()
        # boundless: if the window pokes past the raster edge, pad with nodata
        # instead of silently clipping (clipping would misalign window_transform
        # against the returned array and shift every lookup).
        fill = src.nodata if src.nodata is not None else -1.0
        arr = src.read(1, window=win, boundless=True, fill_value=fill)
        inv = ~src.window_transform(win)

    def fn(lon: float, lat: float) -> float:
        x, y = to_raster.transform(lon, lat)
        col, row = inv * (x, y)
        r, c = int(row), int(col)
        if 0 <= r < arr.shape[0] and 0 <= c < arr.shape[1]:
            v = float(arr[r, c])
            return v if v >= 0.0 else 0.0   # nodata -> 0
        return 0.0

    return fn
