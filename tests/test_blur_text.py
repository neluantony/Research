"""Tests for the text-blurring pure parts (no detector download, no DB)."""
from pathlib import Path

import pytest

from ingest.blur_text import (BLUR_SCHEME, SOURCE_SCHEME, blurred_path,
                              pad_box)


def test_schemes_are_distinct_and_versioned():
    assert BLUR_SCHEME != SOURCE_SCHEME
    assert BLUR_SCHEME.endswith("_v1")     # a scheme change must bump the label


def test_pad_box_grows_and_clips():
    # inside the image: grows by the padding on every side
    assert pad_box((10, 20, 30, 40), 640, 640, pad=4) == (6, 24, 26, 44)
    # at the image edge: clipped, never negative or past the border
    assert pad_box((0, 5, 0, 5), 640, 640, pad=4) == (0, 9, 0, 9)
    assert pad_box((630, 640, 630, 640), 640, 640, pad=4) == (626, 640, 626, 640)


def test_blurred_path_mirrors_the_image_tree():
    src = Path("data/images/paris/PANO123/h090.jpg")
    dst = blurred_path(src, "data/images_blurred")
    assert dst == Path("data/images_blurred/paris/PANO123/h090.jpg")


def test_blur_regions_changes_box_but_not_rest():
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from ingest.blur_text import blur_regions

    rng = np.random.default_rng(0)
    img = rng.integers(0, 255, (100, 100, 3), dtype="uint8")
    before = img.copy()
    blur_regions(img, [(40, 60, 40, 60)])
    # the padded box region changed, a far corner did not
    assert not np.array_equal(img[40:60, 40:60], before[40:60, 40:60])
    assert np.array_equal(img[0:20, 0:20], before[0:20, 0:20])
