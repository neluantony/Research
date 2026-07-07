"""Tests for the GHS-BUILT-S density lookup (tiny synthetic raster; no download).

Builds a small in-CRS (Mollweide) GeoTIFF with a known gradient and checks that
built_density_fn returns the right values for lon/lat queries, maps nodata to
0.0, and returns 0.0 outside the window.
"""
import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")

from rasterio.transform import from_origin
from shapely.geometry import box

from ingest.density import built_density_fn

# proj4 spelling of Mollweide (ESRI:54009): this rasterio build lacks the ESRI
# authority db; the real GHS mosaic embeds its CRS so ingest.density is unaffected.
MOLLWEIDE = "+proj=moll +lon_0=0 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
NODATA = -200.0


@pytest.fixture()
def raster(tmp_path):
    """A 100x100-cell raster (100 m cells) around Mollweide (0,0) ~ lon/lat (0,0):
    value = row index (so density grows southward); one nodata cell."""
    path = tmp_path / "built.tif"
    arr = np.repeat(np.arange(100, dtype="float32")[:, None], 100, axis=1)
    arr[50, 50] = NODATA
    with rasterio.open(
        str(path), "w", driver="GTiff", width=100, height=100, count=1,
        dtype="float32", crs=MOLLWEIDE, nodata=NODATA,
        transform=from_origin(-5000, 5000, 100, 100),  # covers +-5 km around origin
    ) as dst:
        dst.write(arr, 1)
    return str(path)


# Near (0,0), 1 deg lon ~ 100 km in Mollweide; the frame below spans ~ +-2 km.
FRAME = box(-0.02, -0.02, 0.02, 0.02)


def test_gradient_values(raster):
    fn = built_density_fn(raster, FRAME, pad_m=500)
    north, south = fn(0.0, 0.015), fn(0.0, -0.015)
    assert south > north > 0          # value grows southward by construction


def test_nodata_maps_to_zero(raster):
    fn = built_density_fn(raster, FRAME, pad_m=6000)   # window = whole raster
    # cell (50,50) center: x = -5000+50*100+50 = 50, y = 5000-50*100-50 = -50
    # in Mollweide metres ~ (0.0005 deg, -0.0005 deg)
    assert fn(0.0005, -0.0005) == 0.0


def test_outside_window_is_zero(raster):
    fn = built_density_fn(raster, FRAME, pad_m=100)
    assert fn(1.0, 1.0) == 0.0        # ~100 km away, far outside the window
